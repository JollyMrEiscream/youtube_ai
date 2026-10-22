from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from news_youtube_bot.models import NewsItem

logger = logging.getLogger(__name__)


SYSTEM = """You are an editor picking stories for separate YouTube Shorts about technology news.
Rank by how well a story stands alone in under a minute: one concrete development, visual, and not a duplicate of another item.
Prefer fresh technology, science, gadgets, AI, security, and chips over politics, hiring threads, and listicles.
Do not pick two items about the same event.
Respond with JSON only, no markdown. Schema:
{"ranked_ids": ["id1", "id2", ...], "notes": {"id1": "one short reason"}}
Order `ranked_ids` from the best Short to the weakest. Only include ids from the provided list."""


def rank_stories(
    client: OpenAI,
    model: str,
    items: list[NewsItem],
    max_stories: int,
) -> list[NewsItem]:
    if not items:
        return []
    if len(items) <= max_stories:
        return items[:max_stories]

    payload = [it.to_llm_dict() for it in items]
    user = json.dumps({"stories": payload, "max_pick": max_stories}, ensure_ascii=False)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    text = resp.choices[0].message.content or "{}"
    data: dict[str, Any] = json.loads(text)
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

    # Fallback: fill from original order if model omitted ids
    if len(ordered) < max_stories:
        for it in items:
            if it not in ordered:
                ordered.append(it)
            if len(ordered) >= max_stories:
                break

    logger.info("LLM rank selected %d stories", len(ordered))
    return ordered
