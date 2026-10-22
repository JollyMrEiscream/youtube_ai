# Technology YouTube Shorts

A daily pipeline that turns fresh technology reporting into vertical Shorts. It pulls stories, skips ones already used, writes a short script, records a voiceover, cuts real footage under burned-in captions, and parks the file for review. Upload is a separate step, capped so it stays inside YouTube's quota.

The default batch is **5 Shorts a day**. That number is `DAILY_SHORTS`. Set it to 30 when you actually want thirty. Five is the default because each video is meant to be watched by a person before it goes up. See [docs/engagement.md](docs/engagement.md) for the research behind the edit (hook, length, captions, motion, and YouTube's inauthentic-content rule).

This used to be one hourly landscape digest. It is now one story per Short.

## One command

From the repo root, with [ffmpeg](https://ffmpeg.org/) installed:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m news_youtube_bot run --count 1
```

That renders one Short into `output/review/pending/<id>/short.mp4` and does not upload it. The full default batch:

```bash
python -m news_youtube_bot run
```

Thirty, if you mean it:

```bash
python -m news_youtube_bot run --count 30
```

The script and the voice do not need a key: the offline writer uses the headline and the article text, and the voice is Microsoft Edge neural TTS. The picture does. Without `PEXELS_API_KEY`, `PIXABAY_API_KEY`, or `XAI_API_KEY` the run logs the missing keys and parks the Short in the review queue as rejected, with the reason, instead of building a slideshow. A Gemini or OpenAI key makes the script tighter. The run logs which path it took.

PowerShell equivalents of the env vars below use `$env:NAME = "value"`.

## Review, then upload

New files land in `output/review/pending/`. Each folder has `short.mp4`, `script.txt`, `captions.ass`, and `meta.json`. `output/review/INDEX.md` is the list.

```bash
python -m news_youtube_bot review list
python -m news_youtube_bot review show 20261022-01-ab12cd
python -m news_youtube_bot review approve 20261022-01-ab12cd
python -m news_youtube_bot review reject 20261022-01-ab12cd --reason "thin source"
python -m news_youtube_bot upload
```

`upload` sends **approved** videos only, oldest first, and stops at the daily cap. Anything past the cap stays approved and is picked up on the next upload. Rejected videos are kept so you can see what you turned down.

Upload without a person watching is two switches, both off by default:

| Switch | What it does |
| --- | --- |
| `AUTO_UPLOAD=1` | After a render, upload videos that are already approved. Today's new files stay pending. |
| `SKIP_REVIEW=1` | Treat today's new files as approved. Does nothing by itself. |
| Both, and `DRY_RUN` unset | Upload today's Shorts with no review. This is the explicit opt-in. |

`DRY_RUN=1` blocks upload even if those are set. The GitHub Action defaults `DRY_RUN` to `1`.

YouTube's monetization rules (July 2025, "inauthentic content") refuse channels whose videos feel interchangeable, including slideshows and mass-produced narration. Rotating voices and hooks reduces that sameness. It does not clear the rule for you. The review step is how you keep a thin or repetitive Short off the channel. Details and links are in [docs/engagement.md](docs/engagement.md).

## What each Short is made of

1. **Stories.** Tech RSS (`config/feeds.yaml`), the Hacker News frontpage and newest list, and NewsAPI if `NEWS_API_KEY` is set. The default window is 36 hours. If that is too thin, the run widens it and says so.
2. **Deduping.** Same URL and near-duplicate titles are dropped inside the batch. `data/seen.sqlite` remembers stories already rendered, so tomorrow does not remake them. Fuzzy title matching looks at the last 400 used stories.
3. **Picking.** With a model key, the model ranks for a one-minute tech Short and avoids two clips about the same event. Without a key, a local rank prefers recent tech-flagged items and will not take five stories from one outlet when others exist.
4. **Script.** Eight profiles (question, claim, story, stakes, skeptic, briefing, one number, so-what) change the open, the shape, the voice, the pace, the caption color, and the music. The spoken target is about 95–140 words. The first sentence is the hook. The close points at the source. The model is told not to invent facts that are not in the article.
5. **Voice.** Edge neural voices by default, a different voice and rate per profile, with word timings for captions. `TTS_ENGINE=openai` uses `TTS_MODEL` (default `tts-1-hd`).
6. **Picture.** 1080×1920, hard-cut from real video. Each spoken beat (about 2–3 seconds, on a word boundary) gets its own stock-video search: Pexels Videos, then Pixabay Videos, using keywords from that line (product, company, place, action). Clips have to survive a 9:16 crop at 720p or better. The strongest 1.5–3 seconds is what gets used. There is no Ken Burns pass over a photo, and Wikimedia is not a footage source. If stock has nothing usable, xAI Grok Imagine (`grok-imagine-video-1.5`, 9:16, 720p, silent) can generate a short photoreal clip, up to `MAX_AI_CLIPS_PER_DAY`. A clip used in one Short is not reused for a week. The article's lead image may appear once as a small inset over moving footage, and stills never fill the frame. If moving video cannot cover the voice, the Short is rejected with a reason instead of shipped as a slideshow. Captions highlight the current word. A music bed ducks under the voice.
7. **Credits and disclosure.** The description lists the story URL, each clip's Pexels or Pixabay credit (or the Grok model, for a generated shot), and the music source, and says the voice is synthetic. The same credits are stored on the review record. The upload sets YouTube's synthetic-media flag when the API accepts it.

The lead image can include a copyrighted photo, which is why it is an inset and why the review step exists. Footage is only Pexels, Pixabay, or a clip this tool generated. It does not download YouTube or news-site video.

## Keys

Copy `.env.example` to `.env`. The loader fills in anything not already exported. Never commit `.env`.

| Variable | Required | Role |
| --- | --- | --- |
| `GEMINI_API_KEY` | No | Ranking and scripts. Free tier in [Google AI Studio](https://aistudio.google.com/apikey). `GOOGLE_API_KEY` is also accepted. |
| `OPENAI_API_KEY` | No | Same, if `LLM_PROVIDER=openai`. Also required for `TTS_ENGINE=openai`. |
| `PEXELS_API_KEY` | For stock video | [Pexels API](https://www.pexels.com/api/). Free for the videos their license allows. As of this writing, Pexels has paused issuing new keys. |
| `PIXABAY_API_KEY` | For stock video | [Pixabay API](https://pixabay.com/api/docs/), issued when you are logged in. Videos are used under Pixabay's license. |
| `XAI_API_KEY` | For generated b-roll | [xAI console](https://console.x.ai/). Used only when stock search misses a beat. Model defaults to `grok-imagine-video-1.5` ([video generation docs](https://docs.x.ai/developers/model-capabilities/video/generation)). |
| `NEWS_API_KEY` | No | Extra headlines from [NewsAPI](https://newsapi.org/). Their free plan is for development, not production. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` | Only to upload | YouTube Data API OAuth. See below. |

`TTS_VOICE` locks every video to one voice. Leave it empty to rotate.

## YouTube quota

Two different limits show up in Google's docs, and older Cloud projects may still be on the first one:

- The classic quota is **10,000 units per day**, and `videos.insert` costs about **1,600 units**. That is about **6 uploads a day**.
- Current docs also give `videos.insert` its **own bucket of about 100 uploads a day**, at 1 unit each, separate from the 10,000-unit pool used by other methods. Check the Quotas page in Google Cloud for the project you actually use. The quota day resets at **midnight Pacific**.

This tool keeps its own counter in `data/quota.json` and will not upload past a cap. The defaults match the tighter classic math:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAX_UPLOADS_PER_DAY` | `6` | Hard cap for this tool, even if Google would allow more. |
| `UPLOAD_QUOTA_COST` | `1600` | Units charged to the local counter per successful upload. |
| `YOUTUBE_DAILY_QUOTA_UNITS` | `10000` | Units available per day in that counter. |

`6` is `min(6, 10000 // 1600)`. Approved videos past the cap stay approved and go out the next day. The counter does not see uploads you make by hand in YouTube Studio.

If your Cloud project's upload quota is the newer 100-a-day bucket and you want to use it, set `UPLOAD_QUOTA_COST=1`, `YOUTUBE_DAILY_QUOTA_UNITS=100`, and raise `MAX_UPLOADS_PER_DAY`. Leave the cap at 6 if you are posting five reviewed Shorts. Raising it toward 30 is how you outrun a review, which is the thing the monetization rule punishes.

Docs: [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert), [quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost).

## OAuth (one time, only if you upload)

1. In Google Cloud Console, enable **YouTube Data API v3**, create an **OAuth client ID** (Desktop), and download the JSON.
2. Run:

```bash
python scripts/youtube_oauth_setup.py --client-secret path/to/client_secret.json
```

3. Put the printed `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `YOUTUBE_REFRESH_TOKEN` in `.env` or in GitHub Actions secrets. Do not commit them.

Privacy defaults to `private`. Category defaults to `28` (Science & Technology).

## Scheduling

A persistent machine is the reliable setup, because the review queue and the seen-story database need a disk.

```cron
15 8 * * * /path/to/youtube_ai/scripts/run_daily.sh >> /path/to/youtube_ai/logs/daily.log 2>&1
0 18 * * * cd /path/to/youtube_ai && .venv/bin/python -m news_youtube_bot upload
```

The morning job only renders. You approve during the day. The evening job uploads up to the cap.

GitHub Actions:

- [`.github/workflows/daily_shorts.yml`](.github/workflows/daily_shorts.yml) renders at 13:15 UTC and uploads the review folder as an artifact. `DRY_RUN` defaults to `1`.
- [`.github/workflows/upload_approved.yml`](.github/workflows/upload_approved.yml) is manual. Pass comma-separated ids to approve those renders (from the cached queue) and upload up to the cap.

Actions cache is best-effort and can be evicted. If the cache misses, the upload workflow has nothing to send. For a channel you care about, run cron on a machine you control. The old hourly digest workflow is gone.

Repository secrets: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `XAI_API_KEY`, `NEWS_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN`, optional `RSS_FEED_URLS` (one URL per line).

Repository variables worth setting: `DAILY_SHORTS`, `LLM_PROVIDER`, `TTS_ENGINE`, `DRY_RUN`, `AUTO_UPLOAD`, `SKIP_REVIEW`, `MAX_UPLOADS_PER_DAY`, `MAX_AI_CLIPS_PER_DAY`, `XAI_VIDEO_MODEL`. Empty variables fall through to the defaults in the app.

## Cost

Figures are estimates for a ~700-character voiceover and a short script call. Check the vendor pages before you scale. Prices move.

| Piece | 1 Short | 5 / day | 30 / day |
| --- | --- | --- | --- |
| Edge TTS + Pexels or Pixabay video | $0 | $0 | $0 |
| Gemini Flash script and rank, free tier | $0 within the free quota | $0 for a personal day | May hit free-tier rate limits; paid Flash is still well under a cent a Short |
| OpenAI `gpt-4o-mini` script and rank | well under $0.01 | a few cents | still a few cents |
| OpenAI TTS `tts-1` (~$15 / 1M chars) | ~$0.01 | ~$0.05 | ~$0.30 |
| OpenAI TTS `tts-1-hd` (~$30 / 1M chars) | ~$0.02 | ~$0.10 | ~$0.60 |
| xAI Grok Imagine video, about 4s requested then trimmed | Check [xAI pricing](https://docs.x.ai/developers/models/grok-imagine-video). `grok-imagine-video` is listed around $0.05/second; `grok-imagine-video-1.5` may differ. A 4s clip is on the order of $0.20 if that rate holds. | Up to `MAX_AI_CLIPS_PER_DAY` (default 10), so a few dollars if every clip is generated. Stock misses should be rare once a video key is set. | Raise the cap only if you mean to pay for it. 30 fully generated Shorts is a large bill. |
| YouTube Data API | $0 inside the quota above | 5 uploads fit the default cap of 6 | 30 does not fit a 1,600-unit insert; the rest queue |
| GitHub-hosted minutes | a few minutes of render | modest | a 30-video day is a long Actions job |

Edge TTS plus a Pexels or Pixabay key is the cheap picture path. Grok is the paid fallback, capped by `MAX_AI_CLIPS_PER_DAY`. OpenAI HD voice is the other line item if you turn it on. Render time is CPU, not an API bill: one Short is typically a couple of minutes once clips are downloaded. Generated clips are cached under `data/cache/clips/`, and the daily counter is `data/ai_clip_budget.json`.

Pricing pages: [OpenAI](https://platform.openai.com/docs/pricing), [Gemini](https://ai.google.dev/gemini-api/docs/pricing).

## Layout

| Path | What it is |
| --- | --- |
| `output/review/pending/` | Rendered, not approved |
| `output/review/approved/` | Waiting to upload, including anything the quota held back |
| `output/review/rejected/` | Turned down |
| `output/review/uploaded/` | Sent, with the YouTube id in `meta.json` |
| `data/seen.sqlite` | Stories already used |
| `data/quota.json` | Uploads counted against today's Pacific quota day |
| `data/cache/clips/` | Downloaded and generated footage |
| `data/used_clips.json` | Clip ids used in the last week |
| `data/ai_clip_budget.json` | Grok clips counted for today |
| `assets/music/` | Optional licensed tracks. Empty means a generated bed |
| `config/feeds.yaml` | RSS list |

`output/` and `data/` are gitignored.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## What is still yours to provide

This environment has no `PEXELS_API_KEY`, `PIXABAY_API_KEY`, or `XAI_API_KEY`, so a real stock or Grok Short was not rendered here. `pytest` covers those APIs with mocked responses. To get a picture that is real video, add:

- `PEXELS_API_KEY` or `PIXABAY_API_KEY` so beats are cut from stock video. Without one of these, or `XAI_API_KEY`, the Short is rejected instead of rendered
- `XAI_API_KEY` if you want Grok to cover beats that stock search misses. Optional once a stock key is set. Raise `MAX_AI_CLIPS_PER_DAY` if a day needs more than 10 generated shots
- `GEMINI_API_KEY` (or `OPENAI_API_KEY`) so scripts stop using the offline writer
- The three YouTube OAuth values before `upload` will succeed

Until a footage key exists, `python -m news_youtube_bot run --count 1` still writes the script and the voice, then leaves a rejected review record that names the missing keys. It does not upload, and it does not make a slideshow.
