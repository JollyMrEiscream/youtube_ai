from __future__ import annotations

import logging
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from openai import OpenAI

from news_youtube_bot.article import download_file, excerpt_from_html, fetch_page, og_image_url
from news_youtube_bot.config import Settings, active_llm_provider, load_feed_urls
from news_youtube_bot.dedupe import dedupe_items
from news_youtube_bot.footage import FootageRejected, VisualShot, assemble_footage, log_footage_keys
from news_youtube_bot.history import StoryHistory
from news_youtube_bot.hn_ingest import fetch_hacker_news
from news_youtube_bot.llm_gemini import build_script_gemini, rank_stories_gemini
from news_youtube_bot.llm_rank import rank_stories
from news_youtube_bot.llm_script import build_script
from news_youtube_bot.media import ffprobe_duration, find_font
from news_youtube_bot.models import NewsItem
from news_youtube_bot.music import prepare_bed
from news_youtube_bot.newsapi_ingest import fetch_newsapi
from news_youtube_bot.publish import decide_upload, publish_approved
from news_youtube_bot.rank_local import select_stories
from news_youtube_bot.review_queue import ReviewQueue
from news_youtube_bot.rss_ingest import ingest_all
from news_youtube_bot.script_local import build_script_local
from news_youtube_bot.textutil import word_count
from news_youtube_bot.tts_render import render_tts
from news_youtube_bot.variety import Profile, assign_profiles
from news_youtube_bot.video_render import render_short
from news_youtube_bot.window_filter import filter_by_window

logger = logging.getLogger(__name__)

XAI_CHAT_BASE = "https://api.x.ai/v1"


def chat_client(settings: Settings) -> OpenAI:
    """OpenAI SDK. xAI speaks the same chat API at api.x.ai."""
    if active_llm_provider(settings) == "xai":
        return OpenAI(api_key=settings.xai_api_key, base_url=XAI_CHAT_BASE)
    return OpenAI(api_key=settings.openai_api_key)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def _gather(settings: Settings, project_root: Path) -> list[NewsItem]:
    raw = ingest_all(settings, load_feed_urls(settings, project_root))
    raw.extend(fetch_hacker_news(settings.fetch_timeout_seconds, limit=max(20, settings.daily_shorts * 6)))
    if settings.news_api_key:
        raw.extend(fetch_newsapi(settings.news_api_key, settings.fetch_timeout_seconds))
    filtered = filter_by_window(raw, settings.news_window_minutes)
    if len(filtered) < settings.daily_shorts:
        wider = min(max(settings.news_window_minutes * 4, 3 * 24 * 60), 7 * 24 * 60)
        logger.warning(
            "Only %d stories in the %d-minute window; widening to %d minutes",
            len(filtered),
            settings.news_window_minutes,
            wider,
        )
        filtered = filter_by_window(raw, wider)
    return dedupe_items(filtered)


def _rank(settings: Settings, provider: str, items: list[NewsItem]) -> list[NewsItem]:
    count = min(settings.daily_shorts, len(items))
    if provider == "gemini" and settings.gemini_api_key:
        try:
            return rank_stories_gemini(settings.gemini_api_key, settings.gemini_model, items, count)
        except Exception:
            logger.exception("Gemini ranking failed; using the offline editor")
    if provider == "openai" and settings.openai_api_key:
        try:
            return rank_stories(chat_client(settings), settings.openai_model, items, count)
        except Exception:
            logger.exception("OpenAI ranking failed; using the offline editor")
    if provider == "xai" and settings.xai_api_key:
        try:
            return rank_stories(chat_client(settings), settings.xai_chat_model, items, count)
        except Exception:
            logger.exception("xAI ranking failed; using the offline editor")
    return select_stories(items, count)


def _script(settings: Settings, provider: str, item: NewsItem, profile: Profile, excerpt: str) -> dict:
    try:
        if provider == "gemini" and settings.gemini_api_key:
            return build_script_gemini(settings.gemini_api_key, settings.gemini_model, item, profile, excerpt)
        if provider == "openai" and settings.openai_api_key:
            return build_script(chat_client(settings), settings.openai_model, item, profile, excerpt)
        if provider == "xai" and settings.xai_api_key:
            return build_script(chat_client(settings), settings.xai_chat_model, item, profile, excerpt)
    except Exception:
        logger.exception("Script model failed for %s; using the offline writer", item.title[:80])
    return build_script_local(item, profile, excerpt)


@dataclass
class RenderOutcome:
    item_id: str
    status: str
    retryable: bool


