from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


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
    for n in names:
        s = _opt_str(n)
        if s is not None:
            return s
    return None


def _truthy(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or not str(v).strip():
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _resolve_llm_provider() -> str:
    explicit = _env_str("LLM_PROVIDER", "").lower()
    if explicit in ("openai", "gemini"):
        return explicit
    gemini = _first_opt_str("GEMINI_API_KEY", "GOOGLE_API_KEY")
    openai = _opt_str("OPENAI_API_KEY")
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
        feeds_path = Path(_env_str("FEEDS_FILE", str(root / "config" / "feeds.yaml")))
        raw_urls = os.environ.get("RSS_FEED_URLS")
        rss_list: list[str] | None = None
        if raw_urls and raw_urls.strip():
            rss_list = [u.strip() for u in raw_urls.splitlines() if u.strip()]

        tags_raw = _env_str("YOUTUBE_TAGS", "news,summary,ai")
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        out_dir = Path(_env_str("OUTPUT_DIR", str(root / "output")))

        return cls(
            feeds_file=feeds_path,
            news_window_minutes=_env_int("NEWS_WINDOW_MINUTES", 90),
            max_stories=_env_int("MAX_STORIES", 5),
            llm_provider=_resolve_llm_provider(),
            gemini_api_key=_first_opt_str("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            gemini_model=_env_str("GEMINI_MODEL", "gemini-1.5-flash"),
            openai_api_key=_opt_str("OPENAI_API_KEY"),
            openai_model=_env_str("OPENAI_MODEL", "gpt-4o-mini"),
            tts_engine=_env_str("TTS_ENGINE", "openai").lower(),
            tts_voice=_env_str("TTS_VOICE", "alloy"),
            video_width=_env_int("VIDEO_WIDTH", 1920),
            video_height=_env_int("VIDEO_HEIGHT", 1080),
            dry_run=_truthy("DRY_RUN", False),
            output_dir=out_dir,
            youtube_privacy=_env_str("YOUTUBE_PRIVACY", "private").lower(),
            google_client_id=_opt_str("GOOGLE_CLIENT_ID"),
            google_client_secret=_opt_str("GOOGLE_CLIENT_SECRET"),
            youtube_refresh_token=_opt_str("YOUTUBE_REFRESH_TOKEN"),
            youtube_category_id=_env_str("YOUTUBE_CATEGORY_ID", "25"),  # News & Politics
            default_tags=tags,
            fetch_timeout_seconds=_env_float("FETCH_TIMEOUT_SECONDS", 20.0),
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
