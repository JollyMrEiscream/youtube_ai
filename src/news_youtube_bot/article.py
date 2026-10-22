from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from news_youtube_bot.media import USER_AGENT
from news_youtube_bot.textutil import html_to_text

logger = logging.getLogger(__name__)

_OG_IMAGE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
_OG_IMAGE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.I,
)
_OG_DESC = re.compile(
    r'<meta[^>]+property=["\']og:description["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
_OG_DESC_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
    re.I,
)


def _chrome_bin() -> str | None:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def fetch_page(url: str, timeout: float) -> str:
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text[:500_000]
    except httpx.HTTPError as exc:
        logger.info("Page fetch skipped %s: %s", url, exc)
        return ""


def excerpt_from_html(html: str) -> str:
    if not html:
        return ""
    match = _OG_DESC.search(html) or _OG_DESC_ALT.search(html)
    og = match.group(1).strip() if match else ""
    text = html_to_text(html)
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 70]
    body = " ".join(lines[:8])[:1600]
    if og and og not in body:
        body = f"{og} {body}".strip()
    return body[:1800]


def fetch_excerpt(url: str, timeout: float) -> str:
    return excerpt_from_html(fetch_page(url, timeout))


def og_image_url(html: str) -> str | None:
    match = _OG_IMAGE.search(html) or _OG_IMAGE_ALT.search(html)
    if not match:
        return None
    return match.group(1).strip()


def download_file(url: str, dest: Path, timeout: float, max_bytes: int = 18_000_000) -> bool:
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                dest.parent.mkdir(parents=True, exist_ok=True)
                size = 0
                with dest.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("file too large")
                        handle.write(chunk)
        return dest.is_file() and dest.stat().st_size > 1000
    except Exception as exc:
        logger.info("Download failed %s: %s", url[:120], exc)
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


def capture_page(url: str, dest: Path, timeout: float) -> bool:
    binary = _chrome_bin()
    if not binary:
        logger.info("No Chrome/Chromium binary; skipping page capture")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        binary,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--hide-scrollbars",
        "--disable-dev-shm-usage",
        "--window-size=1080,1920",
        f"--screenshot={dest}",
        url,
    ]
    try:
        subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.info("Page capture timed out for %s", url)
        dest.unlink(missing_ok=True)
        return False
    if dest.is_file() and dest.stat().st_size > 8_000:
        return True
    dest.unlink(missing_ok=True)
    return False
