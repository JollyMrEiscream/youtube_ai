from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs without overriding variables already in the environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_str(name: str, default: str) -> str:
    """GitHub Actions often injects `VAR=` (empty) when a repo var is unset; treat as missing."""
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    return str(v).strip()


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    return int(str(v).strip(), 10)


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    return float(str(v).strip())


def _opt_str(name: str) -> str | None:
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return None
    return str(v).strip()


def _first_opt_str(*names: str) -> str | None:
    for name in names:
        found = _opt_str(name)
        if found is not None:
            return found
    return None


def _truthy(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _resolve_llm_provider() -> str:
    explicit = _env_str("LLM_PROVIDER", "").lower()
    if explicit in ("openai", "gemini", "local"):
        return explicit
    gemini = _first_opt_str("GEMINI_API_KEY", "GOOGLE_API_KEY")
    openai = _opt_str("OPENAI_API_KEY")
    if gemini and not openai:
        return "gemini"
    if openai:
        return "openai"
    return "local"


def _daily_count() -> int:
    if _opt_str("DAILY_SHORTS") is not None:
        return _env_int("DAILY_SHORTS", 5)
    # Older installs used MAX_STORIES as the batch size for one digest video.
    if _opt_str("MAX_STORIES") is not None:
        return _env_int("MAX_STORIES", 5)
    return 5


@dataclass
class Settings:
    feeds_file: Path
    news_window_minutes: int
    daily_shorts: int
    llm_provider: str  # openai | gemini | local
    gemini_api_key: str | None
    gemini_model: str
    openai_api_key: str | None
    openai_model: str
    tts_engine: str  # openai | edge
    tts_voice: str
    tts_voice_explicit: bool
    tts_model: str
    tts_rate: str | None
    video_width: int
    video_height: int
    video_preset: str
    video_crf: int
    dry_run: bool
    output_dir: Path
    data_dir: Path
    youtube_privacy: str
    google_client_id: str | None
    google_client_secret: str | None
    youtube_refresh_token: str | None
    youtube_category_id: str
    default_tags: list[str]
    fetch_timeout_seconds: float
    rss_feed_urls: list[str] | None
    pexels_api_key: str | None
    pixabay_api_key: str | None
    news_api_key: str | None
    auto_upload: bool
    skip_review: bool
    max_uploads_per_day: int
    upload_quota_cost: int
    youtube_daily_quota_units: int
    capture_sources: bool
    music_dir: Path | None

    @classmethod
    def load(cls, project_root: Path | None = None) -> Settings:
        root = project_root or Path.cwd()
        load_dotenv(root / ".env")
        feeds_path = Path(_env_str("FEEDS_FILE", str(root / "config" / "feeds.yaml")))
        raw_urls = os.environ.get("RSS_FEED_URLS")
        rss_list: list[str] | None = None
        if raw_urls and raw_urls.strip():
            rss_list = [u.strip() for u in raw_urls.splitlines() if u.strip()]

        tags_raw = _env_str("YOUTUBE_TAGS", "tech,technology,shorts,news")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        music_raw = _opt_str("MUSIC_DIR")
        music_dir = Path(music_raw) if music_raw else (root / "assets" / "music")

        return cls(
            feeds_file=feeds_path,
            news_window_minutes=_env_int("NEWS_WINDOW_MINUTES", 36 * 60),
            daily_shorts=max(1, _daily_count()),
            llm_provider=_resolve_llm_provider(),
            gemini_api_key=_first_opt_str("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            gemini_model=_env_str("GEMINI_MODEL", "gemini-2.5-flash"),
            openai_api_key=_opt_str("OPENAI_API_KEY"),
            openai_model=_env_str("OPENAI_MODEL", "gpt-4o-mini"),
            tts_engine=_env_str("TTS_ENGINE", "edge").lower(),
            tts_voice=_env_str("TTS_VOICE", ""),
            tts_voice_explicit=_opt_str("TTS_VOICE") is not None,
            tts_model=_env_str("TTS_MODEL", "tts-1-hd"),
            tts_rate=_opt_str("TTS_RATE"),
            video_width=_env_int("VIDEO_WIDTH", 1080),
            video_height=_env_int("VIDEO_HEIGHT", 1920),
            video_preset=_env_str("VIDEO_PRESET", "medium"),
            video_crf=_env_int("VIDEO_CRF", 20),
            dry_run=_truthy("DRY_RUN", False),
            output_dir=Path(_env_str("OUTPUT_DIR", str(root / "output"))),
            data_dir=Path(_env_str("DATA_DIR", str(root / "data"))),
            youtube_privacy=_env_str("YOUTUBE_PRIVACY", "private").lower(),
            google_client_id=_opt_str("GOOGLE_CLIENT_ID"),
            google_client_secret=_opt_str("GOOGLE_CLIENT_SECRET"),
            youtube_refresh_token=_opt_str("YOUTUBE_REFRESH_TOKEN"),
            youtube_category_id=_env_str("YOUTUBE_CATEGORY_ID", "28"),  # Science & Technology
            default_tags=tags,
            fetch_timeout_seconds=_env_float("FETCH_TIMEOUT_SECONDS", 20.0),
            rss_feed_urls=rss_list,
            pexels_api_key=_opt_str("PEXELS_API_KEY"),
            pixabay_api_key=_opt_str("PIXABAY_API_KEY"),
            news_api_key=_first_opt_str("NEWS_API_KEY", "NEWSAPI_KEY"),
            auto_upload=_truthy("AUTO_UPLOAD", False),
            skip_review=_truthy("SKIP_REVIEW", False),
            max_uploads_per_day=_env_int("MAX_UPLOADS_PER_DAY", 6),
            upload_quota_cost=_env_int("UPLOAD_QUOTA_COST", 1600),
            youtube_daily_quota_units=_env_int("YOUTUBE_DAILY_QUOTA_UNITS", 10000),
            capture_sources=_truthy("CAPTURE_SOURCES", True),
            music_dir=music_dir,
        )


def active_llm_provider(settings: Settings) -> str:
    """Fall back when the configured provider has no key, so a run still renders."""
    provider = settings.llm_provider
    if provider == "gemini" and settings.gemini_api_key:
        return "gemini"
    if provider == "openai" and settings.openai_api_key:
        return "openai"
    if provider == "local":
        return "local"
    if settings.gemini_api_key:
        return "gemini"
    if settings.openai_api_key:
        return "openai"
    return "local"


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
