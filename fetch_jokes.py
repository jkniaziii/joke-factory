"""Daily dark-joke harvester.

Flow: fetch (Reddit + JokeAPI) -> prefilter -> LLM classify (Groq) ->
append the keepers to a Google Sheet.

Runs headless in GitHub Actions on a daily cron. All credentials come
from environment variables (see .env.example).
"""
from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime, timezone

import gspread
import praw
import requests
from google.oauth2.service_account import Credentials
from groq import Groq

from filters import Candidate, normalize_text, prefilter

# --------------------------------------------------------------------------
# Tunable constants — change these, not the logic below.
# --------------------------------------------------------------------------
SUBREDDITS = ["darkjokes", "DarkJokeCentral", "DarkHumorAndMemes"]
TIME_WINDOW = "day"      # Reddit "top" window: fetch top-of-the-last-24h
FETCH_LIMIT = 50         # posts pulled per subreddit before filtering
MIN_SCORE = 10           # Reddit upvote floor
MIN_COMMENTS = 10        # Reddit comment-count floor
DAILY_CAP = 10           # max jokes appended to the sheet per run
INCLUDE_JOKEAPI = True
GROQ_MODEL = "llama-3.3-70b-versatile"

SHEET_HEADERS = ["Date Added", "Joke", "Identifier"]
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


# --------------------------------------------------------------------------
# Fetchers
# --------------------------------------------------------------------------
def fetch_reddit_jokes() -> list[Candidate]:
    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "joke-factory/1.0"),
    )
    out: list[Candidate] = []
    for sub in SUBREDDITS:
        for post in reddit.subreddit(sub).top(time_filter=TIME_WINDOW, limit=FETCH_LIMIT):
            # Text posts only: skip links, images, galleries, crossposts.
            if not post.is_self:
                continue
            body = (post.title or "").strip()
            if post.selftext:
                body = f"{body}\n\n{post.selftext.strip()}".strip()
            out.append(
                Candidate(
                    text=body,
                    identifier=f"reddit-{post.id}",
                    source="reddit",
                    score=int(post.score),
                    comments=int(post.num_comments),
                )
            )
    return out


def fetch_jokeapi_jokes() -> list[Candidate]:
    if not INCLUDE_JOKEAPI:
        return []
    url = (
        "https://v2.jokeapi.dev/joke/Dark"
        "?amount=10&format=json&type=single,twopart"
    )
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"[jokeapi] skipped: {exc}", file=sys.stderr)
        return []

    jokes = data.get("jokes", []) if "jokes" in data else [data]
    out: list[Candidate] = []
    for j in jokes:
        if j.get("error"):
            continue
        if j.get("type") == "twopart":
            text = f"{j.get('setup', '').strip()}\n{j.get('delivery', '').strip()}"
        else:
            text = (j.get("joke") or "").strip()
        text = html.unescape(text).strip()
        if not text:
            continue
        out.append(
            Candidate(
                text=text,
                identifier=f"jokeapi-{j.get('id')}",
                source="jokeapi",
            )
        )
    return out


# --------------------------------------------------------------------------
# LLM classification
# --------------------------------------------------------------------------
CLASSIFY_PROMPT = (
    "You are a strict classifier for a dark-humor joke collection.\n"
    "Return KEEP only if the text is a genuine, self-contained dark-humor "
    "JOKE with an intact setup and punchline (or a clear one-liner joke).\n"
    "Return DROP if it is: not actually a joke, a meme caption needing an "
    "image, a question to the community, a story, incomplete/removed/deleted, "
    "or just offensive with no joke structure.\n"
    "Reply with exactly one word: KEEP or DROP.\n\n"
    "TEXT:\n{joke}"
)


def classify_joke(client: Groq, text: str) -> bool:
    try:
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": CLASSIFY_PROMPT.format(joke=text)}],
            temperature=0,
            max_tokens=4,
        )
        verdict = (resp.choices[0].message.content or "").strip().upper()
        return verdict.startswith("KEEP")
    except Exception as exc:  # noqa: BLE001 — never let one bad call kill the run
        print(f"[groq] classify failed, dropping candidate: {exc}", file=sys.stderr)
        return False


# --------------------------------------------------------------------------
# Google Sheets
# --------------------------------------------------------------------------
def open_sheet() -> gspread.Worksheet:
    raw = os.environ.get("GOOGLE_SA_JSON")
    if raw:
        info = json.loads(raw)
        creds = Credentials.from_service_account_info(info, scopes=GOOGLE_SCOPES)
    else:
        path = os.environ.get("GOOGLE_SA_JSON_PATH", "service-account.json")
        creds = Credentials.from_service_account_file(path, scopes=GOOGLE_SCOPES)

    gc = gspread.authorize(creds)
    sh = gc.open_by_key(os.environ["SHEET_ID"])
    ws = sh.sheet1
    # Ensure the header row exists exactly once.
    existing = ws.get_all_values()
    if not existing:
        ws.append_row(SHEET_HEADERS, value_input_option="USER_ENTERED")
    return ws


def load_seen(ws: gspread.Worksheet) -> tuple[set[str], set[str]]:
    rows = ws.get_all_values()
    seen_ids: set[str] = set()
    seen_texts: set[str] = set()
    for row in rows[1:]:  # skip header
        if len(row) >= 2 and row[1]:
            seen_texts.add(normalize_text(row[1]))
        if len(row) >= 3 and row[2]:
            seen_ids.add(row[2])
    return seen_ids, seen_texts


def append_jokes(ws: gspread.Worksheet, candidates: list[Candidate]) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = [[today, c.text, c.identifier] for c in candidates]
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def main() -> int:
    print("Fetching candidates...")
    candidates = fetch_reddit_jokes() + fetch_jokeapi_jokes()
    print(f"  fetched {len(candidates)} raw candidates")

    ws = open_sheet()
    seen_ids, seen_texts = load_seen(ws)
    print(f"  sheet already has {len(seen_ids)} identified jokes")

    survivors = prefilter(
        candidates,
        min_score=MIN_SCORE,
        min_comments=MIN_COMMENTS,
        seen_identifiers=seen_ids,
        seen_norm_texts=seen_texts,
    )
    print(f"  {len(survivors)} passed prefilter")

    groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    kept: list[Candidate] = []
    for c in survivors:
        if len(kept) >= DAILY_CAP:
            break
        if classify_joke(groq_client, c.text):
            kept.append(c)
    print(f"  {len(kept)} passed LLM classification (cap {DAILY_CAP})")

    append_jokes(ws, kept)
    print(f"Done. Appended {len(kept)} jokes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
