from __future__ import annotations

import logging
import time
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

# Docs: https://docs.x.ai/developers/model-capabilities/video/generation
# POST /v1/videos/generations, then GET /v1/videos/{request_id} until status is done.
XAI_BASE_URL = "https://api.x.ai"
DEFAULT_MODEL = "grok-imagine-video-1.5"

PHOTOREAL_RULES = (
    "Photoreal live-action footage from a real camera. "
    "Handheld or gimbal, shallow depth of field, natural lighting, 35mm lens. "
    "The subject is in motion for the whole shot. "
    "No text, no logos, no watermarks, no readable screens, no subtitles. "
    "No faces of real people, no identifiable person, no celebrity likeness. "
    "No surreal artifacts, no extra fingers, no plastic skin, no morphing geometry. "
    "Not a still photograph and not an illustration."
)


def photoreal_prompt(scene: str) -> str:
    subject = " ".join((scene or "a technology workbench").split())
    return f"{subject}. {PHOTOREAL_RULES}"


def make_client(api_key: str, timeout: float, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        base_url=XAI_BASE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
        transport=transport,
        follow_redirects=True,
    )


def request_video(
    client: httpx.Client,
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    duration: int = 4,
    aspect_ratio: str = "9:16",
    resolution: str = "720p",
) -> str:
    response = client.post(
        "/v1/videos/generations",
        json={
            "model": model,
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "generate_audio": False,
        },
    )
    response.raise_for_status()
    payload = response.json()
    request_id = payload.get("request_id")
    if not request_id:
        raise RuntimeError(f"xAI video response had no request_id: {payload}")
    return str(request_id)


def poll_video(
    client: httpx.Client,
    request_id: str,
    *,
    timeout: float = 480,
    interval: float = 5,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    deadline = clock() + timeout
    while True:
        response = client.get(f"/v1/videos/{request_id}")
        response.raise_for_status()
        payload = response.json()
        status = str(payload.get("status") or "")
        if status == "done":
            video = payload.get("video") or {}
            url = video.get("url")
            if not url:
                raise RuntimeError("xAI reported done without a video url")
            return str(url)
        if status in {"failed", "expired"}:
            raise RuntimeError(f"xAI video {status}: {payload.get('error') or payload}")
        if clock() >= deadline:
            raise RuntimeError(f"xAI video generation timed out after {timeout:.0f}s")
        sleep(interval)


def generate_video_url(
    api_key: str,
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    duration: int = 4,
    timeout: float = 480,
    client: httpx.Client | None = None,
) -> str:
    own_client = client is None
    if client is None:
        client = make_client(api_key, timeout=min(60, timeout))
    try:
        request_id = request_video(client, prompt, model=model, duration=duration)
        logger.info("xAI video request %s (%s)", request_id, model)
        return poll_video(client, request_id, timeout=timeout)
    finally:
        if own_client:
            client.close()
