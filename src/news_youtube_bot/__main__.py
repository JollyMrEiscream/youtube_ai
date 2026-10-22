from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from news_youtube_bot.config import Settings
from news_youtube_bot.pipeline import configure_logging, run
from news_youtube_bot.publish import publish_approved
from news_youtube_bot.review_queue import ReviewQueue, format_items


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Daily technology YouTube Shorts")
    parser.add_argument("--project-root", type=Path, default=None, help="Project root (default: working directory)")
    sub = parser.add_subparsers(dest="cmd")

    run_parser = sub.add_parser("run", help="Fetch news and render today's Shorts into the review queue")
    run_parser.add_argument("--count", type=int, default=None, help="How many Shorts to render (default: DAILY_SHORTS, 5)")
    run_parser.add_argument("--dry-run", action="store_true", help="Render only. Do not upload even if AUTO_UPLOAD=1")

    review = sub.add_parser("review", help="List, approve, or reject rendered Shorts")
    review.add_argument("action", choices=["list", "show", "approve", "reject"])
    review.add_argument("ids", nargs="*")
    review.add_argument("--reason", default="", help="Stored on a rejection")

    upload = sub.add_parser("upload", help="Upload approved Shorts up to the daily quota cap")
    upload.add_argument("--max", type=int, default=None, help="Override MAX_UPLOADS_PER_DAY for this run")
    return parser


def _root(args: argparse.Namespace) -> Path:
    return (args.project_root or Path.cwd()).resolve()


def _review_command(args: argparse.Namespace, settings: Settings) -> int:
    queue = ReviewQueue(settings.output_dir / "review")
    if args.action == "list":
        print(format_items(queue.all_items()))
        queue.write_index()
        return 0
    if args.action == "show":
        if not args.ids:
            print("Pass a review id. See: python -m news_youtube_bot review list", file=sys.stderr)
            return 1
        item = queue.find(args.ids[0])
        if item is None:
            print(f"No review item {args.ids[0]}", file=sys.stderr)
            return 1
        script = item.directory / "script.txt"
        print(f"id: {item.id}")
        print(f"status: {item.status}")
        print(f"title: {item.meta.get('title')}")
        print(f"profile: {item.meta.get('profile')}")
        print(f"duration: {item.meta.get('duration_sec')}s")
        print(f"video: {item.directory / 'short.mp4'}")
        print(f"source: {item.meta.get('story_url')}")
        if item.meta.get("queue_reason"):
            print(f"queue: {item.meta.get('queue_reason')}")
        if script.is_file():
            print("\n" + script.read_text(encoding="utf-8"))
        return 0
    if not args.ids:
        print("Pass one or more ids.", file=sys.stderr)
        return 1
    for item_id in args.ids:
        try:
            if args.action == "approve":
                queue.transition(item_id, "approved", queue_reason="")
                print(f"approved {item_id}")
            else:
                queue.transition(item_id, "rejected", queue_reason=args.reason or "rejected")
                print(f"rejected {item_id}")
        except KeyError:
            print(f"No review item {item_id}", file=sys.stderr)
            return 1
    queue.write_index()
    return 0


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    raw = list(sys.argv[1:] if argv is None else argv)
    if not raw:
        raw = ["run"]
    elif raw[0].startswith("-"):
        raw = ["run", *raw]
    args = _build_parser().parse_args(raw)
    root = _root(args)
    settings = Settings.load(root)

    if args.cmd == "review":
        raise SystemExit(_review_command(args, settings))
    if args.cmd == "upload":
        if args.max is not None:
            settings = replace(settings, max_uploads_per_day=args.max)
        raise SystemExit(publish_approved(settings))

    if args.count is not None:
        settings = replace(settings, daily_shorts=max(1, args.count))
    if args.dry_run:
        settings = replace(settings, dry_run=True, auto_upload=False)
    raise SystemExit(run(root, settings))


if __name__ == "__main__":
    main()
