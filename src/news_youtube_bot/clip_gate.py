from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# A 9:16 crop has to stay at least 720px on its short side, or the Short is upscaled mush.
MIN_CROP_EDGE = 720
MIN_DURATION = 1.5
MAX_STILL_SHARE = 0.15

_WATERMARK = re.compile(
    r"watermark|shutterstock|gettyimages?|pond5|\bistock\b|preview\s*only|stock\s*photo",
    re.I,
)
_BLOCK = re.compile(
    r"protest|police|riot|weapon|gunshot|nude|porn|\bsex\b|uranium|bomb|shooting|war crime|assault",
    re.I,
)
_SCENE_SCORE = re.compile(r"lavfi\.scene_score=([0-9.]+)")
_PTS_TIME = re.compile(r"pts_time:([0-9.]+)")
_PSNR = re.compile(r"average:([0-9.]+|inf)")
_YDIF = re.compile(r"lavfi\.signalstats\.YDIF=([0-9.]+)")


def crop_short_side(width: int, height: int) -> int:
    """Short side, in pixels, after a center crop to 9:16. No upscaling."""
    if width <= 0 or height <= 0:
        return 0
    if width / height > 9 / 16:
        return int(min(width, height * 9 / 16))
    return int(min(width, height))


def still_share(still_seconds: float, total_seconds: float) -> float:
    if total_seconds <= 0:
        return 1.0
    return max(0.0, still_seconds) / total_seconds


def gate_source(
    *,
    width: int,
    height: int,
    duration: float,
    title: str = "",
    url: str = "",
    tags: str = "",
) -> tuple[bool, str]:
    """Metadata gate. Runs before a file is downloaded."""
    blob = " ".join(part for part in (title, url, tags) if part)
    if _WATERMARK.search(blob):
        return False, "watermark or stock-preview marker in the title or URL"
    if _BLOCK.search(blob):
        return False, "title or tags are off-limits for this channel"
    if duration < MIN_DURATION:
        return False, f"clip is {duration:.1f}s, under {MIN_DURATION:.1f}s"
    edge = crop_short_side(width, height)
    if edge < MIN_CROP_EDGE:
        return False, f"9:16 crop would be {edge}px on the short side, under {MIN_CROP_EDGE}"
    return True, ""


def static_corners_look_like_watermark(flags: list[bool], center_moves: bool) -> bool:
    """A watermark sits in one corner and stays put while the shot moves.

    A locked-off scene has static texture in every corner, so that does not count.
    """
    if not center_moves:
        return False
    marked = sum(1 for flag in flags if flag)
    return 0 < marked <= 2


def corner_is_static_detail(psnr: float, detail: float) -> bool:
    return psnr >= 36 and detail >= 14


def parse_scene_scores(metadata: str) -> list[tuple[float, float]]:
    """Parse ffmpeg `metadata=print` lines into (pts_time, scene_score)."""
    found: list[tuple[float, float]] = []
    pending: float | None = None
    for line in metadata.splitlines():
        pts = _PTS_TIME.search(line)
        if pts:
            pending = float(pts.group(1))
        score = _SCENE_SCORE.search(line)
        if score and pending is not None:
            found.append((pending, float(score.group(1))))
            pending = None
    return found


def choose_window(duration: float, want: float, scenes: list[tuple[float, float]]) -> tuple[float, float]:
    """Pick the strongest 1.5–3s window. `want` is the beat length."""
    if duration <= 0:
        return 0.0, 0.0
    length = min(max(want, MIN_DURATION), 3.0, duration)
    if duration <= length + 0.05:
        return 0.0, duration
    if scenes:
        pts, _score = max(scenes, key=lambda item: item[1])
        start = pts - 0.15
    else:
        start = min(0.45, duration * 0.12)
    start = max(0.0, min(start, duration - length))
    return start, length


def _psnr(left: Path, right: Path, crop: str) -> float | None:
    cmd = [
        "ffmpeg",
        "-v",
        "info",
        "-i",
        str(left),
        "-i",
        str(right),
        "-lavfi",
        f"[0:v]crop={crop}[a];[1:v]crop={crop}[b];[a][b]psnr",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    text = (result.stderr or "") + (result.stdout or "")
    match = _PSNR.search(text)
    if not match:
        return None
    if match.group(1) == "inf":
        return 100.0
    return float(match.group(1))


def _ydif(frame: Path, crop: str) -> float | None:
    cmd = [
        "ffmpeg",
        "-v",
        "info",
        "-i",
        str(frame),
        "-vf",
        f"crop={crop},signalstats,metadata=print",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    match = _YDIF.search((result.stderr or "") + (result.stdout or ""))
    if not match:
        return None
    return float(match.group(1))


def _frame_at(source: Path, dest: Path, seconds: float) -> bool:
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-ss",
        f"{seconds:.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        str(dest),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, OSError):
        return False
    return dest.is_file() and dest.stat().st_size > 0


def file_watermark_heuristic(path: Path, duration: float) -> tuple[bool, str]:
    """Best-effort watermark check. A probe failure does not reject the clip."""
    if shutil.which("ffmpeg") is None or duration < MIN_DURATION:
        return True, ""
    t1 = max(0.1, duration * 0.3)
    t2 = min(duration - 0.1, duration * 0.7)
    if t2 <= t1:
        return True, ""
    crops = (
        "iw*0.18:ih*0.10:0:0",
        "iw*0.18:ih*0.10:iw*0.82:0",
        "iw*0.18:ih*0.10:0:ih*0.90",
        "iw*0.18:ih*0.10:iw*0.82:ih*0.90",
    )
    center = "iw*0.4:ih*0.4:iw*0.3:ih*0.3"
    with tempfile.TemporaryDirectory(prefix="clipgate-") as tmp:
        root = Path(tmp)
        first = root / "a.png"
        second = root / "b.png"
        if not _frame_at(path, first, t1) or not _frame_at(path, second, t2):
            return True, ""
        center_psnr = _psnr(first, second, center)
        if center_psnr is None:
            return True, ""
        flags: list[bool] = []
        for crop in crops:
            psnr = _psnr(first, second, crop)
            detail = _ydif(first, crop)
            if psnr is None or detail is None:
                flags.append(False)
                continue
            flags.append(corner_is_static_detail(psnr, detail))
    if static_corners_look_like_watermark(flags, center_moves=center_psnr <= 30):
        return False, "a corner stays sharp while the shot moves, which usually means a watermark or burned-in bug"
    return True, ""


def gate_file(path: Path, *, source: str) -> tuple[bool, str]:
    """Resolution, duration, aspect, and a watermark heuristic on a downloaded file."""
    from news_youtube_bot.media import ffprobe_video

    probed = ffprobe_video(path)
    if probed is None:
        return False, "ffprobe found no video stream"
    width, height, duration = probed
    ok, reason = gate_source(width=width, height=height, duration=duration, title=path.name, url=str(path))
    if not ok:
        return ok, reason
    if source == "grok":
        # A failed generation is often a near-blank frame. Stock can be a dark room on purpose.
        detail = _ydif_whole(path)
        if detail is not None and detail < 1.2:
            return False, "generated clip looks blank or nearly a single color"
    return file_watermark_heuristic(path, duration)


def _ydif_whole(path: Path) -> float | None:
    cmd = [
        "ffmpeg",
        "-v",
        "info",
        "-ss",
        "0.4",
        "-i",
        str(path),
        "-frames:v",
        "1",
        "-vf",
        "signalstats,metadata=print",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    except OSError:
        return None
    match = _YDIF.search((result.stderr or "") + (result.stdout or ""))
    if not match:
        return None
    return float(match.group(1))
