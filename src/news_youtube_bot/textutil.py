from __future__ import annotations

import hashlib
import html
import re
from html.parser import HTMLParser

_TAG_BREAKS = {"p", "br", "div", "li", "h1", "h2", "h3", "tr", "section", "article"}


_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip == 0 and name in _TAG_BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip == 0 and name in _TAG_BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self.parts.append(data)


def stable_id(link: str) -> str:
    return hashlib.sha256(link.strip().encode("utf-8")).hexdigest()[:16]


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
        text = "".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def clean_title(title: str) -> str:
    title = html.unescape(title or "").strip()
    title = re.sub(
        r"\s+[\|\-–—:]\s+(TechCrunch|The Verge|Ars Technica|Wired|WIRED|BBC(?: News)?|"
        r"The Guardian|Hacker News|MIT Technology Review|The New York Times|NYT|Reuters).*$",
        "",
        title,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", title).strip()


def sentences(text: str, limit: int = 4) -> list[str]:
    plain = html_to_text(text)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return []
    parts = re.split(r"(?<=[.!?])\s+", plain)
    kept: list[str] = []
    for part in parts:
        line = part.strip(" \n\t-•|")
        lower = line.lower()
        if len(line) < 45:
            continue
        if any(ch in line for ch in "{}[]<>"):
            continue
        if "http://" in lower or "https://" in lower or "schema.org" in lower:
            continue
        if len(line) > 320:
            continue
        if any(
            bad in lower
            for bad in (
                "cookie",
                "subscribe",
                "sign up",
                "newsletter",
                "all rights reserved",
                "appeared first on",
                "enable javascript",
                "privacy policy",
                "email digest",
                "homepage feed",
                "posts from this topic",
                "follow us on",
                "share this article",
                "advertisement",
                "related stories",
            )
        ):
            continue
        kept.append(line if line[-1] in ".!?" else line + ".")
        if len(kept) >= limit:
            break
    return kept


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text or ""))


def fit_spoken(text: str, max_words: int = 145) -> str:
    """Drop middle sentences until the voiceover fits a Short, keeping the open and the close."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if word_count(cleaned) <= max_words:
        return cleaned
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", cleaned) if p.strip()]
    if len(parts) <= 2:
        words = cleaned.split()
        clipped = " ".join(words[:max_words])
        cut = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
        return clipped[: cut + 1].strip() if cut > 40 else clipped.strip()
    head = parts[:1]
    ending = parts[-2:] if len(parts) >= 4 else parts[-1:]
    middle = parts[len(head) : len(parts) - len(ending)]
    while middle and word_count(" ".join(head + middle + ending)) > max_words:
        middle.pop()
    out = " ".join(head + middle + ending)
    if word_count(out) > max_words:
        words = out.split()[:max_words]
        clipped = " ".join(words)
        cut = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
        return clipped[: cut + 1].strip() if cut > 40 else clipped.strip()
    return out


def hook_line(title: str, limit_words: int = 8) -> str:
    words = clean_title(title).split()
    if not words:
        return "Today's tech story"
    line = " ".join(words[:limit_words])
    if len(line) > 52:
        line = line[:49].rsplit(" ", 1)[0]
    return line


def ass_escape(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", " ")
    )
