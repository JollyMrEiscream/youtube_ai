from __future__ import annotations

import logging
import shutil
from pathlib import Path

from news_youtube_bot.captions import build_ass, write_ass
from news_youtube_bot.footage import VisualShot
from news_youtube_bot.media import ffprobe_duration, require_ffmpeg, run_ffmpeg
from news_youtube_bot.tts_render import WordTiming
from news_youtube_bot.variety import Profile

logger = logging.getLogger(__name__)


def cover_filter(width: int, height: int) -> str:
    """Center-crop to the frame. No zoom, no pan: the motion has to be in the clip."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2,fps=30,setsar=1,format=yuv420p"
    )


def _concat(paths: list[Path], dest: Path, work: Path) -> None:
    listing = work / "concat.txt"
    lines = []
    for path in paths:
        escaped = str(path.resolve()).replace("'", r"'\''")
        lines.append(f"file '{escaped}'")
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        run_ffmpeg(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(dest)]
        )
    except RuntimeError:
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
                str(dest),
            ]
        )


def _mux(
    visual: Path,
    voice: Path,
    music: Path,
    ass: Path,
    font_dir: Path,
    out: Path,
    preset: str,
    crf: int,
    duration: float,
    *,
    duck: bool,
) -> None:
    fade = max(0.2, duration - 0.65)
    ass_arg = str(ass.resolve()).replace("\\", "/").replace(":", "\\:")
    font_arg = str(font_dir.resolve()).replace("\\", "/").replace(":", "\\:")
    if duck:
        audio = (
            "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            "dynaudnorm=f=150:g=12,asplit=2[vo][sc];"
            "[2:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=0.18,"
            f"afade=t=in:st=0:d=0.25,afade=t=out:st={fade:.3f}:d=0.5[mu];"
            "[mu][sc]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=280:makeup=1.4:knee=2[bg];"
            "[vo][bg]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        audio = (
            "[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,dynaudnorm=f=150:g=12[vo];"
            "[2:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=0.10,"
            f"afade=t=in:st=0:d=0.25,afade=t=out:st={fade:.3f}:d=0.5[mu];"
            "[vo][mu]amix=inputs=2:duration=first:normalize=0[a]"
        )
    graph = f"[0:v]ass={ass_arg}:fontsdir={font_arg}[v];{audio}"
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(visual),
            "-i",
            str(voice),
            "-i",
            str(music),
            "-filter_complex",
            graph,
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-shortest",
            str(out),
        ]
    )


def _render_shot(
    out: Path,
    shot: VisualShot,
    width: int,
    height: int,
    pip: Path | None,
) -> None:
    vf = cover_filter(width, height)
    duration = f"{shot.duration:.3f}"
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{max(0.0, shot.in_point):.3f}",
        "-i",
        str(shot.path),
    ]
    if pip is not None:
        show = min(2.2, shot.duration)
        graph = (
            f"[0:v]{vf}[base];"
            "[1:v]scale=420:-1,format=rgba[inset];"
            f"[base][inset]overlay=x=56:y=280:enable='between(t,0,{show:.2f})'[v]"
        )
        cmd.extend(
            [
                "-loop",
                "1",
                "-i",
                str(pip),
                "-filter_complex",
                graph,
                "-map",
                "[v]",
            ]
        )
    else:
        cmd.extend(["-vf", vf])
    cmd.extend(
        [
            "-t",
            duration,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            str(out),
        ]
    )
    run_ffmpeg(cmd)


def render_short(
    *,
    voice: Path,
    words: list[WordTiming],
    music: Path,
    shots: list[VisualShot],
    out_path: Path,
    work_dir: Path,
    font: Path,
    profile: Profile,
    width: int,
    height: int,
    preset: str,
    crf: int,
    pip: Path | None = None,
    hook_text: str = "",
    payoff_text: str = "",
) -> float:
    """Hard-cut real video under the voice. Stills are not a shot."""
    del payoff_text  # the spoken close and the burned-in captions carry the payoff
    require_ffmpeg()
    if not shots:
        raise RuntimeError("No moving footage to cut. Refusing to render a slideshow.")
    duration = ffprobe_duration(voice)
    if duration < 12:
        logger.warning("Voiceover is only %.1fs. The short will be short; the script may be thin.", duration)
    elif duration > 68:
        logger.warning("Voiceover is %.1fs, longer than the 30-60s target.", duration)

    build = work_dir / "build"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True, exist_ok=True)

    pip_at = len(shots) // 2 if pip is not None else -1
    rendered: list[Path] = []
    for index, shot in enumerate(shots):
        target = build / f"seg_{index:02d}.mp4"
        try:
            _render_shot(target, shot, width, height, pip if index == pip_at else None)
        except RuntimeError:
            if pip is not None and index == pip_at:
                logger.warning("Lead-image inset failed; cutting the shot without it")
                _render_shot(target, shot, width, height, None)
            else:
                raise
        rendered.append(target)

    visual = build / "visual.mp4"
    _concat(rendered, visual, build)
    ass_path = work_dir / "captions.ass"
    hook_seconds = min(2.2, shots[0].duration)
    write_ass(
        ass_path,
        build_ass(
            words,
            profile,
            font,
            hook_text,
            width=width,
            height=height,
            caption_start=min(1.25, max(0.4, hook_seconds - 0.3)),
            hook_seconds=hook_seconds,
        ),
    )
    try:
        _mux(visual, voice, music, ass_path, font.parent, out_path, preset, crf, duration, duck=True)
    except RuntimeError:
        logger.warning("Sidechain duck failed; mixing music at a lower level")
        _mux(visual, voice, music, ass_path, font.parent, out_path, preset, crf, duration, duck=False)
    shutil.rmtree(build, ignore_errors=True)
    return ffprobe_duration(out_path)
