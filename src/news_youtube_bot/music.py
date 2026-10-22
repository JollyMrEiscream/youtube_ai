from __future__ import annotations

import array
import math
import wave
from pathlib import Path

from news_youtube_bot.media import run_ffmpeg

_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}


def _synth(path: Path, duration: float, style: str, bpm: int, seed: int) -> None:
    """A short original bed: a minor-key pad, a soft kick, and a hat. Not a song."""
    sr = 22050
    beat = 60.0 / max(bpm, 1)
    bar = beat * 4
    loop_n = max(1, int(sr * bar * 4))
    if style == "drive":
        roots = (196.00, 146.83, 164.81, 220.00)
        pump_depth = 0.48
    elif style == "ambient":
        roots = (174.61, 220.00, 261.63, 196.00)
        pump_depth = 0.0
    else:
        roots = (220.00, 174.61, 196.00, 146.83)
        pump_depth = 0.34
    samples = array.array("h")
    low = 0.0
    for i in range(loop_n):
        t = i / sr
        root = roots[int(t / bar) % len(roots)]
        pad = (
            0.22 * math.sin(2 * math.pi * root * t)
            + 0.13 * math.sin(2 * math.pi * root * 1.4983 * t)
            + 0.07 * math.sin(2 * math.pi * root * 2 * t)
        )
        local = t % bar
        env = min(1.0, local / 0.06)
        beat_pos = t % beat
        if style == "ambient":
            perc = 0.04 * math.sin(2 * math.pi * root * 0.5 * t)
        else:
            kick_freq = 52 + 36 * math.exp(-beat_pos * 14)
            kick = math.sin(2 * math.pi * kick_freq * t) * math.exp(-beat_pos * 9)
            noise = (((i * 1103515245 + seed) & 65535) / 65535.0) * 2 - 1
            hat_pos = (t + beat / 2) % beat
            hat = noise * math.exp(-hat_pos * 42) * (0.11 if style == "drive" else 0.06)
            perc = kick * 0.42 + hat
        pump = 1 - pump_depth * math.exp(-beat_pos * 7)
        mixed = (pad * env * 0.85 + perc) * pump
        low += 0.14 * (mixed - low)
        sample = max(-1.0, min(1.0, low * 0.92))
        samples.append(int(sample * 26000))

    target = max(1, int(sr * duration))
    tiled = array.array("h")
    while len(tiled) < target:
        tiled.extend(samples)
    del tiled[target:]
    fade_n = min(len(tiled), int(sr * 0.4))
    for i in range(fade_n):
        idx = len(tiled) - fade_n + i
        tiled[idx] = int(tiled[idx] * (1 - i / fade_n))
    fade_in = min(len(tiled), int(sr * 0.15))
    for i in range(fade_in):
        tiled[i] = int(tiled[i] * (i / fade_in))

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(tiled.tobytes())


def prepare_bed(
    dest: Path,
    duration: float,
    style: str,
    bpm: int,
    seed: int,
    music_dir: Path | None,
) -> tuple[Path, str]:
    tracks: list[Path] = []
    if music_dir and music_dir.is_dir():
        tracks = sorted(p for p in music_dir.iterdir() if p.suffix.lower() in _AUDIO_EXTS and p.is_file())
    if tracks:
        track = tracks[seed % len(tracks)]
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(track),
                "-t",
                f"{duration:.3f}",
                "-ac",
                "2",
                "-ar",
                "48000",
                str(dest),
            ]
        )
        return dest, f"Supplied track {track.name}. Confirm the license before you upload."
    _synth(dest, duration, style, bpm, seed)
    return dest, "Original generated music bed. No third-party composition."
