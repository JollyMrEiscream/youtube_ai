from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

import edge_tts
from openai import OpenAI

from news_youtube_bot.config import Settings
from news_youtube_bot.media import ffprobe_duration
from news_youtube_bot.variety import Profile

logger = logging.getLogger(__name__)

_OPENAI_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"}


@dataclass
class WordTiming:
    text: str
    start: float
    end: float


def estimate_word_timings(script: str, duration: float) -> list[WordTiming]:
    tokens = [token for token in script.split() if token.strip()]
    if not tokens:
        return []
    weights = [max(len(token.strip(".,!?;:\"'()")), 1) for token in tokens]
    total = float(sum(weights))
    usable = max(duration - 0.12, 0.4)
    cursor = 0.06
    timings: list[WordTiming] = []
    for token, weight in zip(tokens, weights):
        span = usable * weight / total
        timings.append(WordTiming(token, cursor, cursor + max(span, 0.04)))
        cursor += span
    return timings


def _voice_for(settings: Settings, profile: Profile, engine: str) -> str:
    if settings.tts_voice_explicit and settings.tts_voice:
        if engine == "openai" and settings.tts_voice not in _OPENAI_VOICES:
            logger.warning("TTS_VOICE %s is not an OpenAI voice; using %s", settings.tts_voice, profile.openai_voice)
            return profile.openai_voice
        return settings.tts_voice
    return profile.openai_voice if engine == "openai" else profile.edge_voice


async def _edge_save(text: str, voice: str, rate: str, out_path: Path) -> list[WordTiming]:
    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    audio = bytearray()
    words: list[WordTiming] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            start = float(chunk["offset"]) / 10_000_000
            end = float(chunk["offset"] + chunk["duration"]) / 10_000_000
            token = str(chunk.get("text") or "").strip()
            if token:
                words.append(WordTiming(token, start, max(end, start + 0.04)))
    if not audio:
        raise RuntimeError(f"Edge TTS returned no audio for voice {voice}")
    out_path.write_bytes(audio)
    return words


def render_tts_edge(script: str, voice: str, rate: str, out_path: Path) -> list[WordTiming]:
    logger.info("Edge TTS voice=%s rate=%s", voice, rate)
    words = asyncio.run(_edge_save(script, voice, rate, out_path))
    if not words:
        words = estimate_word_timings(script, ffprobe_duration(out_path))
    return words


def render_tts_openai(
    settings: Settings,
    script: str,
    voice: str,
    instructions: str,
    out_path: Path,
) -> list[WordTiming]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY required for OpenAI TTS")
    client = OpenAI(api_key=settings.openai_api_key)
    logger.info("OpenAI TTS model=%s voice=%s", settings.tts_model, voice)
    kwargs: dict[str, object] = {
        "model": settings.tts_model,
        "voice": voice,
        "input": script,
        "response_format": "mp3",
    }
    if settings.tts_model.startswith("gpt-4o"):
        kwargs["instructions"] = instructions
    try:
        response = client.audio.speech.create(**kwargs)  # type: ignore[arg-type]
    except TypeError:
        kwargs.pop("instructions", None)
        response = client.audio.speech.create(**kwargs)  # type: ignore[arg-type]
    out_path.write_bytes(response.content)
    return estimate_word_timings(script, ffprobe_duration(out_path))


def render_tts(
    settings: Settings,
    script: str,
    out_path: Path,
    profile: Profile,
) -> list[WordTiming]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    engine = settings.tts_engine
    if engine == "openai" and not settings.openai_api_key:
        logger.warning("TTS_ENGINE=openai but OPENAI_API_KEY is missing; using Edge TTS")
        engine = "edge"
    if engine not in ("edge", "openai"):
        raise ValueError(f"Unknown TTS_ENGINE: {engine!r}; use edge or openai")
    voice = _voice_for(settings, profile, engine)
    rate = settings.tts_rate or profile.rate
    if engine == "edge":
        return render_tts_edge(script, voice, rate, out_path)
    return render_tts_openai(settings, script, voice, profile.tts_instructions, out_path)
