from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import httpx

from news_youtube_bot.article import download_file
from news_youtube_bot.beats import Beat, plan_beats
from news_youtube_bot.clip_gate import (
    MAX_STILL_SHARE,
    choose_window,
    crop_short_side,
    gate_file,
    gate_source,
    parse_scene_scores,
    still_share,
)
from news_youtube_bot.clip_memory import AiClipBudget, UsedClipStore
from news_youtube_bot.config import Settings
from news_youtube_bot.grok_video import generate_video_url, photoreal_prompt
from news_youtube_bot.keywords import queries_for_line
from news_youtube_bot.media import USER_AGENT, ffprobe_duration, ffprobe_video, run_ffmpeg
from news_youtube_bot.tts_render import WordTiming

logger = logging.getLogger(__name__)

_QUERY_TOKEN = re.compile(r"[A-Za-z]{4,}")
_STOP = {"with", "from", "that", "this", "your", "into", "about", "video", "clip"}


class FootageRejected(Exception):
    """The Short would have been a slideshow. It goes to review with a reason instead."""

    def __init__(self, reason: str, *, retryable: bool) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retryable = retryable


@dataclass
class Candidate:
    download_url: str
    stable_id: str
    credit: str
    source: str
    width: int
    height: int
    duration: float
    title: str = ""
    tags: str = ""


@dataclass
class VisualShot:
    path: Path
    in_point: float
    duration: float
    credit: str
    source: str
    query: str
    stable_id: str


def missing_footage_keys(settings: Settings) -> list[str]:
    missing: list[str] = []
    if not settings.pexels_api_key:
        missing.append("PEXELS_API_KEY")
    if not settings.pixabay_api_key:
        missing.append("PIXABAY_API_KEY")
    if not settings.xai_api_key:
        missing.append("XAI_API_KEY")
    return missing


def log_footage_keys(settings: Settings) -> list[str]:
    missing = missing_footage_keys(settings)
    if "PEXELS_API_KEY" in missing:
        logger.warning(
            "PEXELS_API_KEY is not set, so Pexels Videos is skipped. "
            "Create a key at https://www.pexels.com/api/"
        )
    if "PIXABAY_API_KEY" in missing:
        logger.warning(
            "PIXABAY_API_KEY is not set, so Pixabay Videos is skipped. "
            "Create a key at https://pixabay.com/api/docs/"
        )
    if "XAI_API_KEY" in missing:
        logger.warning(
            "XAI_API_KEY is not set, so beats with no stock match will not get a Grok clip. "
            "Create a key at https://console.x.ai/ and see "
            "https://docs.x.ai/developers/model-capabilities/video/generation"
        )
    if not missing:
        logger.info("Footage keys present: Pexels, Pixabay, and xAI.")
    elif len(missing) == 3:
        logger.error(
            "No footage keys (PEXELS_API_KEY, PIXABAY_API_KEY, XAI_API_KEY). "
            "Shorts will fail into the review queue instead of rendering a slideshow."
        )
    return missing


def _file_rank(width: int, height: int) -> tuple[int, int, int]:
    portrait = 0 if height >= width else 1
    edge = crop_short_side(width, height)
    return (portrait, abs(edge - 1080), -edge)


def tags_match_query(query: str, tags: str) -> bool:
    if not (tags or "").strip():
        return True
    tokens = [token.lower() for token in _QUERY_TOKEN.findall(query or "") if token.lower() not in _STOP]
    if not tokens:
        return True
    hay = tags.lower().replace("_", " ")
    strong = [token for token in tokens if len(token) >= 5] or tokens
    return any(token in hay for token in strong)


def _best_file(files: list[dict], duration: float, title: str, url: str, tags: str) -> tuple[dict, str] | None:
    ranked: list[tuple[tuple[int, int, int], dict]] = []
    for item in files:
        link = item.get("link") or item.get("url")
        if not link:
            continue
        try:
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
        except (TypeError, ValueError):
            continue
        file_type = str(item.get("file_type") or item.get("type") or "video/mp4")
        if "mp4" not in file_type and not str(link).lower().split("?")[0].endswith(".mp4"):
            continue
        ok, _reason = gate_source(width=width, height=height, duration=duration, title=title, url=str(link), tags=tags)
        if not ok:
            continue
        ranked.append((_file_rank(width, height), item))
    if not ranked:
        return None
    ranked.sort(key=lambda pair: pair[0])
    chosen = ranked[0][1]
    link = str(chosen.get("link") or chosen.get("url"))
    return chosen, link


