# News YouTube Bot

Fetches recent items from RSS feeds, ranks stories with an LLM, generates a voiceover (OpenAI TTS or Edge TTS), builds a short MP4 with FFmpeg, and uploads to YouTube.

## Free tier (no OpenAI bill)

Use **Google Gemini** (free quota in [Google AI Studio](https://aistudio.google.com/apikey)) for ranking + script, and **Edge TTS** for voice (no key):

```powershell
$env:LLM_PROVIDER = "gemini"   # optional if only GEMINI_API_KEY is set (no OPENAI_API_KEY)
$env:GEMINI_API_KEY = "your-ai-studio-key"
$env:GEMINI_MODEL = "gemini-1.5-flash"   # or another flash model your key supports
$env:TTS_ENGINE = "edge"
$env:TTS_VOICE = "en-US-GuyNeural"
$env:DRY_RUN = "1"
python -m news_youtube_bot
```

YouTube uploads and GitHub Actions minutes are still subject to each platform’s free limits and policies.

## Quick start (local)

```powershell
cd c:\Users\levi\youtube_ai
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
# Edit config\feeds.yaml with your RSS URLs (file is in the repo by default)
$env:OPENAI_API_KEY = "sk-..."
$env:DRY_RUN = "1"
python -m news_youtube_bot
```

Outputs under `output/` when not dry-run; with `DRY_RUN=1`, artifacts still go to `output/` by default (override with `OUTPUT_DIR`).

## Environment variables

| Variable | Description |
|----------|-------------|
| `RSS_FEED_URLS` | Newline-separated RSS URLs (overrides `FEEDS_FILE` if set) |
| `FEEDS_FILE` | Path to YAML list of feeds (default `config/feeds.yaml`) |
| `NEWS_WINDOW_MINUTES` | Rolling window for item `published` time (default `90`) |
| `MAX_STORIES` | Top stories after ranking (default `5`) |
| `LLM_PROVIDER` | `openai` or `gemini` (default: `openai`; if unset and only `GEMINI_API_KEY` is set, uses `gemini`) |
| `GEMINI_API_KEY` | Google AI Studio / Gemini API key (for `LLM_PROVIDER=gemini`; `GOOGLE_API_KEY` also accepted) |
| `GEMINI_MODEL` | Gemini model id (default `gemini-1.5-flash`) |
| `OPENAI_API_KEY` | Required for `LLM_PROVIDER=openai`; also required if `TTS_ENGINE=openai` |
| `OPENAI_MODEL` | Chat model (default `gpt-4o-mini`) |
| `TTS_ENGINE` | `openai` or `edge` (default `openai`; use `edge` for free voiceover) |
| `TTS_VOICE` | OpenAI voice e.g. `alloy`, or Edge voice e.g. `en-US-GuyNeural` |
| `VIDEO_WIDTH` / `VIDEO_HEIGHT` | Default `1920` x `1080` (use `1080` x `1920` for Shorts) |
| `DRY_RUN` | Set to `1` to skip YouTube upload |
| `OUTPUT_DIR` | Working output directory (default `output`) |
| `YOUTUBE_PRIVACY` | `private`, `unlisted`, or `public` (default `private`) |
| `GOOGLE_CLIENT_ID` | OAuth client ID (upload) |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret |
| `YOUTUBE_REFRESH_TOKEN` | OAuth refresh token from setup script |

## YouTube OAuth (one-time)

1. In Google Cloud Console: enable **YouTube Data API v3**, create **OAuth client ID** (Desktop app), download JSON.
2. Run:

```powershell
python scripts\youtube_oauth_setup.py --client-secret path\to\client_secret.json
```

3. The script prints **GitHub-ready lines** for `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN`. Add each value as a separate repository secret (see below).

## GitHub Actions

Workflow [`.github/workflows/hourly_news.yml`](.github/workflows/hourly_news.yml) runs on a schedule (hourly, UTC) and on **Run workflow** (`workflow_dispatch`). Runs use GitHub-hosted runners, so your PC does not need to be on.

**Repository:** Use a normal GitHub repo (not a fork) on your account, with the workflow on the **default branch** (e.g. `main`), or scheduled runs will not apply.

### First-time: push this project to GitHub

```powershell
cd c:\Users\levi\youtube_ai
git init -b main
git add -A
git commit -m "Initial commit: news YouTube bot"
# Create an empty repo on github.com (no README), then:
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

### Repository secrets (Settings → Secrets and variables → Actions)

| Secret | When needed |
|--------|----------------|
| `GEMINI_API_KEY` | Free LLM path (`LLM_PROVIDER=gemini` or only Gemini key set) |
| `OPENAI_API_KEY` | OpenAI LLM and/or OpenAI TTS |
| `GOOGLE_CLIENT_ID` | YouTube upload (not dry-run) |
| `GOOGLE_CLIENT_SECRET` | YouTube upload |
| `YOUTUBE_REFRESH_TOKEN` | YouTube upload |
| `RSS_FEED_URLS` | Optional: multiline secret (one RSS URL per line); overrides `config/feeds.yaml` |

### Repository variables (same page, **Variables** tab)

These are passed into the workflow as `vars.*`. Omit any you are happy to leave at app defaults.

| Variable | Typical use |
|----------|-------------|
| `LLM_PROVIDER` | `gemini` or `openai` |
| `GEMINI_MODEL` | e.g. `gemini-1.5-flash` |
| `OPENAI_MODEL` | e.g. `gpt-4o-mini` |
| `NEWS_WINDOW_MINUTES` | Rolling window for RSS items |
| `MAX_STORIES` | Cap after ranking |
| `TTS_ENGINE` | `openai` or `edge` |
| `TTS_VOICE` | OpenAI or Edge voice id |
| `VIDEO_WIDTH` / `VIDEO_HEIGHT` | e.g. `1920` / `1080` or Shorts size |
| `YOUTUBE_PRIVACY` | `private`, `unlisted`, or `public` |
| `YOUTUBE_CATEGORY_ID` | YouTube category (default in code: News) |
| `YOUTUBE_TAGS` | Comma-separated tags |
| `DRY_RUN` | Set to `1` first to test without uploading; then `0` for real uploads |

### Validate before relying on the schedule

1. Add at least one LLM secret (`GEMINI_API_KEY` or `OPENAI_API_KEY`) and set variables as needed; set `DRY_RUN` to `1`.
2. Open **Actions** → **Hourly news YouTube bot** → **Run workflow** → Run. Confirm the job succeeds.
3. For live uploads, add the three YouTube OAuth secrets, set `DRY_RUN` to `0`, and run the workflow again.

Feeds for CI: this repo includes [`config/feeds.yaml`](config/feeds.yaml). To avoid committing feed URLs, remove or replace that file in git and use the `RSS_FEED_URLS` secret instead.
