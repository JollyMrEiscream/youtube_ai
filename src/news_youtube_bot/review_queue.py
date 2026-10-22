from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path


STATUSES = ("pending", "approved", "rejected", "uploaded")


@dataclass
class ReviewItem:
    id: str
    status: str
    directory: Path
    meta: dict


class ReviewQueue:
    def __init__(self, root: Path) -> None:
        self.root = root
        for status in STATUSES:
            (root / status).mkdir(parents=True, exist_ok=True)

    def directory_for(self, status: str, item_id: str) -> Path:
        return self.root / status / item_id

    def prepare(self, item_id: str) -> Path:
        folder = self.directory_for("pending", item_id)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def write_meta(self, folder: Path, meta: dict) -> None:
        (folder / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _read(self, folder: Path) -> ReviewItem | None:
        meta_path = folder / "meta.json"
        if not meta_path.is_file():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return ReviewItem(
            id=str(meta.get("id") or folder.name),
            status=folder.parent.name,
            directory=folder,
            meta=meta,
        )

    def all_items(self) -> list[ReviewItem]:
        items: list[ReviewItem] = []
        for status in STATUSES:
            root = self.root / status
            if not root.is_dir():
                continue
            for folder in sorted(path for path in root.iterdir() if path.is_dir()):
                item = self._read(folder)
                if item:
                    items.append(item)
        return items

    def by_status(self, status: str) -> list[ReviewItem]:
        items = [item for item in self.all_items() if item.status == status]
        items.sort(key=lambda item: str(item.meta.get("created_at") or item.id))
        return items

    def find(self, item_id: str) -> ReviewItem | None:
        for item in self.all_items():
            if item.id == item_id:
                return item
        return None

    def transition(self, item_id: str, status: str, **updates: object) -> ReviewItem:
        if status not in STATUSES:
            raise ValueError(status)
        item = self.find(item_id)
        if item is None:
            raise KeyError(item_id)
        dest = self.directory_for(status, item.id)
        if item.directory.resolve() != dest.resolve():
            if dest.exists():
                raise FileExistsError(dest)
            shutil.move(str(item.directory), str(dest))
        else:
            dest = item.directory
        meta = dict(item.meta)
        meta.update(updates)
        meta["id"] = item.id
        meta["status"] = status
        self.write_meta(dest, meta)
        loaded = self._read(dest)
        if loaded is None:
            raise RuntimeError(f"missing meta after moving {item_id}")
        return loaded

    def write_index(self) -> Path:
        lines = [
            "# Review queue",
            "",
            "Videos upload only after `review approve`. `SKIP_REVIEW=1` is the explicit opt-in to skip this list.",
            "",
            "| status | id | sec | profile | title |",
            "| --- | --- | ---: | --- | --- |",
        ]
        for item in self.all_items():
            title = str(item.meta.get("title") or "").replace("|", "/")
            duration = item.meta.get("duration_sec") or ""
            profile = item.meta.get("profile") or ""
            reason = item.meta.get("queue_reason") or ""
            suffix = f" ({reason})" if reason and item.status == "approved" else ""
            lines.append(f"| {item.status} | `{item.id}` | {duration} | {profile} | {title}{suffix} |")
        lines.append("")
        path = self.root / "INDEX.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path


def format_items(items: list[ReviewItem]) -> str:
    if not items:
        return "(empty)"
    rows = []
    for item in items:
        title = str(item.meta.get("title") or "")[:64]
        duration = float(item.meta.get("duration_sec") or 0)
        profile = str(item.meta.get("profile") or "")
        reason = item.meta.get("queue_reason") or ""
        extra = f"  queued: {reason}" if reason else ""
        rows.append(f"{item.status:9} {item.id:24} {duration:5.0f}s  {profile:12} {title}{extra}")
    return "\n".join(rows)
