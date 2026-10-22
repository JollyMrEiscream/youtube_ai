from __future__ import annotations

import logging
import shutil
from pathlib import Path

from news_youtube_bot.captions import build_ass, write_ass
from news_youtube_bot.media import ffprobe_duration, require_ffmpeg, run_ffmpeg
from news_youtube_bot.tts_render import WordTiming
from news_youtube_bot.variety import Profile

logger = logging.getLogger(__name__)

_MOTIONS = ("punch", "pan_left", "drift_up", "pan_right", "slow_zoom")
_INTERRUPTS = {
    "question": "Here's the detail",
    "bold_claim": "The claim",
    "story": "Keep this part",
    "stakes": "Why it matters",
    "myth": "The narrower fact",
    "newsroom": "The briefing",
    "one_number": "The figure",
    "so_what": "The change",
}


def _wrap(text: str, width: int = 16, limit: int = 3) -> list[str]:
    words = [word for word in (text or "").split() if word]
    if not words:
        return []
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join(current + [word])
        if current and len(trial) > width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return lines[:limit]


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", r"'\''") + "'"


def _motion(mode: str, duration: float, width: int, height: int) -> str:
    scaled_w = int(width * 1.22)
    scaled_h = int(height * 1.22)
    dur = max(duration, 0.4)
    if mode == "pan_left":
        xy = f"x='(iw-ow)*(1-t/{dur:.3f})':y='(ih-oh)/2'"
    elif mode == "pan_right":
        xy = f"x='(iw-ow)*(t/{dur:.3f})':y='(ih-oh)/2'"
    elif mode == "drift_up":
        xy = f"x='(iw-ow)/2':y='(ih-oh)*(1-t/{dur:.3f})'"
    elif mode == "punch":
        xy = "x='(iw-ow)/2*(1-min(t/0.35,1))':y='(ih-oh)/2*(1-min(t/0.35,1))'"
    else:
        xy = f"x='(iw-ow)/2+(iw-ow)*0.12*t/{dur:.3f}':y='(ih-oh)/2'"
    return (
        f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}:{xy},fps=30,setsar=1,format=yuv420p"
    )


def _drawtext(font: Path, lines: list[tuple[Path, int, float]], size: int) -> str:
    filters = []
    for textfile, ypos, delay in lines:
        filters.append(
            "drawtext="
            f"fontfile={_quote(font)}:"
            f"textfile={_quote(textfile)}:"
            f"fontsize={size}:fontcolor=white:"
            "borderw=5:bordercolor=black@0.72:"
            "x=(w-text_w)/2:"
            f"y={ypos}:"
            f"alpha='if(lt(t,{delay:.2f}),0,min(1,(t-{delay:.2f})/0.16))'"
        )
    return ",".join(filters)


def _write_lines(work: Path, stem: str, lines: list[str]) -> list[Path]:
    paths = []
    for index, line in enumerate(lines):
        path = work / f"{stem}_{index}.txt"
        path.write_text(line, encoding="utf-8")
        paths.append(path)
    return paths


def _encode_common(out: Path, preset: str = "veryfast") -> list[str]:
    return [
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        "-movflags",
        "+faststart",
        str(out),
    ]


def _render_plate(
    out: Path,
    duration: float,
    width: int,
    height: int,
    bg: str,
    accent: str,
    font: Path,
    lines: list[str],
    size: int,
) -> None:
    work = out.parent
    text_paths = _write_lines(work, out.stem + "_line", lines)
    ys = [640 + index * (size + 18) for index in range(len(text_paths))]
    draw = _drawtext(font, [(path, y, index * 0.08) for index, (path, y) in enumerate(zip(text_paths, ys))], size)
    dur = f"{duration:.3f}"
    graph = (
        f"[1]format=rgba,colorchannelmixer=aa=0.9[bar];"
        f"[2]format=rgba,colorchannelmixer=aa=0.28[rail];"
        f"[0][bar]overlay=x=0:y='160+({height - 400})*t/{duration:.3f}'[mid];"
        f"[mid][rail]overlay=x='30+({width - 80})*t/{duration:.3f}':y=0"
    )
    if draw:
        graph += f",{draw}"
    graph += "[v]"
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={bg}:s={width}x{height}:r=30:d={dur}",
        "-f",
        "lavfi",
        "-i",
        f"color=c={accent}:s={width}x22:r=30:d={dur}",
        "-f",
        "lavfi",
        "-i",
        f"color=c={accent}:s=18x{height}:r=30:d={dur}",
        "-filter_complex",
        graph,
        "-map",
        "[v]",
        "-t",
        dur,
        *_encode_common(out),
    ]
    run_ffmpeg(cmd)


