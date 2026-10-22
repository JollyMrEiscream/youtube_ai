from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "daily_shorts.yml",
    ROOT / ".github" / "workflows" / "upload_approved.yml",
)


def test_workflows_queue_together_and_save_state_when_they_fail():
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        assert data["concurrency"]["group"] == "youtube-ai-shorts"
        assert data["concurrency"]["cancel-in-progress"] is False
        steps = next(iter(data["jobs"].values()))["steps"]
        restores = [step for step in steps if step.get("uses", "").startswith("actions/cache/restore@")]
        saves = [step for step in steps if step.get("uses", "").startswith("actions/cache/save@")]
        assert len(restores) == 1
        assert len(saves) == 1
        assert saves[0].get("if") == "always()"
        saved = saves[0]["with"]["path"]
        assert "data" in saved
        assert "output/review" in saved
        assert "actions/cache/save@v4" in text
        assert "actions/cache@v4\n" not in text
