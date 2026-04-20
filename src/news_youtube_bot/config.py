from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


def _truthy(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _resolve_llm_provider() -> str:
    explicit = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if explicit in ("openai", "gemini"):
        return explicit
    gemini = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    openai = os.environ.get("OPENAI_API_KEY")
    if gemini and not openai:
        return "gemini"
    return "openai"


@dataclass
class Settings:
    feeds_file: Path
    news_window_minutes: int
    max_stories: int
    llm_provider: str  # openai | gemini
    gemini_api_key: str | None
    gemini_model: str
    openai_api_key: str | None
    openai_model: str
    tts_engine: str  # openai | edge
    tts_voice: str
    video_width: int
    video_height: int
    dry_run: bool
    output_dir: Path
    youtube_privacy: str
    google_client_id: str | None
    google_client_secret: str | None
    youtube_refresh_token: str | None
    youtube_category_id: str
    default_tags: list[str]
    fetch_timeout_seconds: float
    rss_feed_urls: list[str] | None

    @classmethod
    def load(cls, project_root: Path | None = None) -> Settings:
        root = project_root or Path.cwd()
        feeds_path = Path(os.environ.get("FEEDS_FILE", str(root / "config" / "feeds.yaml")))
        raw_urls = os.environ.get("RSS_FEED_URLS")
        rss_list: list[str] | None = None
        if raw_urls and raw_urls.strip():
            rss_list = [u.strip() for u in raw_urls.splitlines() if u.strip()]

        tags_raw = os.environ.get("YOUTUBE_TAGS", "news,summary,ai")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        return cls(
            feeds_file=feeds_path,
            news_window_minutes=int(os.environ.get("NEWS_WINDOW_MINUTES", "90")),
            max_stories=int(os.environ.get("MAX_STORIES", "5")),
            llm_provider=_resolve_llm_provider(),
            gemini_api_key=os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"),
            gemini_model=os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"),
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            tts_engine=os.environ.get("TTS_ENGINE", "openai").strip().lower(),
            tts_voice=os.environ.get("TTS_VOICE", "alloy"),
            video_width=int(os.environ.get("VIDEO_WIDTH", "1920")),
            video_height=int(os.environ.get("VIDEO_HEIGHT", "1080")),
            dry_run=_truthy("DRY_RUN", False),
            output_dir=Path(os.environ.get("OUTPUT_DIR", str(root / "output"))),
            youtube_privacy=os.environ.get("YOUTUBE_PRIVACY", "private").strip().lower(),
            google_client_id=os.environ.get("GOOGLE_CLIENT_ID"),
            google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
            youtube_refresh_token=os.environ.get("YOUTUBE_REFRESH_TOKEN"),
            youtube_category_id=os.environ.get("YOUTUBE_CATEGORY_ID", "25"),  # News & Politics
            default_tags=tags,
            fetch_timeout_seconds=float(os.environ.get("FETCH_TIMEOUT_SECONDS", "20")),
            rss_feed_urls=rss_list,
        )


def load_feed_urls(settings: Settings, project_root: Path | None = None) -> list[tuple[str, str | None]]:
    """Return list of (url, optional name)."""
    if settings.rss_feed_urls:
        return [(u, None) for u in settings.rss_feed_urls]

    path = settings.feeds_file
    if not path.is_file():
        example = (project_root or Path.cwd()) / "config" / "feeds.example.yaml"
        if example.is_file():
            path = example
        else:
            return []

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    feeds = data.get("feeds") or []
    out: list[tuple[str, str | None]] = []
    for entry in feeds:
        if isinstance(entry, str):
            out.append((entry, None))
        elif isinstance(entry, dict) and entry.get("url"):
            out.append((str(entry["url"]), entry.get("name")))
    return out
