from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from news_youtube_bot.captions import ass_timestamp, build_ass
from news_youtube_bot.config import Settings, active_llm_provider
from news_youtube_bot.pipeline import chat_client
from news_youtube_bot.dedupe import dedupe_items
from news_youtube_bot.clip_gate import crop_short_side, gate_source
from news_youtube_bot.footage import tags_match_query
from news_youtube_bot.keywords import queries_for_line
from news_youtube_bot.textutil import html_to_text, sentences
from news_youtube_bot.history import StoryHistory
from news_youtube_bot.models import NewsItem
from news_youtube_bot.publish import decide_upload
from news_youtube_bot.quota import QuotaState, plan_slots
from news_youtube_bot.rank_local import select_stories
from news_youtube_bot.review_queue import ReviewQueue
from news_youtube_bot.script_local import build_script_local
from news_youtube_bot.textutil import fit_spoken, word_count
from news_youtube_bot.tts_render import WordTiming, estimate_word_timings
from news_youtube_bot.variety import PROFILES, assign_profiles
from news_youtube_bot.window_filter import filter_by_window


def _item(title: str, link: str, feed: str, summary: str = "", hours_ago: float = 2, tech: bool = True) -> NewsItem:
    return NewsItem(
        id=link[-6:],
        title=title,
        link=link,
        summary=summary,
        published=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        feed_name=feed,
        raw={"tech": tech, "hn_score": 80},
    )


def test_quota_classic_1600_caps_at_six():
    slots, state = plan_slots(
        30,
        QuotaState(date="2026-10-22"),
        today="2026-10-22",
        max_uploads=6,
        unit_cost=1600,
        daily_units=10_000,
    )
    assert slots == 6
    assert state.uploads == 0


def test_quota_resets_on_a_new_pacific_day_and_stops_when_units_run_out():
    slots, state = plan_slots(
        4,
        QuotaState(date="2026-10-21", uploads=6, units=9600),
        today="2026-10-22",
        max_uploads=6,
        unit_cost=1600,
        daily_units=10_000,
    )
    assert slots == 4
    assert state.uploads == 0

    later, _ = plan_slots(
        3,
        QuotaState(date="2026-10-22", uploads=5, units=8000),
        today="2026-10-22",
        max_uploads=6,
        unit_cost=1600,
        daily_units=10_000,
    )
    assert later == 1


def test_upload_requires_explicit_opt_in():
    assert decide_upload(False, False, False) == "render_only"
    assert decide_upload(True, False, False) == "upload_approved_only"
    assert decide_upload(True, True, False) == "upload_without_review"
    assert decide_upload(True, True, True) == "render_only"


def test_profiles_for_a_day_do_not_repeat_back_to_back():
    picked = assign_profiles(5, "2026-10-22")
    assert len(picked) == 5
    assert len({profile.id for profile in picked}) == 5
    again = assign_profiles(30, "2026-10-22")
    assert all(again[i].id != again[i + 1].id for i in range(len(again) - 1))
    assert len(PROFILES) >= 8


def test_local_scripts_differ_and_stay_inside_a_short(tmp_path: Path):
    item = _item(
        "NVIDIA lists a cheaper desktop GPU after a retailer page goes live",
        "https://example.com/gpu",
        "The Verge",
        summary=(
            "The Verge reports that a retailer page briefly listed a new mid-range desktop graphics card overnight. "
            "The listing described 12 gigabytes of memory and did not confirm a street price. "
            "NVIDIA has not commented on whether the page was a mistake or a planned reveal."
        ),
    )
    scripts = [str(build_script_local(item, profile)["script"]) for profile in PROFILES[:5]]
    openings = [script.split(".")[0] for script in scripts]
    assert len(set(openings)) == 5
    for script in scripts:
        assert "NVIDIA" in script or "desktop" in script.lower()
        assert 40 <= word_count(script) <= 150
        assert "welcome back" not in script.lower()
        assert "let's dive in" not in script.lower()


def test_fit_spoken_keeps_the_ending():
    text = "Hook sentence here. " + " ".join(f"Middle fact number {i} is long enough to count." for i in range(12))
    text += " Final payoff stays. Source line stays."
    fitted = fit_spoken(text, max_words=40)
    assert word_count(fitted) <= 40
    assert "Source line stays." in fitted


def test_history_blocks_a_repeat_url_and_a_near_title(tmp_path: Path):
    history = StoryHistory(tmp_path / "seen.sqlite")
    first = _item("Acme ships a new battery", "https://example.com/a?utm_source=rss", "The Verge")
    history.mark_used(first)
    repeat = _item("Acme ships a new battery", "https://example.com/a", "TechCrunch")
    similar = _item("Acme ships a new battery today", "https://example.com/b", "Wired")
    fresh = _item("A lab demos a quieter server fan", "https://example.com/c", "Ars Technica")
    kept = history.filter_fresh([repeat, similar, fresh])
    assert [item.link for item in kept] == ["https://example.com/c"]
    history.close()


def test_dedupe_and_window_and_diverse_rank():
    now = datetime.now(timezone.utc)
    items = [
        _item("Chip A launches with a new cache", "https://example.com/1", "The Verge", hours_ago=1),
        _item("Chip A launches with a new cache", "https://example.com/1?utm_campaign=x", "TechCrunch", hours_ago=1),
        _item("Old phone rumor", "https://example.com/old", "Wired", hours_ago=80),
        _item("Google changes Android backup keys", "https://example.com/2", "Ars Technica", hours_ago=3),
        _item("A second Verge chip follow", "https://example.com/3", "The Verge", hours_ago=2),
        _item("Linux kernel gets a scheduler tweak", "https://example.com/4", "Hacker News", hours_ago=4),
    ]
    fresh = filter_by_window(items, 36 * 60, now=now)
    assert all(item.link != "https://example.com/old" for item in fresh)
    deduped = dedupe_items(fresh)
    assert len(deduped) == len(fresh) - 1
    picked = select_stories(deduped, 3, now=now)
    assert len(picked) == 3
    assert len({item.feed_name for item in picked}) == 3


