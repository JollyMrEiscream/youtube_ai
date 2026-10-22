from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from news_youtube_bot.article import download_file
from news_youtube_bot.config import Settings
from news_youtube_bot.media import USER_AGENT, has_video_stream
from news_youtube_bot.models import NewsItem

logger = logging.getLogger(__name__)

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "your", "into", "about", "after",
    "before", "over", "under", "what", "when", "where", "why", "how", "are", "was", "were",
    "will", "just", "than", "then", "them", "they", "have", "has", "had", "its", "it's",
    "new", "says", "say", "said", "can", "could", "would", "should", "not", "but", "you",
    "all", "any", "our", "out", "his", "her", "who", "a", "an", "of", "to", "in", "on",
    "at", "by", "or", "as", "is", "it", "be", "we", "their", "more", "most", "into",
    "using", "use", "used", "via", "per", "amid", "after", "gets", "get", "got",
}

_GENERIC = (
    "laptop typing",
    "computer keyboard",
    "smartphone",
    "typing on a keyboard",
    "server room",
    "software code monitor",
    "robot arm",
    "city traffic night",
    "data center",
    "engineer computer",
    "satellite dish",
    "newsroom",
)

_NONFREE = ("non-free", "fair use", "all rights reserved", "copyrighted")
_BLOCK_TITLE = re.compile(
    r"protest|police|riot|weapon|gunshot|nude|porn|\bsex\b|uranium|bomb|shooting|war crime|assault",
    re.I,
)


def _title_matches_query(title: str, query: str) -> bool:
    """Keep a clip only when its title actually depicts the search, not a coincidental noun."""
    if _BLOCK_TITLE.search(title or ""):
        return False
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z]{4,}", query or "")
        if token.lower() not in _STOP and token.lower() not in {"filetype", "video"}
    ]
    hay = (title or "").lower().replace("_", " ")
    if not tokens:
        return True
    strong = [token for token in tokens if len(token) >= 5]
    wanted = strong or tokens
    return any(token in hay for token in wanted)


@dataclass
class Clip:
    path: Path
    credit: str
    source: str


def search_queries(title: str, salt: int, extra: list[str] | None = None) -> list[str]:
    words = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z0-9+-]{2,}", title or "")
        if word.lower() not in _STOP
    ]
    specific = " ".join(words[:3]) if words else "technology"
    queries = []
    if extra:
        queries.extend(q.strip() for q in extra if q and q.strip())
    queries.append(specific)
    for offset in (0, 3, 7):
        queries.append(_GENERIC[(salt + offset) % len(_GENERIC)])
    # Preserve order, drop dupes.
    seen: set[str] = set()
    out: list[str] = []
    for query in queries:
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(query)
    return out[:5]