def _render_media(
    out: Path,
    source: Path,
    duration: float,
    width: int,
    height: int,
    motion: str,
    font: Path,
    lines: list[str],
    size: int,
    *,
    still: bool,
) -> None:
    work = out.parent
    text_paths = _write_lines(work, out.stem + "_line", lines)
    ys = [620 + index * (size + 16) for index in range(len(text_paths))]
    draw = _drawtext(font, [(path, y, index * 0.06) for index, (path, y) in enumerate(zip(text_paths, ys))], size)
    vf = _motion(motion, duration, width, height)
    if draw:
        vf = vf + "," + draw
    dur = f"{duration:.3f}"
    if still:
        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(source), "-t", dur, "-vf", vf, *_encode_common(out)]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(source),
            "-t",
            dur,
            "-vf",
            vf,
            *_encode_common(out),
        ]
    run_ffmpeg(cmd)


def _allocate(duration: float) -> tuple[float, list[float], float]:
    duration = max(duration, 4.0)
    hook = min(2.2, max(1.5, duration * 0.07))
    payoff = min(3.4, max(2.1, duration * 0.15))
    if hook + payoff > duration - 1.5:
        hook = duration * 0.24
        payoff = duration * 0.24
    middle = max(0.0, duration - hook - payoff)
    slots: list[float] = []
    left = middle
    index = 0
    while left > 0.45:
        slot = 2.5 + ((index * 3) % 8) * 0.22
        if left <= slot + 0.85:
            slots.append(left)
            left = 0.0
            break
        slots.append(slot)
        left -= slot
        index += 1
    if not slots and middle > 0.2:
        slots.append(middle)
    payoff += duration - (hook + sum(slots) + payoff)
    if payoff < 1.0 and slots:
        slots[-1] = max(0.8, slots[-1] + payoff - 1.0)
        payoff = 1.0
    return hook, slots, payoff


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


def render_short(
    *,
    voice: Path,
    words: list[WordTiming],
    music: Path,
    clips: list[Path],
    stills: list[Path],
    hook_text: str,
    payoff_text: str,
    out_path: Path,
    work_dir: Path,
    font: Path,
    profile: Profile,
    width: int,
    height: int,
    preset: str,
    crf: int,
) -> float:
    """Cut b-roll, stills, and kinetic cards to the voiceover and burn captions."""
    require_ffmpeg()
    duration = ffprobe_duration(voice)
    if duration < 12:
        logger.warning("Voiceover is only %.1fs. The short will be short; the script may be thin.", duration)
    elif duration > 68:
        logger.warning("Voiceover is %.1fs, longer than the 30-60s target.", duration)

    build = work_dir / "build"
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True, exist_ok=True)

    hook_d, mids, payoff_d = _allocate(duration)
    hook_lines = _wrap(hook_text)
    payoff_lines = _wrap(payoff_text or "Read the source", width=18, limit=2)
    interrupt = _INTERRUPTS.get(profile.id, "Here's the detail")

    segments: list[tuple[str, Path | None, str, float, list[str], int]] = []
    pool: list[tuple[str, Path]] = [("clip", path) for path in clips] + [("still", path) for path in stills]
    hook_kind, hook_src = pool[0] if pool else ("plate", None)
    segments.append((hook_kind, hook_src, "punch", hook_d, hook_lines, 78))
    for index, slot in enumerate(mids):
        if pool:
            kind, source = pool[(index + 1) % len(pool)]
        else:
            kind, source = "plate", None
        lines: list[str] = []
        size = 64
        if index == min(1, len(mids) - 1) and mids:
            lines = _wrap(interrupt, width=18, limit=2)
        segments.append((kind, source, _MOTIONS[index % len(_MOTIONS)], slot, lines, size))
    segments.append(("plate", None, "slow_zoom", payoff_d, payoff_lines, 80))

    rendered: list[Path] = []
    for index, (kind, source, motion, slot, lines, size) in enumerate(segments):
        target = build / f"seg_{index:02d}.mp4"
        try:
            if kind == "clip" and source is not None:
                _render_media(target, source, slot, width, height, motion, font, lines, size, still=False)
            elif kind == "still" and source is not None:
                _render_media(target, source, slot, width, height, motion, font, lines, size, still=True)
            else:
                _render_plate(target, slot, width, height, profile.bg, profile.accent, font, lines, size)
        except RuntimeError:
            logger.warning("Segment %d failed; using a motion card", index)
            _render_plate(target, slot, width, height, profile.bg, profile.accent, font, lines, size)
        rendered.append(target)

    visual = build / "visual.mp4"
    _concat(rendered, visual, build)
    ass_path = work_dir / "captions.ass"
    write_ass(
        ass_path,
        build_ass(
            words,
            profile,
            font,
            hook_text,
            width=width,
            height=height,
            caption_start=min(1.25, max(0.4, hook_d - 0.4)),
            hook_seconds=hook_d,
        ),
    )
    try:
        _mux(visual, voice, music, ass_path, font.parent, out_path, preset, crf, duration, duck=True)
    except RuntimeError:
        logger.warning("Sidechain duck failed; mixing music at a lower level")
        _mux(visual, voice, music, ass_path, font.parent, out_path, preset, crf, duration, duck=False)
    shutil.rmtree(build, ignore_errors=True)
    return ffprobe_duration(out_path)
