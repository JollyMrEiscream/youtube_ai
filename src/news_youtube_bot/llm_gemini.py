from __future__ import annotations

import json
import logging
from typing import Any

from google import genai
from google.genai import types

from news_youtube_bot.llm_rank import SYSTEM as RANK_SYSTEM
from news_youtube_bot.llm_script import normalize_script_payload, script_request
from news_youtube_bot.models import NewsItem
from news_youtube_bot.variety import Profile

logger = logging.getLogger(__name__)


def _json_from_response(response: Any) -> dict[str, Any]:
    text = getattr(response, "text", None) or ""
    if not text.strip():
        raise ValueError("Empty Gemini response (no text)")
    return json.loads(text)


def rank_stories_gemini(
    api_key: str,
    model_name: str,
    items: list[NewsItem],
    max_stories: int,
) -> list[NewsItem]:
    if not items:
        return []
    if len(items) <= max_stories:
        return items[:max_stories]

    client = genai.Client(api_key=api_key)
    payload = [it.to_llm_dict() for it in items]
    user = json.dumps({"stories": payload, "max_pick": max_stories}, ensure_ascii=False)

    response = client.models.generate_content(
        model=model_name,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=RANK_SYSTEM,
            response_mime_type="application/json",
            temperature=0.3,
        ),
    )
    data = _json_from_response(response)
    ranked_ids = data.get("ranked_ids") or []
    if not isinstance(ranked_ids, list):
        ranked_ids = []

    by_id = {it.id: it for it in items}
    ordered: list[NewsItem] = []
    for rid in ranked_ids:
        if not isinstance(rid, str):
            continue
        it = by_id.get(rid)
        if it and it not in ordered:
            ordered.append(it)
        if len(ordered) >= max_stories:
            break

    if len(ordered) < max_stories:
        for it in items:
            if it not in ordered:
                ordered.append(it)
            if len(ordered) >= max_stories:
                break

    logger.info("Gemini rank selected %d stories", len(ordered))
    return ordered


def build_script_gemini(
    api_key: str,
    model_name: str,
    item: NewsItem,
    profile: Profile,
    excerpt: str = "",
) -> dict[str, Any]:
    client = genai.Client(api_key=api_key)
    system, user = script_request(item, profile, excerpt)
    response = client.models.generate_content(
        model=model_name,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=0.7,
            max_output_tokens=4096,
        ),
    )
    data = normalize_script_payload(_json_from_response(response), item)
    logger.info("Gemini script title=%s", str(data.get("video_title"))[:60])
    return data