def _cache_path(cache: Path, url: str, suffix: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return cache / f"{digest}{suffix}"


def _suffix_from_url(url: str, default: str = ".mp4") -> str:
    path = urlparse(url).path.lower()
    for ext in (".mp4", ".webm", ".mov", ".ogv", ".mkv", ".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(ext):
            return ext
    return default


def _keep_video(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 20_000:
        return False
    if not has_video_stream(path):
        path.unlink(missing_ok=True)
        return False
    return True


def _pexels(query: str, key: str, timeout: float) -> list[tuple[str, str]]:
    headers = {"Authorization": key, "User-Agent": USER_AGENT}
    found: list[tuple[str, str]] = []
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        for params in (
            {"query": query, "orientation": "portrait", "per_page": 6, "size": "small"},
            {"query": query, "per_page": 6, "size": "small"},
        ):
            try:
                response = client.get("https://api.pexels.com/videos/search", params=params)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.info("Pexels search failed: %s", exc)
                continue
            for video in payload.get("videos") or []:
                files = [
                    item
                    for item in (video.get("video_files") or [])
                    if item.get("link") and "mp4" in str(item.get("file_type") or "video/mp4")
                ]
                if not files:
                    continue
                files.sort(key=lambda item: (abs(int(item.get("height") or 0) - 1280), int(item.get("width") or 0)))
                chosen = files[0]
                user = ((video.get("user") or {}).get("name")) or "a Pexels contributor"
                page = video.get("url") or "https://www.pexels.com"
                credit = f"Clip by {user} on Pexels ({page})"
                found.append((str(chosen["link"]), credit))
            if found:
                break
    return found


def _pixabay(query: str, key: str, timeout: float) -> list[tuple[str, str]]:
    params = {
        "key": key,
        "q": query.replace(" ", "+"),
        "video_type": "film",
        "safesearch": "true",
        "per_page": 6,
    }
    try:
        response = httpx.get(
            "https://pixabay.com/api/videos/",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Pixabay search failed: %s", exc)
        return []
    found: list[tuple[str, str]] = []
    for hit in payload.get("hits") or []:
        videos = hit.get("videos") or {}
        rendition = videos.get("medium") or videos.get("small") or videos.get("tiny") or {}
        link = rendition.get("url")
        if not link:
            continue
        user = hit.get("user") or "a Pixabay contributor"
        page = hit.get("pageURL") or "https://pixabay.com"
        found.append((str(link), f"Clip by {user} on Pixabay ({page})"))
    return found


def _license_ok(info: dict) -> bool:
    meta = info.get("extmetadata") or {}
    raw = ((meta.get("LicenseShortName") or {}).get("value") or "").lower()
    if not raw:
        return True
    return not any(flag in raw for flag in _NONFREE)


def _wikimedia(query: str, timeout: float) -> list[tuple[str, str]]:
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"{query} filetype:video",
        "gsrnamespace": 6,
        "gsrlimit": 15,
        "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata",
    }
    try:
        response = httpx.get(
            "https://commons.wikimedia.org/w/api.php",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Wikimedia search failed: %s", exc)
        return []
    pages = ((payload.get("query") or {}).get("pages") or {}).values()
    ranked: list[tuple[int, str, str]] = []
    for page in pages:
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        title = page.get("title") or ""
        if not _title_matches_query(title, query):
            continue
        info = infos[0]
        if not _license_ok(info):
            continue
        mime = str(info.get("mime") or "")
        if not mime.startswith("video/"):
            continue
        size = int(info.get("size") or 0)
        duration = float(info.get("duration") or 0)
        if size <= 0 or size > 18_000_000:
            continue
        if duration > 45:
            continue
        url = info.get("url")
        if not url:
            continue
        score = 0
        if 3 <= duration <= 25:
            score += 3
        if size < 8_000_000:
            score += 2
        width = int(info.get("width") or 0)
        height = int(info.get("height") or 0)
        if height > width:
            score += 2
        title = title or "Wikimedia Commons file"
        meta = info.get("extmetadata") or {}
        license_name = ((meta.get("LicenseShortName") or {}).get("value")) or "see file page"
        desc = info.get("descriptionurl") or ""
        credit = f"{title} via Wikimedia Commons ({license_name}). {desc}".strip()
        ranked.append((score, str(url), credit))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [(url, credit) for _score, url, credit in ranked]


def collect_clips(
    settings: Settings,
    item: NewsItem,
    queries: list[str],
    used_urls: set[str],
    limit: int = 3,
) -> list[Clip]:
    cache = settings.data_dir / "cache" / "clips"
    cache.mkdir(parents=True, exist_ok=True)
    salt = sum(ord(char) for char in item.id)
    wanted = search_queries(item.title, salt, queries)
    clips: list[Clip] = []
    seen_urls: set[str] = set()
    for query in wanted:
        if len(clips) >= limit:
            break
        found: list[tuple[str, str, str]] = []
        if settings.pexels_api_key:
            found.extend((url, credit, "pexels") for url, credit in _pexels(query, settings.pexels_api_key, settings.fetch_timeout_seconds))
        if settings.pixabay_api_key:
            found.extend((url, credit, "pixabay") for url, credit in _pixabay(query, settings.pixabay_api_key, settings.fetch_timeout_seconds))
        found.extend((url, credit, "wikimedia") for url, credit in _wikimedia(query, settings.fetch_timeout_seconds))
        for url, credit, source in found:
            if len(clips) >= limit or url in used_urls or url in seen_urls:
                continue
            seen_urls.add(url)
            dest = _cache_path(cache, url, _suffix_from_url(url))
            if not dest.is_file() and not download_file(url, dest, settings.fetch_timeout_seconds):
                continue
            if not _keep_video(dest):
                continue
            used_urls.add(url)
            clips.append(Clip(path=dest, credit=credit, source=source))
    logger.info(
        "Footage for %s: %d clip(s) from %s",
        item.id,
        len(clips),
        ", ".join(sorted({clip.source for clip in clips})) or "none",
    )
    return clips
