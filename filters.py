"""Pure, side-effect-free filtering logic for joke candidates.

Kept separate from fetch_jokes.py so it can be unit-tested without any
network, Reddit, Groq, or Google Sheets access.
"""
from __future__ import annotations

import re
import string
from dataclasses import dataclass, field


@dataclass
class Candidate:
    """A joke pulled from a source, before filtering/classification."""

    text: str
    identifier: str  # stable dedup key, e.g. "reddit-<post_id>" / "jokeapi-<id>"
    source: str  # "reddit" or "jokeapi"
    score: int = 0  # Reddit upvotes (0 for non-Reddit)
    comments: int = 0  # Reddit comment count (0 for non-Reddit)
    extra: dict = field(default_factory=dict)


_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Lowercase, strip punctuation and collapse whitespace.

    Used for the reposted-joke check so "Why did the..." and
    "why did the ...!" collapse to the same key.
    """
    lowered = text.lower()
    no_punct = lowered.translate(str.maketrans("", "", string.punctuation))
    return _WS.sub(" ", no_punct).strip()


def is_text_joke(text: str) -> bool:
    """Reject empty, link-only, or trivially short posts."""
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < 10:
        return False
    # Link/image posts that slipped through as "text".
    if re.fullmatch(r"https?://\S+", stripped):
        return False
    return True


def passes_reddit_gate(candidate: Candidate, min_score: int, min_comments: int) -> bool:
    """Engagement gate. Only applies to Reddit candidates.

    Non-Reddit sources (e.g. JokeAPI, which is curated and has no scores)
    skip the gate and are judged by format + LLM classification alone.
    """
    if candidate.source != "reddit":
        return True
    return candidate.score >= min_score and candidate.comments >= min_comments


def is_duplicate(
    candidate: Candidate,
    seen_identifiers: set[str],
    seen_norm_texts: set[str],
) -> bool:
    """True if this joke is already in the sheet, by id or normalized text."""
    if candidate.identifier in seen_identifiers:
        return True
    if normalize_text(candidate.text) in seen_norm_texts:
        return True
    return False


def prefilter(
    candidates: list[Candidate],
    *,
    min_score: int,
    min_comments: int,
    seen_identifiers: set[str],
    seen_norm_texts: set[str],
) -> list[Candidate]:
    """Apply every cheap, deterministic filter before the LLM pass.

    Also de-dups within the current batch itself (two sources, or two
    subreddits, surfacing the same joke in one run).
    """
    kept: list[Candidate] = []
    batch_ids = set(seen_identifiers)
    batch_texts = set(seen_norm_texts)
    for c in candidates:
        if not is_text_joke(c.text):
            continue
        if not passes_reddit_gate(c, min_score, min_comments):
            continue
        if is_duplicate(c, batch_ids, batch_texts):
            continue
        kept.append(c)
        batch_ids.add(c.identifier)
        batch_texts.add(normalize_text(c.text))
    return kept
