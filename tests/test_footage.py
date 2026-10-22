from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx
import pytest

from news_youtube_bot.beats import plan_beats
from news_youtube_bot.clip_gate import (
    choose_window,
    crop_short_side,
    gate_source,
    parse_scene_scores,
    static_corners_look_like_watermark,
    still_share,
)
from news_youtube_bot.clip_memory import AiClipBudget, UsedClipStore
from news_youtube_bot.config import Settings
from news_youtube_bot.footage import (
    Candidate,
    FootageRejected,
    StockRateLimit,
    _generate,
    assemble_footage,
    search_pexels,
    search_pixabay,
    search_stock,
)
from news_youtube_bot.grok_video import generate_video_url, photoreal_prompt, poll_video, request_video
from news_youtube_bot.tts_render import estimate_word_timings
from news_youtube_bot.video_render import cover_filter


def test_beats_land_on_word_boundaries_every_two_or_three_seconds():
    script = "one two three four five six seven eight nine ten eleven twelve"
    words = estimate_word_timings(script, 12)
    beats = plan_beats(words, 12)
    assert beats[0].start < 0.2
    assert beats[-1].end == pytest.approx(12, abs=0.05)
    # Interior cuts stay inside 2–3s. The tail can be a bit shorter when the
    # previous shot is already at the cap and the next word boundary is late.
    assert all(beat.duration <= 3.15 for beat in beats)
    assert all(beat.duration >= 1.9 for beat in beats[:-1])
    assert beats[-1].duration >= 1.2
    for beat in beats[:-1]:
        assert any(abs(beat.end - word.end) < 0.02 for word in words)


def test_crop_and_window_prefer_a_real_cut():
    assert crop_short_side(1080, 1920) >= 720
    assert crop_short_side(1920, 1080) < 720
    assert crop_short_side(1280, 720) < 720
    assert crop_short_side(1920, 1280) >= 720
    ok, _reason = gate_source(width=1080, height=1920, duration=6, url="https://cdn.example/vert.mp4")
    assert ok
    scenes = parse_scene_scores(
        "frame:1 pts_time:1.20\nlavfi.scene_score=0.10\nframe:2 pts_time:4.80\nlavfi.scene_score=0.62\n"
    )
    start, length = choose_window(10, 2.4, scenes)
    assert start == pytest.approx(4.65, abs=0.01)
    assert length == pytest.approx(2.4, abs=0.01)
    assert still_share(1.0, 10) < 0.15
    assert still_share(4.0, 10) > 0.15


def test_watermark_heuristic_flags_one_static_corner_only():
    assert static_corners_look_like_watermark([True, False, False, False], center_moves=True)
    assert not static_corners_look_like_watermark([True, True, True, True], center_moves=True)
    assert not static_corners_look_like_watermark([True, False, False, False], center_moves=False)
    rejected, reason = gate_source(
        width=1080,
        height=1920,
        duration=5,
        url="https://cdn.example/preview-watermark.mp4",
    )
    assert not rejected
    assert "watermark" in reason


