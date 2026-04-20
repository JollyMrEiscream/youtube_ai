from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from news_youtube_bot.config import Settings
from news_youtube_bot.pipeline import configure_logging, run


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description="RSS news digest to YouTube")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip YouTube upload (same as env DRY_RUN=1)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root (defaults to current working directory)",
    )
    args = parser.parse_args()

    root = (args.project_root or Path.cwd()).resolve()
    settings = Settings.load(root)
    if args.dry_run:
        settings = replace(settings, dry_run=True)

    code = run(root, settings)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
