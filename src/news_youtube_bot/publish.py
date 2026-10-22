from __future__ import annotations

import logging
from datetime import datetime, timezone

from news_youtube_bot.config import Settings
from news_youtube_bot.quota import load_quota, pacific_today, plan_slots, save_quota
from news_youtube_bot.review_queue import ReviewQueue
from news_youtube_bot.youtube_upload import upload_video

logger = logging.getLogger(__name__)


def decide_upload(auto_upload: bool, skip_review: bool, dry_run: bool) -> str:
    """render_only, upload_approved_only, or upload_without_review."""
    if dry_run or not auto_upload:
        return "render_only"
    if skip_review:
        return "upload_without_review"
    return "upload_approved_only"


def is_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower().replace(" ", "").replace("_", "")
    return "quotaexceeded" in text or "uploadlimitexceeded" in text or "dailylimitexceeded" in text


def publish_approved(settings: Settings, queue: ReviewQueue | None = None) -> int:
    """Upload approved videos until the daily cap. Leave the rest approved for the next run."""
    if settings.dry_run:
        logger.info("DRY_RUN: not uploading")
        return 0
    review = queue or ReviewQueue(settings.output_dir / "review")
    approved = review.by_status("approved")
    if not approved:
        logger.info("No approved videos. Approve one with: python -m news_youtube_bot review approve ID")
        review.write_index()
        return 0
    if not settings.youtube_refresh_token:
        logger.error("YOUTUBE_REFRESH_TOKEN is missing. Approved videos stay in the queue.")
        return 1

    today = pacific_today()
    quota_path = settings.data_dir / "quota.json"
    state = load_quota(quota_path, today)
    slots, state = plan_slots(
        len(approved),
        state,
        today=today,
        max_uploads=settings.max_uploads_per_day,
        unit_cost=settings.upload_quota_cost,
        daily_units=settings.youtube_daily_quota_units,
    )
    logger.info(
        "Upload slots today: %d (used %d uploads / %d units, cap %d uploads or %d units at %d each)",
        slots,
        state.uploads,
        state.units,
        settings.max_uploads_per_day,
        settings.youtube_daily_quota_units,
        settings.upload_quota_cost,
    )
    if slots <= 0:
        for item in approved:
            review.transition(item.id, "approved", queue_reason="daily upload cap")
        review.write_index()
        logger.warning("%d approved video(s) stay queued until the quota day resets (midnight Pacific).", len(approved))
        return 0

    failures = 0
    for item in approved[:slots]:
        video = item.directory / "short.mp4"
        if not video.is_file():
            logger.error("Missing video for %s", item.id)
            failures += 1
            continue
        title = str(item.meta.get("title") or "Tech short")
        description = str(item.meta.get("description") or "")
        tags = item.meta.get("tags") if isinstance(item.meta.get("tags"), list) else []
        try:
            video_id = upload_video(settings, video, title, description, [str(tag) for tag in tags])
        except Exception as exc:
            if is_quota_error(exc):
                logger.error("YouTube quota rejected the upload. Leaving %s and the rest queued.", item.id)
                review.transition(item.id, "approved", queue_reason="youtube quota rejected the upload")
                for rest in approved[approved.index(item) + 1 : slots]:
                    review.transition(rest.id, "approved", queue_reason="youtube quota rejected the upload")
                break
            logger.exception("Upload failed for %s", item.id)
            failures += 1
            continue
        review.transition(
            item.id,
            "uploaded",
            youtube_id=video_id,
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            queue_reason="",
        )
        state.uploads += 1
        state.units += max(settings.upload_quota_cost, 0)
        save_quota(quota_path, state)
        logger.info("Uploaded %s as https://youtu.be/%s", item.id, video_id)

    for item in approved[slots:]:
        current = review.find(item.id)
        if current and current.status == "approved":
            review.transition(item.id, "approved", queue_reason="daily upload cap")
    if len(approved) > slots:
        logger.warning(
            "%d approved video(s) were not uploaded today. They stay approved and go out on the next upload run.",
            len(approved) - slots,
        )
    save_quota(quota_path, state)
    review.write_index()
    return 1 if failures else 0
