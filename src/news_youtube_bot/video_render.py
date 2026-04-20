from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

from news_youtube_bot.config import Settings

logger = logging.getLogger(__name__)

OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
OG_IMAGE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.I,
)


def ffprobe_duration_seconds(audio_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return max(float(out), 0.1)


def fetch_og_image_url(link: str, timeout: float) -> str | None:
    try:
        with httpx.Client(follow_redirects=True, headers={"User-Agent": "news-youtube-bot/0.1"}) as c:
            r = c.get(link, timeout=timeout)
            r.raise_for_status()
            html = r.text[:500_000]
    except httpx.HTTPError as e:
        logger.debug("og:image fetch skip %s: %s", link, e)
        return None
    m = OG_IMAGE_RE.search(html) or OG_IMAGE_RE_ALT.search(html)
    if not m:
        return None
    return m.group(1).strip()


def download_background_image(image_url: str, dest: Path, timeout: float, max_bytes: int = 3_000_000) -> bool:
    try:
        with httpx.Client(follow_redirects=True, headers={"User-Agent": "news-youtube-bot/0.1"}) as c:
            with c.stream("GET", image_url, timeout=timeout) as r:
                r.raise_for_status()
                size = 0
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as f:
                    for chunk in r.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("image too large")
                        f.write(chunk)
        return True
    except Exception as e:
        logger.info("Background image download failed: %s", e)
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


def build_video(
    settings: Settings,
    audio_path: Path,
    video_title: str,
    source_link: str | None,
    out_path: Path,
) -> None:
    w, h = settings.video_width, settings.video_height
    duration = ffprobe_duration_seconds(audio_path)
    fps = 30
    d_frames = max(int(duration * fps) + int(fps), 1)

    bg: Path | None = None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    title_file = out_path.parent / "overlay_title.txt"
    title_file.write_text(video_title[:500], encoding="utf-8")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        if source_link:
            og = fetch_og_image_url(source_link, settings.fetch_timeout_seconds)
            if og:
                cand = td_path / "bg.jpg"
                if download_background_image(og, cand, settings.fetch_timeout_seconds):
                    bg = cand

        # Ken Burns zoom on image or solid generated via lavfi
        zoompan = (
            f"zoompan=z='min(zoom+0.0012,1.35)':d={d_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={w}x{h}:fps={fps}"
        )
        draw = (
            f"drawtext=fontcolor=white:fontsize={48 if h >= 1080 else 32}:"
            "x=(w-text_w)/2:y=60:textfile=overlay_title.txt:"
            "line_spacing=8:box=1:boxcolor=black@0.45:boxborderw=16"
        )
        if bg and bg.exists():
            vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},{zoompan},{draw}"
        else:
            vf = f"{zoompan},{draw}"

        workdir = str(out_path.parent.resolve())
        audio_rel = audio_path.name if audio_path.parent.resolve() == out_path.parent.resolve() else str(audio_path)
        out_rel = out_path.name

        if bg and bg.exists():
            cmd = [
                "ffmpeg",
                "-y",
                "-loop",
                "1",
                "-i",
                str(bg),
                "-i",
                audio_rel,
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                out_rel,
            ]
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x0f3460:s={w}x{h}:r={fps}",
                "-i",
                audio_rel,
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-pix_fmt",
                "yuv420p",
                "-shortest",
                out_rel,
            ]

        logger.info("Running ffmpeg -> %s", out_path.name)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=workdir)
        except subprocess.CalledProcessError as e:
            logger.error("ffmpeg failed: %s", e.stderr)
            raise
