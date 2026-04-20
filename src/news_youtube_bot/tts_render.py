from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import edge_tts
from openai import OpenAI

from news_youtube_bot.config import Settings

logger = logging.getLogger(__name__)


def render_tts_openai(
    settings: Settings,
    script: str,
    out_path: Path,
) -> None:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY required for OpenAI TTS")
    client = OpenAI(api_key=settings.openai_api_key)
    voice = settings.tts_voice or "alloy"
    logger.info("OpenAI TTS voice=%s", voice)
    response = client.audio.speech.create(
        model="tts-1",
        voice=voice,  # type: ignore[arg-type]
        input=script,
        response_format="mp3",
    )
    out_path.write_bytes(response.content)


async def _edge_save(voice: str, text: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))


def render_tts_edge(script: str, voice: str, out_path: Path) -> None:
    logger.info("Edge TTS voice=%s", voice)
    asyncio.run(_edge_save(voice, script, out_path))


def render_tts(settings: Settings, script: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    engine = settings.tts_engine
    if engine == "edge":
        v = settings.tts_voice if settings.tts_voice != "alloy" else "en-US-GuyNeural"
        render_tts_edge(script, v, out_path)
    elif engine == "openai":
        render_tts_openai(settings, script, out_path)
    else:
        raise ValueError(f"Unknown TTS_ENGINE: {engine!r}; use openai or edge")