def test_review_approve_and_reject(tmp_path: Path):
    queue = ReviewQueue(tmp_path / "review")
    folder = queue.prepare("20261022-01-abcdef")
    (folder / "short.mp4").write_bytes(b"not a real video")
    queue.write_meta(folder, {"id": "20261022-01-abcdef", "status": "pending", "title": "A chip", "created_at": "2026-10-22T00:00:00+00:00"})
    approved = queue.transition("20261022-01-abcdef", "approved")
    assert approved.status == "approved"
    assert (approved.directory / "short.mp4").is_file()
    rejected = queue.transition("20261022-01-abcdef", "rejected", queue_reason="thin script")
    assert rejected.meta["queue_reason"] == "thin script"
    assert queue.by_status("pending") == []


def test_captions_highlight_the_active_word():
    words = [
        WordTiming("Seen", 1.4, 1.7),
        WordTiming("this", 1.7, 2.0),
        WordTiming("yet?", 2.0, 2.3),
    ]
    profile = PROFILES[0]
    ass = build_ass(words, profile, Path("LiberationSans-Bold.ttf"), "Seen this yet", hook_seconds=1.2)
    assert "Dialogue: 1,0:00:00.00,0:00:01.20,Hook" in ass
    assert r"{\c" in ass
    assert ass_timestamp(1.25) == "0:00:01.25"
    estimated = estimate_word_timings("one two three", 3)
    assert len(estimated) == 3
    assert estimated[-1].end > estimated[0].end


def test_page_text_drops_json_ld_and_keeps_the_sentence():
    html = (
        "<html><head><script type='application/ld+json'>{\"@context\":\"https://schema.org\","
        "\"headline\":\"PHP bug\"}</script></head><body><p>A hacker attempted to exploit the PHP bug "
        "four days before a patch was released, according to Amazon Threat Intelligence.</p></body></html>"
    )
    text = html_to_text(html)
    assert "schema.org" not in text
    assert "PHP bug" in text or "hacker" in text.lower()
    found = sentences(html)
    assert found
    assert all("{" not in line for line in found)


def test_stock_tags_have_to_match_the_search():
    assert not tags_match_query("satellite dish", "Uranium Glazed Dish")
    assert not tags_match_query("city traffic night", "Hong Kong Police Clash with Protesters")
    assert tags_match_query("city traffic night", "City at night")
    assert tags_match_query("computer keyboard", "Dell laptop keyboard mouse")
    blocked, reason = gate_source(
        width=1080,
        height=1920,
        duration=8,
        title="Hong Kong Police Clash with Protesters",
        url="https://example.com/protest.mp4",
    )
    assert not blocked
    assert "off-limits" in reason
    low, low_reason = gate_source(width=640, height=360, duration=10, title="server room")
    assert not low
    assert "720" in low_reason
    assert crop_short_side(1080, 1920) >= 720


def test_line_queries_name_the_product_and_place():
    queries = queries_for_line("NVIDIA shipped a quieter fan for its data-center GPUs.")
    blob = " ".join(queries).lower()
    assert "nvidia" in blob
    assert "data center" in blob or "fan" in blob


def test_default_settings_are_five_vertical_shorts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for name in (
        "DAILY_SHORTS",
        "MAX_STORIES",
        "NEWS_WINDOW_MINUTES",
        "VIDEO_WIDTH",
        "VIDEO_HEIGHT",
        "TTS_ENGINE",
        "TTS_VOICE",
        "AUTO_UPLOAD",
        "SKIP_REVIEW",
        "DRY_RUN",
        "MAX_UPLOADS_PER_DAY",
        "UPLOAD_QUOTA_COST",
        "YOUTUBE_DAILY_QUOTA_UNITS",
        "LLM_PROVIDER",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "PEXELS_API_KEY",
        "PIXABAY_API_KEY",
        "XAI_API_KEY",
        "XAI_VIDEO_MODEL",
        "XAI_MODEL",
        "MAX_AI_CLIPS_PER_DAY",
        "MAX_AI_CLIPS_PER_SHORT",
        "CLIP_REUSE_DAYS",
        "CAPTURE_SOURCES",
        "STOCK_SEARCH_CACHE_HOURS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.load(tmp_path)
    assert settings.daily_shorts == 5
    assert settings.video_width == 1080
    assert settings.video_height == 1920
    assert settings.tts_engine == "edge"
    assert settings.auto_upload is False
    assert settings.skip_review is False
    assert settings.max_uploads_per_day == 6
    assert settings.upload_quota_cost == 1600
    assert settings.youtube_daily_quota_units == 10000
    assert settings.llm_provider == "local"
    assert settings.xai_api_key is None
    assert settings.xai_video_model == "grok-imagine-video-1.5"
    assert settings.xai_chat_model == "grok-4.7"
    assert settings.max_ai_clips_per_day == 10
    assert settings.max_ai_clips_per_short == 3
    assert settings.clip_reuse_days == 7
    assert settings.capture_sources is False


def test_xai_key_alone_selects_xai_for_scripts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for name in ("LLM_PROVIDER", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("XAI_MODEL", "grok-4.7")
    settings = Settings.load(tmp_path)
    assert settings.llm_provider == "xai"
    assert active_llm_provider(settings) == "xai"
    client = chat_client(settings)
    assert "api.x.ai" in str(client.base_url)
    assert str(client.base_url).rstrip("/").endswith("/v1")
