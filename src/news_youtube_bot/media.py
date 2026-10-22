from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Wikimedia rejects clients whose User-Agent has no URL. See https://w.wiki/4wJS
USER_AGENT = (
    "NewsYouTubeBot/0.2 (+https://www.mediawiki.org/wiki/API:Etiquette; technology-shorts) "
    "python-httpx"
)


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe are required on PATH")


def run_ffmpeg(cmd: list[str], *, cwd: Path | None = None) -> None:
    logger.debug("ffmpeg: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    except subprocess.CalledProcessError as exc:
        tail = (exc.stderr or "")[-2000:]
        logger.error("ffmpeg failed: %s", tail)
        raise RuntimeError(tail) from exc


def ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return max(float(out), 0.1)


def has_video_stream(path: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, text=True).strip()
    except subprocess.CalledProcessError:
        return False
    return out.startswith("video")


def find_font(project_root: Path) -> Path:
    candidates = [
        project_root / "assets" / "fonts" / "Montserrat-Bold.ttf",
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("No bold TTF font found. Install fonts-liberation.")


def ass_font_name(font_path: Path) -> str:
    name = font_path.name.lower()
    if "montserrat" in name:
        return "Montserrat"
    if "dejavu" in name:
        return "DejaVu Sans"
    return "Liberation Sans"
