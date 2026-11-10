from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from .agent_views import TOPIC_IDS
from .io_utils import write_utf8_if_changed


def write_search_views(output_dir: Path, archive_docs: dict[str, dict], checked_at: str | None) -> None:
    search_dir = output_dir / "search"
    months = []
    for month, doc in sorted(archive_docs.items()):
        items = [search_item(item, month) for item in doc.get("items", [])]
        if not items:
            continue
        published = [item["published_at"] for item in items if item["published_at"]]
        observed = [
            item["first_seen_at"][:10]
            for item in items
            if not item["published_at"] and item["first_seen_at"]
        ]
        content = json.dumps(items, ensure_ascii=False, separators=(",", ":")) + "\n"
        data = content.encode("utf-8")
        write_utf8_if_changed(search_dir / f"{month}.json", content)
        months.append({
            "month": month,
            "published_from": min(published, default=None),
            "published_to": max(published, default=None),
            "undated_from": min(observed, default=None),
            "undated_to": max(observed, default=None),
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })

    catalog = {"schema_version": 1, "checked_at": checked_at, "topics": TOPIC_IDS, "months": months}
    write_utf8_if_changed(
        search_dir / "catalog.json",
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n",
    )


def search_views_exist(output_dir: Path) -> bool:
    search_dir = output_dir / "search"
    try:
        catalog = json.loads((search_dir / "catalog.json").read_text(encoding="utf-8"))
        return catalog["schema_version"] == 1 and all(
            (search_dir / f'{entry["month"]}.json').stat().st_size == entry["size_bytes"]
            for entry in catalog["months"]
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def search_item(item: dict, month: str) -> dict:
    pnu = item["_pnu"]
    snippet = pnu.get("snippet") or item.get("summary") or ""
    published_at = pnu.get("published_at")
    try:
        published = date.fromisoformat((published_at or "")[:10]).isoformat()
    except ValueError:
        published = None
    return {
        "id": item["id"],
        "archive_month": month,
        "title": item["title"],
        "url": item["url"],
        "source_id": pnu.get("source_id"),
        "source_name": pnu.get("source_name"),
        "topics": pnu.get("topics", []),
        "published_at": published,
        "first_seen_at": item.get("_archive", {}).get("first_seen_at"),
        "preview": " ".join(snippet.split())[:240] or None,
        "content_access": pnu.get("content_access"),
        "same_notice_group_id": pnu.get("same_notice_group_id"),
        "canonical_item_id": pnu.get("canonical_item_id"),
    }
