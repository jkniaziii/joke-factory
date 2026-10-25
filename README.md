# Joke Factory

A daily job that harvests dark-humor jokes, filters them hard, has a free LLM
confirm each one is a real joke, and appends the keepers to a Google Sheet.

## How it works

Once a day (GitHub Actions cron), `fetch_jokes.py`:

1. **Fetches** top-of-the-last-24h text posts from the configured subreddits
   (`r/darkjokes`, `r/DarkJokeCentral`, `r/DarkHumorAndMemes`) plus JokeAPI's
   `Dark` category.
2. **Filters**: drops link/image/too-short posts; requires Reddit posts to have
   **≥ 10 upvotes AND ≥ 10 comments**; de-dups against the sheet by identifier
   and by normalized joke text (so reposts don't sneak in).
3. **Classifies**: one free Groq (Llama) call per survivor confirms it's a
   genuine joke with an intact setup/punchline.
4. **Appends** up to **10 jokes/day** to the sheet: `Date Added | Joke | Identifier`.

Tuning knobs (subreddits, thresholds, cap, window, model) live as constants at
the top of `fetch_jokes.py`.

## One-time setup (the parts only you can do)

### 1. Reddit API key
- Go to <https://www.reddit.com/prefs/apps> → **create another app** → type **script**.
- Copy the **client ID** (under the app name) and **secret**.

### 2. Google service account + share the sheet
- In <https://console.cloud.google.com> create a project, enable the **Google
  Sheets API** and **Google Drive API**.
- Create a **service account**, then a **JSON key** for it — download the file.
- Open your spreadsheet → **Share** → paste the service account's email
  (`...@...iam.gserviceaccount.com`) → give it **Editor**. This is how the job
  writes with no human login.
- Copy the **Sheet ID** from the URL: `docs.google.com/spreadsheets/d/<SHEET_ID>/edit`.

### 3. Groq API key (free)
- <https://console.groq.com> → **API Keys** → create one. Free tier covers this
  tiny daily volume.

### 4. Add everything as GitHub Actions secrets
Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `REDDIT_CLIENT_ID` | from step 1 |
| `REDDIT_CLIENT_SECRET` | from step 1 |
| `REDDIT_USER_AGENT` | e.g. `joke-factory/1.0 by u/yourname` |
| `SHEET_ID` | from step 2 |
| `GOOGLE_SA_JSON` | **paste the entire contents** of the service-account JSON file |
| `GROQ_API_KEY` | from step 3 |

## Run it

- **Manually**: repo → **Actions → Daily dark jokes → Run workflow**.
- **Scheduled**: runs automatically at 09:00 UTC daily (change the cron in
  `.github/workflows/daily-jokes.yml`).

## Local development

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in real values
# put the service-account JSON next to the code as service-account.json
# then load .env into your shell and run:
python fetch_jokes.py
```

## Tests

Pure filter logic is unit-tested (no network/credentials needed):

```bash
pip install pytest
pytest
```