def test_pexels_keeps_vertical_video_and_drops_stills_and_watermarks():
    payload = {
        "videos": [
            {
                "id": 11,
                "duration": 12,
                "url": "https://www.pexels.com/video/server-room-11/",
                "user": {"name": "Ada"},
                "video_files": [
                    {"file_type": "video/mp4", "width": 640, "height": 360, "link": "https://cdn.example/small.mp4"},
                    {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://cdn.example/vert.mp4"},
                ],
            },
            {
                "id": 12,
                "duration": 8,
                "url": "https://www.pexels.com/video/watermark-preview/",
                "user": {"name": "Bob"},
                "video_files": [
                    {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://cdn.example/wm.mp4"},
                ],
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "pexels-test"
        assert "image" not in str(request.url)
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        found = search_pexels("server room racks", "pexels-test", client)
    assert len(found) == 1
    assert found[0].stable_id == "pexels:11"
    assert found[0].width == 1080
    assert found[0].height == 1920
    assert found[0].source == "pexels"
    assert "Ada" in found[0].credit
    assert "Pexels" in found[0].credit


def test_pixabay_skips_unrelated_and_sub_720_renditions():
    payload = {
        "hits": [
            {
                "id": 9,
                "user": "Sam",
                "pageURL": "https://pixabay.com/videos/cat-9/",
                "tags": "cat, cute, animal",
                "duration": 10,
                "videos": {"large": {"url": "https://cdn.example/cat.mp4", "width": 1080, "height": 1920}},
            },
            {
                "id": 4,
                "user": "Riley",
                "pageURL": "https://pixabay.com/videos/server-4/",
                "tags": "server, room, rack",
                "duration": 9,
                "videos": {
                    "tiny": {"url": "https://cdn.example/tiny.mp4", "width": 640, "height": 360},
                    "large": {"url": "https://cdn.example/server.mp4", "width": 1080, "height": 1920},
                },
            },
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["key"] == "pixabay-test"
        assert request.url.params["video_type"] == "film"
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        found = search_pixabay("server room", "pixabay-test", client)
    assert [item.stable_id for item in found] == ["pixabay:4"]
    assert found[0].download_url.endswith("server.mp4")


def test_grok_request_is_photoreal_vertical_and_silent():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content.decode())
            seen["body"] = body
            assert request.headers["Authorization"] == "Bearer xai-test"
            return httpx.Response(200, json={"request_id": "req-1"})
        if request.url.path.endswith("/req-1"):
            return httpx.Response(
                200,
                json={"status": "done", "video": {"url": "https://vidgen.x.ai/clip.mp4", "duration": 4}},
            )
        return httpx.Response(404)

    prompt = photoreal_prompt("a server fan spinning in a dim rack")
    assert "35mm" in prompt
    assert "No text" in prompt
    assert "no logos" in prompt.lower()
    assert "No faces of real people" in prompt
    assert "handheld" in prompt.lower()
    with httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.x.ai",
        headers={"Authorization": "Bearer xai-test"},
    ) as client:
        request_id = request_video(client, prompt, model="grok-imagine-video-1.5", duration=4)
        url = poll_video(client, request_id, timeout=5, interval=0, sleep=lambda _seconds: None)
    assert request_id == "req-1"
    assert url.endswith("clip.mp4")
    assert seen["body"]["model"] == "grok-imagine-video-1.5"
    assert seen["body"]["aspect_ratio"] == "9:16"
    assert seen["body"]["resolution"] == "720p"
    assert seen["body"]["generate_audio"] is False
    assert seen["body"]["duration"] == 4


def test_used_clip_cache_blocks_a_week_and_budget_stops_at_the_cap(tmp_path):
    store = UsedClipStore(tmp_path / "used.json", days=7)
    today = date(2026, 10, 22)
    assert not store.seen("pexels:1", today)
    store.mark("pexels:1", today, "story-a")
    assert store.seen("pexels:1", today)
    assert store.seen("pexels:1", date(2026, 10, 28))
    assert not store.seen("pexels:1", date(2026, 10, 29))
    budget = AiClipBudget(tmp_path / "budget.json", "2026-10-22", 2)
    assert budget.remaining() == 2
    budget.consume()
    budget.consume()
    assert budget.remaining() == 0
    reloaded = AiClipBudget(tmp_path / "budget.json", "2026-10-22", 2)
    assert reloaded.remaining() == 0
    assert AiClipBudget(tmp_path / "budget.json", "2026-10-23", 2).remaining() == 2


def test_no_footage_keys_fails_the_short_instead_of_a_slideshow(tmp_path, monkeypatch: pytest.MonkeyPatch):
    for name in ("PEXELS_API_KEY", "PIXABAY_API_KEY", "XAI_API_KEY", "DAILY_SHORTS"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.load(tmp_path)
    settings.data_dir = tmp_path / "data"
    words = estimate_word_timings("NVIDIA shipped a quieter fan for the data center today", 6)
    with pytest.raises(FootageRejected) as exc:
        assemble_footage(
            settings,
            script="NVIDIA shipped a quieter fan for the data center today",
            words=words,
            voice_seconds=6,
            story_title="NVIDIA quieter data center fan",
            story_id="story-1",
            extra_queries=["server room"],
            when=datetime(2026, 10, 22, tzinfo=timezone.utc),
        )
    assert "slideshow" in exc.value.reason.lower()
    assert "PEXELS_API_KEY" in exc.value.reason
    assert "PIXABAY_API_KEY" in exc.value.reason
    assert "XAI_API_KEY" in exc.value.reason
    assert exc.value.retryable is True


def test_spent_grok_budget_is_named_in_the_rejection(tmp_path, monkeypatch: pytest.MonkeyPatch):
    for name in ("PEXELS_API_KEY", "PIXABAY_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("MAX_AI_CLIPS_PER_DAY", "1")
    settings = Settings.load(tmp_path)
    settings.data_dir = tmp_path / "data"
    settings.data_dir.mkdir()
    (settings.data_dir / "ai_clip_budget.json").write_text(
        '{"date": "2026-10-22", "count": 1}\n',
        encoding="utf-8",
    )
    words = estimate_word_timings("A lab tested a new chip today", 4)
    with pytest.raises(FootageRejected) as exc:
        assemble_footage(
            settings,
            script="A lab tested a new chip today",
            words=words,
            voice_seconds=4,
            story_title="new chip",
            story_id="story-2",
            extra_queries=[],
            when=datetime(2026, 10, 22, tzinfo=timezone.utc),
        )
    assert "MAX_AI_CLIPS_PER_DAY" in exc.value.reason
    assert exc.value.retryable is True


def test_cover_filter_does_not_pan_or_zoom():
    filt = cover_filter(1080, 1920)
    assert "zoompan" not in filt
    assert "t/" not in filt
    assert "1080" in filt and "1920" in filt


_PEXELS_HIT = {
    "videos": [
        {
            "id": 11,
            "duration": 12,
            "url": "https://www.pexels.com/video/server-room-11/",
            "user": {"name": "Ada"},
            "video_files": [
                {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://cdn.example/vert.mp4"},
            ],
        }
    ]
}


def _when():
    return datetime(2026, 10, 22, tzinfo=timezone.utc)


def _words(seconds: float = 8.0):
    script = "one two three four five six seven eight nine ten"
    return script, estimate_word_timings(script, seconds)


def test_pexels_retries_rate_limits_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("news_youtube_bot.footage._sleep", lambda _seconds: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=_PEXELS_HIT)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        found = search_pexels("server room", "pexels-test", client)
    assert calls["n"] == 3
    assert [item.stable_id for item in found] == ["pexels:11"]


def test_pexels_rate_limit_still_raises_after_retries(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("news_youtube_bot.footage._sleep", lambda _seconds: None)
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "rate limit"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(StockRateLimit) as exc:
            search_pexels("server room", "pexels-test", client)
    assert calls["n"] == 4
    assert exc.value.provider == "pexels"


def test_stock_search_results_are_cached(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-test")
    settings = Settings.load(tmp_path)
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_PEXELS_HIT)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = search_stock(settings, "server room", client)
        second = search_stock(settings, "server room", client)
    assert calls["n"] == 1
    assert [item.stable_id for item in first] == ["pexels:11"]
    assert [item.stable_id for item in second] == ["pexels:11"]


def test_rate_limit_rejects_the_short_without_calling_grok(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("MAX_AI_CLIPS_PER_DAY", "10")
    settings = Settings.load(tmp_path)
    settings.data_dir = tmp_path / "data"
    called = {"n": 0}

    def search(_settings, _query, client=None):
        raise StockRateLimit("pexels", "server room")

    def generate(*_args, **_kwargs):
        called["n"] += 1
        raise AssertionError("Grok must not run after a stock rate limit")

    monkeypatch.setattr("news_youtube_bot.footage.search_stock", search)
    monkeypatch.setattr("news_youtube_bot.footage._generate", generate)
    script, words = _words()
    with pytest.raises(FootageRejected) as exc:
        assemble_footage(
            settings,
            script=script,
            words=words,
            voice_seconds=8,
            story_title="server room",
            story_id="rate-1",
            extra_queries=[],
            when=_when(),
        )
    assert called["n"] == 0
    assert exc.value.retryable is True
    assert "rate-limited" in exc.value.reason
    assert "Grok" in exc.value.reason
    assert AiClipBudget(settings.data_dir / "ai_clip_budget.json", "2026-10-22", 10).count == 0


def test_short_is_rejected_before_any_grok_spend_when_the_cap_cannot_cover_it(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("MAX_AI_CLIPS_PER_DAY", "10")
    monkeypatch.setenv("MAX_AI_CLIPS_PER_SHORT", "1")
    settings = Settings.load(tmp_path)
    settings.data_dir = tmp_path / "data"
    script, words = _words()
    assert len(plan_beats(words, 8)) > 1
    called = {"n": 0}

    def generate(*_args, **_kwargs):
        called["n"] += 1
        raise AssertionError("budget check should happen before generation")

    monkeypatch.setattr("news_youtube_bot.footage._generate", generate)
    with pytest.raises(FootageRejected) as exc:
        assemble_footage(
            settings,
            script=script,
            words=words,
            voice_seconds=8,
            story_title="chip lab",
            story_id="cap-1",
            extra_queries=[],
            when=_when(),
        )
    assert called["n"] == 0
    assert "Nothing was requested" in exc.value.reason
    assert "MAX_AI_CLIPS_PER_SHORT=1" in exc.value.reason
    assert exc.value.retryable is True
    assert AiClipBudget(settings.data_dir / "ai_clip_budget.json", "2026-10-22", 10).count == 0


def test_grok_request_counts_as_soon_as_it_is_accepted_even_if_it_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    settings = Settings.load(tmp_path)
    budget = AiClipBudget(tmp_path / "ai_clip_budget.json", "2026-10-22", 10)
    memory = UsedClipStore(tmp_path / "used.json")

    def boom(*_args, on_accepted=None, **_kwargs):
        assert on_accepted is not None
        on_accepted("req-timeout")
        raise RuntimeError("timed out")

    monkeypatch.setattr("news_youtube_bot.footage.generate_video_url", boom)
    result = _generate(settings, "a spinning server fan", tmp_path, budget, set(), memory, date(2026, 10, 22))
    assert result is None
    assert budget.count == 1
    assert AiClipBudget(tmp_path / "ai_clip_budget.json", "2026-10-22", 10).count == 1

    def refused(*_args, on_accepted=None, **_kwargs):
        raise RuntimeError("401")

    fresh = AiClipBudget(tmp_path / "fresh.json", "2026-10-22", 10)
    monkeypatch.setattr("news_youtube_bot.footage.generate_video_url", refused)
    assert _generate(settings, "another fan", tmp_path, fresh, set(), memory, date(2026, 10, 22)) is None
    assert fresh.count == 0


def test_failed_poll_is_charged_only_after_accept():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"request_id": "req-9"})
        return httpx.Response(200, json={"status": "failed", "error": "nope"})

    seen: dict[str, str] = {}
    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.x.ai") as client:
        with pytest.raises(RuntimeError):
            generate_video_url(
                "xai-test",
                "prompt",
                client=client,
                on_accepted=lambda request_id: seen.setdefault("id", request_id),
            )
    assert seen["id"] == "req-9"


def _clip(stable_id: str) -> Candidate:
    return Candidate(
        download_url=f"https://cdn.example/{stable_id}.mp4",
        stable_id=stable_id,
        credit=f"Video {stable_id}",
        source="pexels",
        width=1080,
        height=1920,
        duration=8,
    )


def test_stock_clips_are_marked_used_only_when_the_short_is_accepted(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PEXELS_API_KEY", "pexels-test")
    settings = Settings.load(tmp_path)
    settings.data_dir = tmp_path / "data"
    monkeypatch.setattr("news_youtube_bot.footage._accept", lambda *_args, **_kwargs: tmp_path / "clip.mp4")
    monkeypatch.setattr("news_youtube_bot.footage.window_for", lambda _path, want: (0.2, want))
    script, words = _words()
    beats = plan_beats(words, 8)

    handed = {"n": 0}

    def one_then_empty(_settings, _query, client=None):
        handed["n"] += 1
        if handed["n"] == 1:
            return [_clip("pexels:only")]
        return []

    monkeypatch.setattr("news_youtube_bot.footage.search_stock", one_then_empty)
    with pytest.raises(FootageRejected):
        assemble_footage(
            settings,
            script=script,
            words=words,
            voice_seconds=8,
            story_title="partial",
            story_id="partial-1",
            extra_queries=[],
            when=_when(),
        )
    assert not UsedClipStore(settings.data_dir / "used_clips.json").seen("pexels:only", date(2026, 10, 22))

    seq = iter(range(1, 20))

    def enough(_settings, _query, client=None):
        return [_clip(f"pexels:{next(seq)}")]

    monkeypatch.setattr("news_youtube_bot.footage.search_stock", enough)
    shots = assemble_footage(
        settings,
        script=script,
        words=words,
        voice_seconds=8,
        story_title="full",
        story_id="full-1",
        extra_queries=[],
        when=_when(),
    )
    assert len(shots) == len(beats)
    store = UsedClipStore(settings.data_dir / "used_clips.json")
    for shot in shots:
        assert store.seen(shot.stable_id, date(2026, 10, 22))
    assert not store.seen("pexels:only", date(2026, 10, 22))
