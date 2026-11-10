from __future__ import annotations

import json
from pathlib import Path

from .io_utils import write_utf8_if_changed
from .topics import SOURCE_CATEGORY_TOPICS, TAG_TOPICS, TITLE_TOPIC_PATTERNS


TOPIC_IDS = sorted(
    {topic for topics in SOURCE_CATEGORY_TOPICS.values() for topic in topics}
    | set(TAG_TOPICS.values())
    | {topic for topic, _ in TITLE_TOPIC_PATTERNS}
)
SCHEMA_VERSION = "0.1"
TOPIC_ITEM_LIMIT = 20
PREVIEW_LIMIT = 240


def agent_views_exist(output_dir: Path) -> bool:
    return (output_dir / "agent.json").is_file() and all(
        (output_dir / "topics" / f"{topic}.json").is_file() for topic in TOPIC_IDS
    )


def write_agent_views(output_dir: Path, items: list[dict], events: dict) -> None:
    by_topic: dict[str, dict[str, dict]] = {topic: {} for topic in TOPIC_IDS}
    for item in sorted(items, key=discovery_sort_key, reverse=True):
        pnu = item["_pnu"]
        group_id = pnu.get("same_notice_group_id") or item["id"]
        for topic in pnu.get("topics", []):
            if topic not in by_topic:
                continue
            group_items = by_topic[topic]
            previous = group_items.get(group_id)
            if previous is None or (
                pnu.get("is_canonical") and not previous["_pnu"].get("is_canonical")
            ):
                group_items[group_id] = item

    checked_at = events.get("checked_at")
    topics_dir = output_dir / "topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    for topic, groups in by_topic.items():
        selected = sorted(groups.values(), key=discovery_sort_key, reverse=True)
        preview_items = [preview_item(item) for item in selected[:TOPIC_ITEM_LIMIT]]
        write_compact_json(
            topics_dir / f"{topic}.json",
            {
                "schema_version": SCHEMA_VERSION,
                "topic": topic,
                "checked_at": checked_at,
                "coverage": "active_source_snapshot",
                "matching_count": len(selected),
                "item_limit": TOPIC_ITEM_LIMIT,
                "item_count": len(preview_items),
                "is_truncated": len(selected) > len(preview_items),
                "items": preview_items,
            },
        )

    write_compact_json(
        output_dir / "agent.json",
        {
            "schema_version": SCHEMA_VERSION,
            "checked_at": checked_at,
            "latest_event_id": events.get("latest_event_id"),
            "latest_seen_at": events.get("latest_seen_at"),
            "events_url": "./events.json",
            "index_url": "./index.json",
            "topics": [{"id": topic, "url": f"./topics/{topic}.json"} for topic in TOPIC_IDS],
        },
    )


def discovery_sort_key(item: dict) -> tuple[str, str]:
    pnu = item["_pnu"]
    date = pnu.get("published_at") or (pnu.get("fetched_at") or "")[:10]
    return date, item["id"]


def preview_item(item: dict) -> dict:
    pnu = item["_pnu"]
    snippet = pnu.get("snippet") or item.get("summary")
    access = pnu.get("content_access") or {}
    return {
        "id": item["id"],
        "title": item["title"],
        "url": item["url"],
        "source_id": pnu["source_id"],
        "source_name": pnu["source_name"],
        "published_at": pnu.get("published_at"),
        "preview": " ".join(snippet.split())[:PREVIEW_LIMIT] if snippet else None,
        **({"content_access": access} if access.get("availability") == "detail_unverified" else {}),
    }


def write_compact_json(path: Path, document: dict) -> None:
    write_utf8_if_changed(
        path, json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
