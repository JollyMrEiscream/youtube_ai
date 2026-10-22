from __future__ import annotations

import re

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "your", "into", "about", "after",
    "before", "over", "under", "what", "when", "where", "why", "how", "are", "was", "were",
    "will", "just", "than", "then", "them", "they", "have", "has", "had", "its", "it's",
    "new", "says", "say", "said", "can", "could", "would", "should", "not", "but", "you",
    "all", "any", "our", "out", "his", "her", "who", "a", "an", "of", "to", "in", "on",
    "at", "by", "or", "as", "is", "it", "be", "we", "their", "more", "most", "using",
    "use", "used", "via", "per", "amid", "gets", "get", "got", "today", "yesterday",
    "headline", "doing", "work", "here", "there", "been", "being", "than", "then",
    "also", "just", "only", "very", "much", "many", "some", "such", "other", "into",
    "across", "while", "where", "which", "whose", "because", "since", "until", "after",
    "before", "about", "above", "below", "between", "through", "during", "without",
    "within", "again", "still", "already", "really", "actually", "something", "anything",
}

_SETTINGS = (
    "data center",
    "server room",
    "clean room",
    "factory",
    "laboratory",
    "warehouse",
    "newsroom",
    "office",
    "street",
    "highway",
    "airport",
    "satellite",
    "rocket",
    "circuit",
    "keyboard",
    "laptop",
    "smartphone",
    "robot",
    "drone",
    "camera",
    "monitor",
    "chip",
    "server",
    "phone",
    "desk",
    "lab",
    "city",
)

_ACTIONS = (
    "typing",
    "assembling",
    "soldering",
    "launching",
    "flying",
    "driving",
    "installing",
    "charging",
    "filming",
    "testing",
    "scanning",
    "printing",
    "packing",
    "shipping",
    "walking",
    "running",
    "opening",
    "plugging",
    "welding",
)

_BRAND = re.compile(
    r"\b(?:"
    r"[A-Z]{2,}[A-Za-z0-9+.-]*"
    r"|[A-Za-z]*[a-z][A-Z][A-Za-z0-9+.-]*"
    r"|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9+.-]*"
    r"|[A-Za-z]*\d[A-Za-z0-9+.-]*"
    r")\b"
)


def _normalize(text: str) -> str:
    return (text or "").replace("-", " ").replace("’", "'")


def queries_for_line(line: str, limit: int = 3) -> list[str]:
    """Search phrases for one spoken line: products, companies, places, actions."""
    text = _normalize(line)
    brands: list[str] = []
    for token in _BRAND.findall(text):
        if token.lower() in _STOP or token.lower() in brands:
            continue
        if token not in brands:
            brands.append(token)
    lowered = text.lower()
    settings = [name for name in _SETTINGS if name in lowered]
    actions = [name for name in _ACTIONS if name in lowered]
    nouns = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z0-9+]{3,}", lowered)
        if word not in _STOP and word not in {name.split()[-1] for name in settings}
    ]
    queries: list[str] = []

    def add(query: str) -> None:
        cleaned = " ".join(query.split())
        if not cleaned:
            return
        key = cleaned.lower()
        if key in {item.lower() for item in queries}:
            return
        queries.append(cleaned)

    if brands and settings:
        add(f"{brands[0]} {settings[0]}")
    if brands and nouns:
        add(f"{brands[0]} {nouns[0]}")
    elif brands:
        add(" ".join(brands[:2]))
    if actions and settings:
        add(f"{actions[0]} {settings[0]}")
    elif actions and nouns:
        add(f"{actions[0]} {nouns[0]}")
    if settings:
        add(settings[0])
    if len(nouns) >= 2:
        add(f"{nouns[0]} {nouns[1]}")
    elif nouns:
        add(nouns[0])
    return queries[:limit]
