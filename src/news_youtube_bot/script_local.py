from __future__ import annotations

import re
from difflib import SequenceMatcher

from news_youtube_bot.models import NewsItem
from news_youtube_bot.textutil import clean_title, fit_spoken, hook_line, sentences
from news_youtube_bot.variety import Profile

def _outlet(item: NewsItem) -> str:
    name = (item.feed_name or "").strip()
    return name or "the source"


def _facts(item: NewsItem, excerpt: str) -> list[str]:
    found = sentences(excerpt, limit=3) or sentences(item.summary, limit=3)
    title = clean_title(item.title)
    if not found:
        return [f"The headline is: {title}."]
    # Drop a sentence that is just the title repeated.
    title_l = title.lower().strip(".")
    trimmed = []
    for fact in found:
        fact_l = fact.lower().strip(".")
        if fact_l == title_l or title_l in fact_l:
            continue
        if SequenceMatcher(None, fact_l, title_l).ratio() >= 0.72:
            continue
        trimmed.append(fact)
    return trimmed or found[:1]


def _spoken_title(title: str) -> str:
    spoken = clean_title(title).rstrip(".")
    if not spoken:
        return "A tech story moved today."
    if spoken[-1] not in ".!?":
        spoken += "."
    return spoken[0].upper() + spoken[1:]


def _number_opener(title: str, profile: Profile, salt: int) -> str:
    if re.search(r"\d", title):
        return profile.openers[0]
    return profile.openers[salt % len(profile.openers)]


def build_script_local(item: NewsItem, profile: Profile, excerpt: str = "") -> dict[str, object]:
    """Creator-style script that uses only the headline and source text.

    This is the no-key path. A Gemini or OpenAI key produces a tighter script
    from the same facts; this writer exists so the pipeline still renders.
    """
    outlet = _outlet(item)
    title = clean_title(item.title)
    facts = _facts(item, excerpt)
    salt = sum(ord(c) for c in item.id)
    if profile.id == "one_number":
        opener = _number_opener(title, profile, salt)
    else:
        opener = profile.openers[salt % len(profile.openers)]
    signoff = profile.signoffs[salt % len(profile.signoffs)].format(outlet=outlet)
    spoken = _spoken_title(title)
    fact_text = " ".join(facts[:3])

    if profile.id == "question":
        body = f"{opener} {spoken} {fact_text}"
    elif profile.id == "bold_claim":
        body = f"{opener} {spoken} {outlet} is reporting it. {fact_text}"
    elif profile.id == "story":
        body = f"{opener} {fact_text} The headline on it: {spoken}"
    elif profile.id == "myth":
        body = f"{opener} {spoken} What the writeup actually gives us: {fact_text}"
    elif profile.id == "newsroom":
        body = f"{opener} {spoken} {fact_text}"
    elif profile.id == "so_what":
        body = f"{opener} {spoken} {fact_text}"
    elif profile.id == "one_number":
        body = f"{opener} {spoken} {fact_text}"
    else:
        body = f"{opener} {spoken} {fact_text}"

    script = fit_spoken(f"{body} {signoff}", max_words=145)

    tags = ["tech", "technology", "shorts"]
    if item.feed_name:
        tags.append(re.sub(r"[^a-z0-9]+", "", item.feed_name.lower())[:24])

    return {
        "script": script,
        "video_title": title[:90],
        "description": (
            f"{spoken}\n\n"
            f"Source: {item.title}\n{item.link}\n\n"
            "A short briefing of that report. The voiceover is synthetic. "
            "Read the source before you repeat the details."
        ),
        "tags": tags,
        "hook_text": hook_line(title),
        "payoff_text": "Read the source",
        "broll_queries": [],
    }