def _description(meta: dict, item: NewsItem, credits: list[str], music_credit: str) -> str:
    base = str(meta.get("description") or "").strip()
    footage = "\n".join(f"- {credit}" for credit in credits) or "- No footage matched."
    text = (
        f"{base}\n\n"
        f"Source: {item.title}\n{item.link}\n\n"
        f"Footage:\n{footage}\n"
        f"- {music_credit}\n\n"
        "Voiceover is text-to-speech. This Short briefs the linked report. "
        "It is not original reporting, so read the source before you repeat the details.\n\n"
        "#Shorts"
    )
    return text[:4900]


def _tags(meta: dict, settings: Settings) -> list[str]:
    tags: list[str] = []
    for tag in list(meta.get("tags") or []) + settings.default_tags + ["shorts"]:
        text = str(tag).strip()
        if text and text.lower() not in {existing.lower() for existing in tags}:
            tags.append(text)
    return tags[:30]


def _lead_image(settings: Settings, page: str | None, folder: Path) -> Path | None:
    if not settings.capture_sources or not page:
        return None
    image_url = og_image_url(page)
    if not image_url:
        return None
    suffix = Path(urlparse(image_url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    image_path = folder / f"source-image{suffix}"
    if download_file(image_url, image_path, settings.fetch_timeout_seconds, max_bytes=4_000_000):
        return image_path
    return None


def _record(
    settings: Settings,
    item: NewsItem,
    profile: Profile,
    meta: dict,
    script: str,
    item_id: str,
    when: datetime,
    *,
    status: str,
    duration: float,
    credits: list[str],
    music_credit: str,
    shots: list[VisualShot],
    pip: bool,
    reason: str,
) -> dict:
    return {
        "id": item_id,
        "status": status,
        "title": str(meta.get("video_title") or item.title)[:100],
        "description": _description(meta, item, credits, music_credit),
        "tags": _tags(meta, settings),
        "story_url": item.link,
        "story_title": item.title,
        "feed_name": item.feed_name,
        "profile": profile.id,
        "voice": profile.edge_voice if settings.tts_engine != "openai" else profile.openai_voice,
        "created_at": when.isoformat(),
        "duration_sec": round(duration, 2),
        "word_count": word_count(script),
        "clips": len(shots),
        "credits": credits,
        "music": music_credit,
        "pip_lead_image": pip,
        "still_runtime_sec": 0,
        "shots": [
            {
                "source": shot.source,
                "query": shot.query,
                "in_point": round(shot.in_point, 3),
                "duration": round(shot.duration, 3),
                "credit": shot.credit,
            }
            for shot in shots
        ],
        "queue_reason": reason,
        "youtube_id": "",
    }


def _render_one(
    settings: Settings,
    project_root: Path,
    queue: ReviewQueue,
    item: NewsItem,
    profile: Profile,
    provider: str,
    index: int,
    when: datetime,
) -> RenderOutcome:
    page = fetch_page(item.link, settings.fetch_timeout_seconds)
    excerpt = excerpt_from_html(page)
    meta = _script(settings, provider, item, profile, excerpt)
    script = str(meta["script"])
    logger.info(
        "Story %d profile=%s words=%d title=%s",
        index,
        profile.id,
        word_count(script),
        str(meta.get("video_title"))[:80],
    )
    item_id = f"{when:%Y%m%d}-{index:02d}-{item.id[:6]}"
    suffix = 2
    while queue.find(item_id):
        item_id = f"{when:%Y%m%d}-{index:02d}-{item.id[:6]}-{suffix}"
        suffix += 1
    folder = queue.prepare(item_id)
    try:
        (folder / "script.txt").write_text(script + "\n", encoding="utf-8")
        voice = folder / "voice.mp3"
        words = render_tts(settings, script, voice, profile)
        voice_seconds = ffprobe_duration(voice)
        if voice_seconds > 75:
            raise RuntimeError(
                f"Voiceover is {voice_seconds:.0f}s, past the 75s ceiling for a Short. "
                "The script is probably padded with page junk."
            )
        queries = meta.get("broll_queries") if isinstance(meta.get("broll_queries"), list) else []
        try:
            shots = assemble_footage(
                settings,
                script=script,
                words=words,
                voice_seconds=voice_seconds,
                story_title=item.title,
                story_id=item_id,
                extra_queries=[str(query) for query in queries],
                when=when,
            )
        except FootageRejected as exc:
            logger.error("Footage rejected for %s: %s", item_id, exc.reason)
            record = _record(
                settings,
                item,
                profile,
                meta,
                script,
                item_id,
                when,
                status="rejected",
                duration=voice_seconds,
                credits=[],
                music_credit="Not mixed. Rejected before a picture was cut.",
                shots=[],
                pip=False,
                reason=exc.reason,
            )
            queue.write_meta(folder, record)
            queue.transition(item_id, "rejected", queue_reason=exc.reason)
            return RenderOutcome(item_id, "rejected", exc.retryable)
        pip = _lead_image(settings, page, folder)
        credits: list[str] = []
        for shot in shots:
            if shot.credit not in credits:
                credits.append(shot.credit)
        if pip is not None:
            credits.append(
                "Source-page lead image, shown once as a small inset over moving footage. "
                "Review it before upload."
            )
        music_path, music_credit = prepare_bed(
            folder / "bed.wav",
            voice_seconds + 0.3,
            profile.music_style,
            profile.bpm,
            int(item.id, 16) % 1_000_000,
            settings.music_dir,
        )
        out = folder / "short.mp4"
        duration = render_short(
            voice=voice,
            words=words,
            music=music_path,
            shots=shots,
            pip=pip,
            hook_text=str(meta.get("hook_text") or item.title),
            payoff_text=str(meta.get("payoff_text") or "Read the source"),
            out_path=out,
            work_dir=folder,
            font=find_font(project_root),
            profile=profile,
            width=settings.video_width,
            height=settings.video_height,
            preset=settings.video_preset,
            crf=settings.video_crf,
        )
        record = _record(
            settings,
            item,
            profile,
            meta,
            script,
            item_id,
            when,
            status="pending",
            duration=duration,
            credits=credits,
            music_credit=music_credit,
            shots=shots,
            pip=pip is not None,
            reason="",
        )
        queue.write_meta(folder, record)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    logger.info("READY for review: %s (%s, %.0fs, %d shots)", out, profile.id, duration, len(shots))
    return RenderOutcome(item_id, "pending", False)


def run(project_root: Path, settings: Settings) -> int:
    project_root = project_root.resolve()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    provider = active_llm_provider(settings)
    if provider == "local":
        logger.warning(
            "No LLM key set. Ranking and scripts use the offline writer. "
            "Add GEMINI_API_KEY, OPENAI_API_KEY, or XAI_API_KEY for tighter, more natural scripts."
        )
    else:
        logger.info("LLM provider: %s", provider)
    log_footage_keys(settings)

    items = _gather(settings, project_root)
    history = StoryHistory(settings.data_dir / "seen.sqlite")
    try:
        fresh = history.filter_fresh(items)
        if not fresh:
            logger.warning("No fresh technology stories to turn into Shorts")
            return 0
        selected = _rank(settings, provider, fresh)
        if not selected:
            logger.warning("Ranking returned no stories")
            return 0
        when = datetime.now(timezone.utc)
        profiles = assign_profiles(len(selected), when.strftime("%Y-%m-%d"))
        queue = ReviewQueue(settings.output_dir / "review")
        made: list[str] = []
        for index, (item, profile) in enumerate(zip(selected, profiles), start=1):
            logger.info("Rendering %d/%d: %s", index, len(selected), item.title[:100])
            try:
                outcome = _render_one(
                    settings,
                    project_root,
                    queue,
                    item,
                    profile,
                    provider,
                    index,
                    when,
                )
            except Exception:
                logger.exception("Failed to render %s", item.title[:100])
                continue
            if outcome.status == "pending" or not outcome.retryable:
                history.mark_used(item, when)
            if outcome.status == "pending":
                made.append(outcome.item_id)
        queue.write_index()
        if not made:
            logger.error(
                "No Short was left pending. Rejections, with reasons, are in %s",
                queue.root / "rejected",
            )
            return 1
        mode = decide_upload(settings.auto_upload, settings.skip_review, settings.dry_run)
        if mode == "upload_without_review":
            logger.warning(
                "SKIP_REVIEW=1 and AUTO_UPLOAD=1. Today's Shorts will upload without a person watching them. "
                "That is the explicit opt-in. YouTube's inauthentic-content policy still applies."
            )
            for item_id in made:
                queue.transition(item_id, "approved")
            return publish_approved(settings, queue)
        if mode == "upload_approved_only":
            logger.info(
                "AUTO_UPLOAD=1 and SKIP_REVIEW is off. Today's %d Short(s) stay pending. "
                "Uploading videos you already approved, up to the daily cap.",
                len(made),
            )
            return publish_approved(settings, queue)
        logger.info(
            "Rendered %d Short(s) into %s. Nothing was uploaded. "
            "Review them, then: python -m news_youtube_bot review approve ID",
            len(made),
            queue.root / "pending",
        )
        return 0
    finally:
        history.close()