def search_pexels(query: str, api_key: str, client: httpx.Client) -> list[Candidate]:
    found: list[Candidate] = []
    for params in (
        {"query": query, "orientation": "portrait", "per_page": 8, "size": "medium"},
        {"query": query, "per_page": 8, "size": "medium"},
    ):
        try:
            response = client.get(
                "https://api.pexels.com/videos/search",
                params=params,
                headers={"Authorization": api_key},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("Pexels search failed for %r: %s", query, exc)
            continue
        for video in payload.get("videos") or []:
            try:
                duration = float(video.get("duration") or 0)
            except (TypeError, ValueError):
                duration = 0
            page = str(video.get("url") or "")
            user = ((video.get("user") or {}).get("name")) or "a Pexels contributor"
            chosen = _best_file(list(video.get("video_files") or []), duration, page, page, "")
            if chosen is None:
                continue
            item, link = chosen
            video_id = video.get("id") or hashlib.sha256(link.encode("utf-8")).hexdigest()[:12]
            found.append(
                Candidate(
                    download_url=link,
                    stable_id=f"pexels:{video_id}",
                    credit=f"Video by {user} on Pexels ({page or 'https://www.pexels.com'})",
                    source="pexels",
                    width=int(item.get("width") or 0),
                    height=int(item.get("height") or 0),
                    duration=duration,
                    title=page,
                )
            )
        if found:
            break
    found.sort(key=lambda item: _file_rank(item.width, item.height))
    return found


def search_pixabay(query: str, api_key: str, client: httpx.Client) -> list[Candidate]:
    params = {
        "key": api_key,
        "q": query,
        "video_type": "film",
        "safesearch": "true",
        "per_page": 8,
    }
    try:
        response = client.get("https://pixabay.com/api/videos/", params=params)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Pixabay search failed for %r: %s", query, exc)
        return []
    found: list[Candidate] = []
    for hit in payload.get("hits") or []:
        tags = str(hit.get("tags") or "")
        if not tags_match_query(query, tags):
            continue
        try:
            duration = float(hit.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        page = str(hit.get("pageURL") or "https://pixabay.com")
        files = []
        for _name, rendition in (hit.get("videos") or {}).items():
            if isinstance(rendition, dict):
                files.append(rendition)
        chosen = _best_file(files, duration, page, page, tags)
        if chosen is None:
            continue
        item, link = chosen
        user = hit.get("user") or "a Pixabay contributor"
        hit_id = hit.get("id") or hashlib.sha256(link.encode("utf-8")).hexdigest()[:12]
        found.append(
            Candidate(
                download_url=link,
                stable_id=f"pixabay:{hit_id}",
                credit=f"Video by {user} on Pixabay ({page})",
                source="pixabay",
                width=int(item.get("width") or 0),
                height=int(item.get("height") or 0),
                duration=duration,
                title=page,
                tags=tags,
            )
        )
    found.sort(key=lambda item: _file_rank(item.width, item.height))
    return found


def search_stock(settings: Settings, query: str, client: httpx.Client | None = None) -> list[Candidate]:
    own = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Authorization": settings.pexels_api_key or ""},
            timeout=settings.fetch_timeout_seconds,
            follow_redirects=True,
        )
    try:
        found: list[Candidate] = []
        if settings.pexels_api_key:
            found.extend(search_pexels(query, settings.pexels_api_key, client))
        if settings.pixabay_api_key:
            # Pixabay wants the key in the query string. A separate client avoids sending the Pexels header.
            if own:
                found.extend(_pixabay_with_own_client(settings, query))
            else:
                found.extend(search_pixabay(query, settings.pixabay_api_key, client))
        return found
    finally:
        if own:
            client.close()


def _pixabay_with_own_client(settings: Settings, query: str) -> list[Candidate]:
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=settings.fetch_timeout_seconds,
        follow_redirects=True,
    ) as client:
        return search_pixabay(query, settings.pixabay_api_key or "", client)


