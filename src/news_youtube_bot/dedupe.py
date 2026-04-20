from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from news_youtube_bot.models import NewsItem

logger = logging.getLogger(__name__)

_TITLE_SIMILARITY_THRESHOLD = 0.86


def canonicalize_url(link: str) -> str:
    """Normalize URL for deduplication (strip tracking params, lowercase host)."""
    try:
        p = urlparse(link.strip())
    except Exception:
        return link.strip().lower()

    scheme = (p.scheme or "https").lower()
    netloc = (p.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = p.path or ""
    # Drop common tracking query keys
    drop_keys = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
    }
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in drop_keys]
    query = urlencode(q)
    frag = ""
    return urlunparse((scheme, netloc, path, "", query, frag))


def _normalize_title(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def dedupe_items(items: list[NewsItem]) -> list[NewsItem]:
    """Remove duplicates by canonical URL and near-duplicate titles (keep first)."""
    by_url: dict[str, NewsItem] = {}
    order: list[NewsItem] = []

    for item in items:
        key = canonicalize_url(item.link)
        if key in by_url:
            continue
        by_url[key] = item
        order.append(item)

    # Title fuzzy dedupe against already kept
    final: list[NewsItem] = []
    norms: list[str] = []
    for item in order:
        nt = _normalize_title(item.title)
        dup = False
        for prev in norms:
            if SequenceMatcher(None, nt, prev).ratio() >= _TITLE_SIMILARITY_THRESHOLD:
                dup = True
                break
        if dup:
            logger.debug("Fuzzy title dedupe dropped: %s", item.title[:80])
            continue
        norms.append(nt)
        final.append(item)

    logger.info("Dedupe: %d -> %d items", len(items), len(final))
    return final
