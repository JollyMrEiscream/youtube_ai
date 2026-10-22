from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI

from news_youtube_bot.models import NewsItem
from news_youtube_bot.textutil import fit_spoken, hook_line
from news_youtube_bot.variety import Profile

logger = logging.getLogger(__name__)

SYSTEM = """You write a spoken script for one YouTube Short about a single technology news story.
Sound like a real creator talking to a friend: contractions, mixed sentence lengths, no announcer voice, no corporate tone.
Rules:
- Use only facts that are in the headline, summary, or excerpt. Do not invent numbers, quotes, motives, or what a product "means" if the source did not say it.
- If a detail is thin, say the source hasn't pinned it down. Do not fill the gap.
- The first sentence is the hook and must land in under two seconds. No "welcome back", "let's dive in", "in this video", "buckle up", "game-changer", or "you won't believe".
- One story only. About 95 to 140 words, which reads as roughly 30 to 55 seconds.
- End on a clear payoff and a calm call to action that points at the source. Do not beg for likes.
- Plain spoken prose. No markdown, bullets, or stage directions.
Respond with JSON only:
{
  "script": "spoken words",
  "video_title": "specific title under 90 characters, not all caps",
  "description": "two sentences a human would post, plus the source title and URL",
  "tags": ["lowercase", "topical"],
  "hook_text": "on-screen hook, 4 to 8 words, sentence case",
  "payoff_text": "on-screen payoff, 2 to 6 words",
  "broll_queries": ["three short stock-footage searches, concrete and visual"]
}"""


def script_request(item: NewsItem, profile: Profile, excerpt: str) -> tuple[str, str]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {
        "utc_date": today,
        "profile": {
            "id": profile.id,
            "hook_style": profile.hook_style,
            "structure": profile.structure,
            "cta": profile.cta,
            "spoken_style": profile.tts_instructions,
        },
        "story": item.to_llm_dict(),
        "article_excerpt": (excerpt or "")[:1800],
    }
    return SYSTEM, json.dumps(payload, ensure_ascii=False)


def normalize_script_payload(data: dict[str, Any], item: NewsItem) -> dict[str, Any]:
    script = fit_spoken(str(data.get("script") or "").strip(), max_words=150)
    if not script:
        raise ValueError("LLM returned an empty script")
    title = str(data.get("video_title") or item.title).strip()[:90] or item.title[:90]
    description = str(data.get("description") or "").strip()
    tags = data.get("tags") if isinstance(data.get("tags"), list) else []
    queries = data.get("broll_queries") if isinstance(data.get("broll_queries"), list) else []
    data["script"] = script
    data["video_title"] = title
    data["description"] = description
    data["tags"] = [str(tag) for tag in tags if str(tag).strip()]
    data["hook_text"] = str(data.get("hook_text") or hook_line(title)).strip()[:80]
    data["payoff_text"] = str(data.get("payoff_text") or "Read the source").strip()[:60]
    data["broll_queries"] = [str(query).strip() for query in queries if str(query).strip()][:4]
    return data


def build_script(
    client: OpenAI,
    model: str,
    item: NewsItem,
    profile: Profile,
    excerpt: str = "",
) -> dict[str, Any]:
    system, user = script_request(item, profile, excerpt)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
    )
    data = json.loads(response.choices[0].message.content or "{}")
    normalized = normalize_script_payload(data, item)
    logger.info("LLM script title=%s", normalized["video_title"][:60])
    return normalized
