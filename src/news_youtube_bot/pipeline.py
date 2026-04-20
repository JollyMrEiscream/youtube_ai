from __future__ import annotations

import logging
import sys
from pathlib import Path

from openai import OpenAI

from news_youtube_bot.config import Settings, load_feed_urls
from news_youtube_bot.dedupe import dedupe_items
from news_youtube_bot.llm_gemini import build_script_gemini, rank_stories_gemini
from news_youtube_bot.llm_rank import rank_stories
from news_youtube_bot.llm_script import build_script
from news_youtube_bot.rss_ingest import ingest_all
from news_youtube_bot.tts_render import render_tts
from news_youtube_bot.video_render import build_video
from news_youtube_bot.window_filter import filter_by_window
from news_youtube_bot.youtube_upload import upload_video

logger = logging.getLogger(__name__)


def run(project_root: Path, settings: Settings) -> int:
    project_root = project_root.resolve()
    settings.output_dir.mkdir(parents=True, exist_ok=True)

    feed_pairs = load_feed_urls(settings, project_root)
    raw = ingest_all(settings, feed_pairs)
    filtered = filter_by_window(raw, settings.news_window_minutes)
    deduped = dedupe_items(filtered)

    if not deduped:
        logger.warning("No stories in the configured time window; nothing to publish")
        return 0

    if settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            logger.error("GEMINI_API_KEY (or GOOGLE_API_KEY) is required when using Gemini for LLM")
            return 1
        ranked = rank_stories_gemini(
            settings.gemini_api_key,
            settings.gemini_model,
            deduped,
            settings.max_stories,
        )
        meta = build_script_gemini(settings.gemini_api_key, settings.gemini_model, ranked)
    else:
        if not settings.openai_api_key:
            logger.error("OPENAI_API_KEY is required when LLM_PROVIDER=openai (default)")
            return 1
        client = OpenAI(api_key=settings.openai_api_key)
        ranked = rank_stories(client, settings.openai_model, deduped, settings.max_stories)
        meta = build_script(client, settings.openai_model, ranked)

    script: str = meta["script"]
    video_title = str(meta.get("video_title") or "News summary")[:100]
    description = str(meta.get("description") or "").strip()
    llm_tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
    tag_strings = [str(t) for t in llm_tags if str(t).strip()]
    tags = list(dict.fromkeys(tag_strings + settings.default_tags))[:500]

    description = (
        description
        + "\n\n---\nThis video uses AI-generated voiceover. Automated RSS headline summary; "
        "verify facts using the linked sources."
    )

    audio_path = settings.output_dir / "voice.mp3"
    video_path = settings.output_dir / "episode.mp4"

    render_tts(settings, script, audio_path)
    lead_link = ranked[0].link if ranked else None
    build_video(settings, audio_path, video_title, lead_link, video_path)

    if settings.dry_run:
        logger.info("DRY_RUN enabled: skipping YouTube upload (artifacts in %s)", settings.output_dir)
        return 0

    if not settings.youtube_refresh_token:
        logger.error("YOUTUBE_REFRESH_TOKEN missing; set DRY_RUN=1 to skip upload")
        return 1

    upload_video(settings, video_path, video_title, description, tags)
    return 0


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
