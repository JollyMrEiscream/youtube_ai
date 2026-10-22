from __future__ import annotations

import array
import math
import shutil
import wave
from pathlib import Path

import pytest

import subprocess

from news_youtube_bot.footage import VisualShot
from news_youtube_bot.media import ffprobe_duration, ffprobe_video, find_font
from news_youtube_bot.music import prepare_bed
from news_youtube_bot.tts_render import estimate_word_timings
from news_youtube_bot.variety import PROFILES
from news_youtube_bot.video_render import render_short


def _moving_clip(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=720x1280:rate=30:duration=4",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(path),
        ],
        check=True,
    )


def _tone(path: Path, seconds: float = 6.0) -> None:
    sr = 22050
    frames = array.array("h")
    for i in range(int(sr * seconds)):
        frames.append(int(0.2 * math.sin(2 * math.pi * 220 * i / sr) * 32767))
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(frames.tobytes())


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_motion_short_renders(tmp_path: Path):
    voice = tmp_path / "voice.wav"
    _tone(voice, 6.0)
    script = "Seen this yet? A lab shipped a quieter fan for server racks today."
    words = estimate_word_timings(script, 6.0)
    music, _credit = prepare_bed(tmp_path / "bed.wav", 6.3, "pulse", 110, 3, None)
    left = tmp_path / "left.mp4"
    right = tmp_path / "right.mp4"
    _moving_clip(left)
    _moving_clip(right)
    shots = [
        VisualShot(left, 0.2, 3.0, "Video by Ada on Pexels (https://www.pexels.com/video/1)", "pexels", "server fan", "pexels:1"),
        VisualShot(right, 0.4, 3.0, "Video by Sam on Pixabay (https://pixabay.com/videos/2)", "pixabay", "rack", "pixabay:2"),
    ]
    out = tmp_path / "short.mp4"
    duration = render_short(
        voice=voice,
        words=words,
        music=music,
        shots=shots,
        hook_text="A quieter server fan",
        payoff_text="Read the source",
        out_path=out,
        work_dir=tmp_path,
        font=find_font(Path("/workspace")),
        profile=PROFILES[0],
        width=1080,
        height=1920,
        preset="veryfast",
        crf=23,
    )
    assert out.is_file()
    assert out.stat().st_size > 20_000
    assert 4.0 < duration < 12.0
    probed = ffprobe_video(out)
    assert probed is not None
    assert probed[0] == 1080
    assert probed[1] == 1920
    assert ffprobe_duration(out) == pytest.approx(duration, abs=0.2)
