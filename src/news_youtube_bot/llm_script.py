from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from news_youtube_bot.models import NewsItem

logger = logging.getLogger(__name__)


SYSTEM = """You write neutral spoken news summaries for a short YouTube video.
Rules:
- Use only facts implied by the provided headlines and summaries. Do not invent details, numbers, or quotes.
- If something is uncertain, say it is reported or according to sources.
- Target about 60 to 120 seconds when read aloud at a moderate pace.
- Start with a brief welcome line including today's date (you will be given ISO date in UTC).
- End with a single disclaimer sentence that the segment is an automated summary and viewers should check linked sources.
- Do not use markdown or bullet characters; write plain prose paragraphs suitable for voiceover.
Respond with JSON only. Schema:
{
  "script": "full spoken script as one string with paragraph breaks as newlines",
  "video_title": "concise YouTube title under 100 chars",
  "description": "2-4 sentences plus a Sources section with one line per story: title - URL",
  "tags": ["tag1", "tag2"]
}
tags: 3-8 lowercase topical tags suitable for YouTube."""


def build_script(
    client: OpenAI,
    model: str,
    items: list[NewsItem],
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stories = [it.to_llm_dict() for it in items]
    user = json.dumps({"utc_date": today, "stories": stories}, ensure_ascii=False)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.5,
    )
    text = resp.choices[0].message.content or "{}"
    data: dict[str, Any] = json.loads(text)
    script = (data.get("script") or "").strip()
    if not script:
        raise ValueError("LLM returned empty script")
    data["script"] = script
    data.setdefault("video_title", "News summary")
    data.setdefault("description", "")
    data.setdefault("tags", [])
    if not isinstance(data["tags"], list):
        data["tags"] = []
    logger.info("LLM script generated, title=%s", str(data.get("video_title"))[:60])
    return data