def _scene_log(path: Path) -> str:
    try:
        result = __import__("subprocess").run(
            [
                "ffmpeg",
                "-v",
                "info",
                "-i",
                str(path),
                "-vf",
                "select='gt(scene,0.08)',metadata=print",
                "-an",
                "-f",
                "null",
                "-",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return (result.stderr or "") + (result.stdout or "")


def window_for(path: Path, want: float) -> tuple[float, float]:
    probed = ffprobe_video(path)
    duration = probed[2] if probed else ffprobe_duration(path)
    scenes = parse_scene_scores(_scene_log(path))
    return choose_window(duration, want, scenes)


def _cache_file(cache: Path, stable_id: str) -> Path:
    digest = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:20]
    return cache / f"{digest}.mp4"


def _download_candidate(settings: Settings, candidate: Candidate, dest: Path) -> bool:
    if dest.is_file() and dest.stat().st_size > 20_000:
        return True
    return download_file(candidate.download_url, dest, settings.fetch_timeout_seconds, max_bytes=80_000_000)


def queries_for_beat(beat: Beat, story_title: str, extras: list[str], index: int) -> list[str]:
    queries = queries_for_line(beat.text)
    if not queries:
        queries = queries_for_line(story_title)
    if extras:
        extra = extras[index % len(extras)].strip()
        if extra and extra.lower() not in {item.lower() for item in queries}:
            queries.append(extra)
    if not queries:
        queries = ["technology laboratory"]
    seen: set[str] = set()
    out: list[str] = []
    for query in queries:
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(query)
    return out[:4]


def _accept(
    settings: Settings,
    candidate: Candidate,
    cache: Path,
    used_ids: set[str],
    memory: UsedClipStore,
    today,
) -> Path | None:
    if candidate.stable_id in used_ids or memory.seen(candidate.stable_id, today):
        return None
    ok, reason = gate_source(
        width=candidate.width,
        height=candidate.height,
        duration=candidate.duration,
        title=candidate.title,
        url=candidate.download_url,
        tags=candidate.tags,
    )
    if not ok:
        logger.info("Skipped %s: %s", candidate.stable_id, reason)
        return None
    dest = _cache_file(cache, candidate.stable_id)
    if not _download_candidate(settings, candidate, dest):
        return None
    passed, why = gate_file(dest, source=candidate.source)
    if not passed:
        logger.info("Rejected %s after download: %s", candidate.stable_id, why)
        dest.unlink(missing_ok=True)
        return None
    return dest


def _borrow(existing: list[VisualShot], beat: Beat) -> VisualShot | None:
    if len(existing) < 2:
        return None
    counts: dict[str, int] = {}
    for shot in existing:
        counts[shot.stable_id] = counts.get(shot.stable_id, 0) + 1
    previous = existing[-1].stable_id
    for shot in existing:
        if shot.stable_id == previous or counts.get(shot.stable_id, 0) >= 2:
            continue
        return replace(
            shot,
            duration=beat.duration,
            credit=shot.credit + " (second use in this Short)",
        )
    return None


def _generate(
    settings: Settings,
    scene: str,
    cache: Path,
    budget: AiClipBudget,
    used_ids: set[str],
    memory: UsedClipStore,
    today,
) -> tuple[Candidate, Path] | None:
    if not settings.xai_api_key:
        return None
    if budget.remaining() <= 0:
        logger.warning("MAX_AI_CLIPS_PER_DAY=%d is spent. No more Grok clips today.", budget.limit)
        return None
    prompt = photoreal_prompt(scene)
    stable_id = "grok:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:20]
    if stable_id in used_ids or memory.seen(stable_id, today):
        return None
    dest = cache / f"{stable_id.split(':', 1)[1]}.mp4"
    if not dest.is_file():
        try:
            url = generate_video_url(
                settings.xai_api_key,
                prompt,
                model=settings.xai_video_model,
                duration=settings.xai_video_duration,
                timeout=settings.xai_poll_timeout,
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            logger.warning("Grok video failed for %r: %s", scene, exc)
            return None
        budget.consume()
        if not download_file(url, dest, max(settings.fetch_timeout_seconds, 60), max_bytes=80_000_000):
            return None
    passed, why = gate_file(dest, source="grok")
    if not passed:
        logger.info("Rejected generated clip: %s", why)
        dest.unlink(missing_ok=True)
        return None
    probed = ffprobe_video(dest)
    width, height, duration = probed if probed else (720, 1280, float(settings.xai_video_duration))
    credit = (
        f"Generated with xAI Grok Imagine ({settings.xai_video_model}) for \"{scene}\". "
        "Synthetic b-roll, not a recording of a real product or person."
    )
    candidate = Candidate(
        download_url=str(dest),
        stable_id=stable_id,
        credit=credit,
        source="grok",
        width=width,
        height=height,
        duration=duration,
        title=scene,
    )
    return candidate, dest


def assemble_footage(
    settings: Settings,
    *,
    script: str,
    words: list[WordTiming],
    voice_seconds: float,
    story_title: str,
    story_id: str,
    extra_queries: list[str],
    when: datetime | None = None,
    client: httpx.Client | None = None,
) -> list[VisualShot]:
    """One moving-video shot per beat. Raises FootageRejected instead of inventing a slideshow."""
    moment = when or datetime.now(timezone.utc)
    today = moment.date()
    missing = missing_footage_keys(settings)
    beats = plan_beats(words, voice_seconds)
    if not beats:
        raise FootageRejected("No spoken beats to cover with video.", retryable=True)

    cache = settings.data_dir / "cache" / "clips"
    cache.mkdir(parents=True, exist_ok=True)
    memory = UsedClipStore(settings.data_dir / "used_clips.json", days=settings.clip_reuse_days)
    budget = AiClipBudget(settings.data_dir / "ai_clip_budget.json", today.isoformat(), settings.max_ai_clips_per_day)
    used_ids: set[str] = set()
    shots: list[VisualShot] = []
    misses: list[str] = []
    budget_blocked = False
    del script

    for index, beat in enumerate(beats):
        queries = queries_for_beat(beat, story_title, extra_queries, index)
        chosen: tuple[Candidate, Path, float, float] | None = None
        for query in queries:
            if chosen:
                break
            for candidate in search_stock(settings, query, client):
                path = _accept(settings, candidate, cache, used_ids, memory, today)
                if path is None:
                    continue
                start, length = window_for(path, beat.duration)
                if length + 0.25 < beat.duration:
                    logger.info("Clip %s is too short for a %.1fs beat", candidate.stable_id, beat.duration)
                    continue
                chosen = (candidate, path, start, min(beat.duration, length))
                break
        if chosen is None and settings.xai_api_key:
            if budget.remaining() <= 0:
                budget_blocked = True
            else:
                generated = _generate(
                    settings,
                    queries[0],
                    cache,
                    budget,
                    used_ids,
                    memory,
                    today,
                )
                if generated:
                    start, length = window_for(generated[1], beat.duration)
                    if length + 0.25 >= beat.duration:
                        chosen = (generated[0], generated[1], start, min(beat.duration, length))
                    else:
                        logger.info("Generated clip is too short for a %.1fs beat", beat.duration)
        if chosen is None:
            borrowed = _borrow(shots, beat)
            if borrowed is not None:
                start, length = window_for(borrowed.path, beat.duration)
                if length + 0.25 >= beat.duration:
                    shots.append(
                        replace(
                            borrowed,
                            in_point=start,
                            duration=min(beat.duration, length),
                        )
                    )
                    continue
            misses.append(queries[0])
            continue
        candidate, path, start, shot_length = chosen
        shots.append(
            VisualShot(
                path=path,
                in_point=start,
                duration=shot_length,
                credit=candidate.credit,
                source=candidate.source,
                query=queries[0],
                stable_id=candidate.stable_id,
            )
        )
        used_ids.add(candidate.stable_id)
        memory.mark(candidate.stable_id, today, story_id)

    video_seconds = sum(shot.duration for shot in shots)
    missing_seconds = max(0.0, voice_seconds - video_seconds)
    uncovered = bool(misses) or len(shots) < len(beats) or still_share(missing_seconds, voice_seconds) > MAX_STILL_SHARE
    if uncovered:
        key_note = ""
        if missing:
            key_note = " Missing keys: " + ", ".join(missing) + "."
        budget_note = ""
        if budget_blocked:
            budget_note = f" Grok budget is spent (MAX_AI_CLIPS_PER_DAY={budget.limit})."
        elif not settings.xai_api_key:
            budget_note = " No XAI_API_KEY, so nothing was generated to fill the gap."
        reason = (
            "Refusing to render a slideshow. "
            f"Moving video covers {len(shots)}/{len(beats)} shots "
            f"({video_seconds:.1f}s of {voice_seconds:.1f}s). "
            f"No usable stock video for: {', '.join(misses[:4]) or 'the remaining beats'}."
            f"{key_note}{budget_note} "
            f"Stills stay under {MAX_STILL_SHARE:.0%} of the runtime and never go full screen."
        )
        attempted = bool(settings.pexels_api_key or settings.pixabay_api_key or settings.xai_api_key)
        retryable = (not attempted) or budget_blocked
        raise FootageRejected(reason, retryable=retryable)

    logger.info(
        "Footage for %s: %d moving shot(s) from %s",
        story_id,
        len(shots),
        ", ".join(sorted({shot.source for shot in shots})),
    )
    return shots


def read_script_beats(script: str, words: list[WordTiming], voice_seconds: float) -> list[Beat]:
    """Used by tests and logs. `script` is accepted so callers can pass the spoken text."""
    del script
    return plan_beats(words, voice_seconds)


def strongest_trim_command(source: Path, dest: Path, start: float, length: float) -> None:
    """Optional pre-trim. The renderer seeks itself; this is here for tests and previews."""
    run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, start):.3f}",
            "-i",
            str(source),
            "-t",
            f"{length:.3f}",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ]
    )
