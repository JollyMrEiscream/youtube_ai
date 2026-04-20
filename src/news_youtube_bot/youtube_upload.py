from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from news_youtube_bot.config import Settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _clip_tags(tags: list[str], max_tags: int = 30, max_chars: int = 450) -> list[str]:
    out: list[str] = []
    total = 0
    for raw in tags:
        t = raw.strip()[:30]
        if not t:
            continue
        sep = 2 if out else 0
        if len(out) >= max_tags or total + sep + len(t) > max_chars:
            break
        out.append(t)
        total += sep + len(t)
    return out


def _credentials(settings: Settings) -> Credentials:
    if not settings.google_client_id or not settings.google_client_secret:
        raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required for upload")
    if not settings.youtube_refresh_token:
        raise ValueError("YOUTUBE_REFRESH_TOKEN is required for upload")

    creds = Credentials(
        token=None,
        refresh_token=settings.youtube_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def upload_video(
    settings: Settings,
    file_path: Path,
    title: str,
    description: str,
    tags: list[str],
) -> str:
    creds = _credentials(settings)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": _clip_tags(tags),
            "categoryId": settings.youtube_category_id,
        },
        "status": {
            "privacyStatus": settings.youtube_privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(file_path),
        chunksize=-1,
        resumable=True,
        mimetype="video/mp4",
    )

    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    try:
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info("Upload progress: %d%%", int(status.progress() * 100))
    except HttpError as e:
        logger.error("YouTube API error: %s", e)
        raise

    video_id = response.get("id") if isinstance(response, dict) else None
    if not video_id:
        raise RuntimeError(f"Unexpected upload response: {response!r}")
    logger.info("YouTube video id=%s", video_id)
    return str(video_id)
