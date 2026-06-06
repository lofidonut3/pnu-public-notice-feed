from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

ARCHIVE_VERSION = "0.3"
EVENT_STREAM_VERSION = "0.3"
RECENT_EVENT_LIMIT = 1000
TIMEZONE = "Asia/Seoul"


def write_archive_outputs(output_dir: Path, feed: dict, pretty: bool) -> tuple[dict, dict]:
    archive_dir = output_dir / "archive"
    archive_docs = read_archive_docs(archive_dir)
    previous_index = read_json_if_exists(output_dir / "index.json")

    next_archive_docs, archive_index = build_archive_documents(
        feed=feed,
        existing_archive_docs=archive_docs,
        previous_index=previous_index.get("archives") if previous_index else None,
        pretty=pretty,
    )
    recent_events = build_recent_events_document(next_archive_docs, archive_index)

    cleanup_legacy_archive_outputs(archive_dir)
    for month, doc in next_archive_docs.items():
        write_json_if_changed(archive_dir / f"{month}.json", doc, pretty)
    write_json_if_changed(output_dir / "events.json", recent_events, pretty)
    return archive_index, recent_events


def archive_outputs_exist(output_dir: Path) -> bool:
    index = read_json_if_exists(output_dir / "index.json")
    if not index or not (output_dir / "events.json").exists():
        return False
    for month in index.get("archives", {}).get("months", []):
        url = month.get("url")
        if url and not (output_dir / url.removeprefix("./")).exists():
            return False
    return True


def build_archive_documents(
    feed: dict,
    existing_archive_docs: dict[str, dict] | None = None,
    previous_index: dict | None = None,
    pretty: bool = False,
) -> tuple[dict[str, dict], dict]:
    generated_at = str(feed.get("_pnu", {}).get("generated_at"))
    baseline_source_ids = {
        str(source_id)
        for source_id in feed.get("_pnu", {}).get("baseline_source_ids", [])
    }
    archive_docs = copy.deepcopy(existing_archive_docs or {})
    archived_items = archived_items_by_id(archive_docs)
    touched_months: set[str] = set()
    baseline_item_ids: set[str] = set()

    for current_item in feed.get("items", []):
        item = normalize_archive_input_item(current_item)
        item_id = str(item["id"])
        current_hash = item_content_hash(item)
        seen_at = str(item.get("_pnu", {}).get("fetched_at") or generated_at)
        is_baseline_item = item_source_id(item) in baseline_source_ids
        if is_baseline_item:
            baseline_item_ids = {*baseline_item_ids, item_id}
        existing = archived_items.get(item_id)

        if existing is None:
            item_month = archive_month_for_item(item, seen_at)
            archived_item = archive_item(
                item,
                archive_month=item_month,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
                last_changed_at=seen_at,
                baseline_imported_at=seen_at if is_baseline_item else None,
            )
            archive_docs = upsert_archive_item(archive_docs, item_month, archived_item)
            touched_months = {
                *touched_months,
                item_month,
            }
            if not is_baseline_item:
                archive_docs = add_event(
                    archive_docs,
                    event_type="added",
                    item=archived_item,
                    item_month=item_month,
                    event_time=seen_at,
                    previous_content_hash=None,
                )
                touched_months = {
                    *touched_months,
                    month_from_timestamp(seen_at),
                }
            continue

        existing_month, existing_item = existing
        previous_hash = item_content_hash(existing_item)
        if previous_hash == current_hash:
            existing_archive = existing_item.get("_archive", {})
            archived_item = archive_item(
                item,
                archive_month=existing_month,
                first_seen_at=str(existing_archive.get("first_seen_at") or seen_at),
                last_seen_at=str(existing_archive.get("last_seen_at") or seen_at),
                last_changed_at=str(
                    existing_archive.get("last_changed_at")
                    or existing_archive.get("first_seen_at")
                    or seen_at
                ),
                baseline_imported_at=existing_archive.get("baseline_imported_at"),
            )
            if archive_metadata_core(existing_item) != archive_metadata_core(archived_item):
                archive_docs = upsert_archive_item(
                    archive_docs,
                    existing_month,
                    archived_item,
                )
                touched_months = {
                    *touched_months,
                    existing_month,
                }
            continue

        existing_archive = existing_item.get("_archive", {})
        first_seen_at = str(existing_archive.get("first_seen_at") or seen_at)
        archived_item = archive_item(
            item,
            archive_month=existing_month,
            first_seen_at=first_seen_at,
            last_seen_at=generated_at,
            last_changed_at=generated_at,
            baseline_imported_at=existing_archive.get("baseline_imported_at"),
        )
        archive_docs = upsert_archive_item(archive_docs, existing_month, archived_item)
        archive_docs = add_event(
            archive_docs,
            event_type="updated",
            item=archived_item,
            item_month=existing_month,
            event_time=generated_at,
            previous_content_hash=previous_hash,
        )
        touched_months = {
            *touched_months,
            existing_month,
            month_from_timestamp(generated_at),
        }

    if baseline_item_ids:
        baseline_event_months = months_with_events_for_items(
            archive_docs,
            baseline_item_ids,
        )
        archive_docs = remove_events_for_items(archive_docs, baseline_item_ids)
        touched_months = {
            *touched_months,
            *baseline_event_months,
        }

    archive_docs = rebuild_archive_docs(
        archive_docs,
        {
            *touched_months,
            *months_needing_rebuild(archive_docs),
        },
        generated_at,
    )
    archive_index = build_archive_index(
        archive_docs,
        previous_index=previous_index,
        last_modified_at=generated_at,
        pretty=pretty,
    )
    return archive_docs, archive_index


def build_recent_events_document(
    archive_docs: dict[str, dict],
    archive_index: dict,
    event_limit: int = RECENT_EVENT_LIMIT,
) -> dict:
    all_events = sorted(
        [
            compact_event(event)
            for doc in archive_docs.values()
            for event in doc.get("events", [])
        ],
        key=event_sort_key,
    )
    limited_events = all_events[-event_limit:]
    oldest_event = limited_events[0] if limited_events else None
    latest_event = limited_events[-1] if limited_events else None
    return {
        "schema_version": "0.1",
        "event_stream_version": EVENT_STREAM_VERSION,
        "generated_at": archive_index.get("last_modified_at"),
        "timezone": TIMEZONE,
        "event_count": len(limited_events),
        "total_event_count": len(all_events),
        "event_limit": event_limit,
        "latest_event_id": archive_index.get("latest_event_id"),
        "oldest_event_id": oldest_event.get("event_id") if oldest_event else None,
        "oldest_seen_at": oldest_event.get("seen_at") if oldest_event else None,
        "latest_seen_at": latest_event.get("seen_at") if latest_event else None,
        "is_truncated": len(all_events) > len(limited_events),
        "index_url": "./index.json",
        "archive_url_pattern": "./archive/{YYYY-MM}.json",
        "events": limited_events,
    }


def read_archive_docs(archive_dir: Path) -> dict[str, dict]:
    direct_docs = read_direct_archive_docs(archive_dir)
    if direct_docs:
        return direct_docs
    return migrate_split_archive_docs(
        read_month_docs(archive_dir / "notices"),
        read_month_docs(archive_dir / "events"),
    )


def read_direct_archive_docs(archive_dir: Path) -> dict[str, dict]:
    if not archive_dir.exists():
        return {}
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(archive_dir.glob("????-??.json"))
    }


def migrate_split_archive_docs(
    notice_docs: dict[str, dict],
    event_docs: dict[str, dict],
) -> dict[str, dict]:
    archive_docs = {
        month: empty_archive_doc(month)
        for month in sorted(set(notice_docs) | set(event_docs))
    }
    for month, doc in notice_docs.items():
        archive_docs = {
            **archive_docs,
            month: {
                **archive_docs.get(month, empty_archive_doc(month)),
                "last_modified_at": doc.get("last_modified_at"),
                "items": copy.deepcopy(doc.get("items", [])),
            },
        }

    archived_items = archived_items_by_id(archive_docs)
    for month, doc in event_docs.items():
        events = [
            migrate_split_event(event, archived_items)
            for event in doc.get("events", [])
        ]
        current = archive_docs.get(month, empty_archive_doc(month))
        archive_docs = {
            **archive_docs,
            month: {
                **current,
                "last_modified_at": max_known(
                    current.get("last_modified_at"),
                    doc.get("last_modified_at"),
                ),
                "events": events,
            },
        }

    return rebuild_archive_docs(archive_docs, set(archive_docs), None)


def migrate_split_event(
    event: dict,
    archived_items: dict[str, tuple[str, dict]],
) -> dict:
    notice_id = str(event.get("archive_notice_id") or event.get("notice_id"))
    item_month, item = archived_items.get(notice_id, (archive_month_from_event(event), {}))
    return compact_event({
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "notice_id": event.get("notice_id"),
        "source_id": event.get("source_id"),
        "seen_at": event.get("seen_at"),
        "published_at": event.get("published_at"),
        "title": event.get("title"),
        "url": event.get("url"),
        "content_hash": event.get("content_hash"),
        "previous_content_hash": event.get("previous_content_hash"),
        "archive_file": f"./archive/{item_month}.json",
        "archive_item_id": notice_id,
        "item": event_item_snapshot(item) if item else None,
    })


def archive_month_from_event(event: dict) -> str:
    value = str(event.get("archive_notice_file") or "")
    if value.endswith(".json") and len(value) >= 12:
        return Path(value).stem
    published_at = event.get("published_at")
    if isinstance(published_at, str) and len(published_at) >= 7:
        return published_at[:7]
    seen_at = str(event.get("seen_at") or "")
    return seen_at[:7]


def read_month_docs(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {
        file_path.stem: json.loads(file_path.read_text(encoding="utf-8"))
        for file_path in sorted(path.glob("*.json"))
    }


def read_json_if_exists(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def archived_items_by_id(archive_docs: dict[str, dict]) -> dict[str, tuple[str, dict]]:
    result: dict[str, tuple[str, dict]] = {}
    for month, doc in archive_docs.items():
        for item in doc.get("items", []):
            item_id = item.get("id")
            if item_id:
                result = {**result, str(item_id): (month, item)}
    return result


def normalize_archive_input_item(item: dict) -> dict:
    archive_item_copy = {
        key: copy.deepcopy(value)
        for key, value in item.items()
        if key != "_archive"
    }
    return {
        **archive_item_copy,
        "_pnu": copy.deepcopy(item.get("_pnu", {})),
    }


def archive_month_for_item(item: dict, first_seen_at: str) -> str:
    pnu = item.get("_pnu", {})
    published_at = pnu.get("published_at") or item.get("date_published")
    if isinstance(published_at, str) and len(published_at) >= 7:
        return published_at[:7]
    return month_from_timestamp(first_seen_at)


def month_from_timestamp(value: str | None) -> str:
    return str(value or "")[:7]


def archive_item(
    item: dict,
    archive_month: str,
    first_seen_at: str,
    last_seen_at: str,
    last_changed_at: str,
    baseline_imported_at: str | None = None,
) -> dict:
    normalized = normalize_archive_input_item(item)
    archive_metadata = {
        "archive_month": archive_month,
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "last_changed_at": last_changed_at,
        "current_content_hash": item_content_hash(normalized),
    }
    if baseline_imported_at:
        archive_metadata = {
            **archive_metadata,
            "baseline_imported_at": baseline_imported_at,
        }
    return {
        **normalized,
        "_archive": archive_metadata,
    }


def upsert_archive_item(
    archive_docs: dict[str, dict],
    month: str,
    item: dict,
) -> dict[str, dict]:
    doc = archive_docs.get(month) or empty_archive_doc(month)
    items = {
        str(existing["id"]): existing
        for existing in doc.get("items", [])
        if existing.get("id")
    }
    items = {**items, str(item["id"]): item}
    return {
        **archive_docs,
        month: {
            **doc,
            "items": sorted(items.values(), key=notice_sort_key, reverse=True),
        },
    }


def remove_events_for_items(
    archive_docs: dict[str, dict],
    item_ids: set[str],
) -> dict[str, dict]:
    return {
        month: {
            **doc,
            "events": [
                event
                for event in doc.get("events", [])
                if str(event.get("archive_item_id") or event.get("notice_id")) not in item_ids
            ],
        }
        for month, doc in archive_docs.items()
    }


def months_with_events_for_items(
    archive_docs: dict[str, dict],
    item_ids: set[str],
) -> set[str]:
    return {
        month
        for month, doc in archive_docs.items()
        for event in doc.get("events", [])
        if str(event.get("archive_item_id") or event.get("notice_id")) in item_ids
    }


def add_event(
    archive_docs: dict[str, dict],
    event_type: str,
    item: dict,
    item_month: str,
    event_time: str,
    previous_content_hash: str | None,
) -> dict[str, dict]:
    event_month = month_from_timestamp(event_time)
    doc = archive_docs.get(event_month) or empty_archive_doc(event_month)
    event = event_for_item(
        item=item,
        event_type=event_type,
        event_time=event_time,
        item_month=item_month,
        previous_content_hash=previous_content_hash,
    )
    events = {
        str(existing["event_id"]): existing
        for existing in doc.get("events", [])
        if existing.get("event_id")
    }
    events = {**events, str(event["event_id"]): event}
    return {
        **archive_docs,
        event_month: {
            **doc,
            "events": sorted(events.values(), key=event_sort_key),
        },
    }


def event_for_item(
    item: dict,
    event_type: str,
    event_time: str,
    item_month: str,
    previous_content_hash: str | None,
) -> dict:
    pnu = item.get("_pnu", {})
    notice_id = str(item["id"])
    content_hash = item_content_hash(item)
    return {
        "event_id": event_id(
            event_time=event_time,
            event_type=event_type,
            notice_id=notice_id,
            content_hash=content_hash,
        ),
        "event_type": event_type,
        "notice_id": notice_id,
        "source_id": pnu.get("source_id"),
        "seen_at": event_time,
        "published_at": pnu.get("published_at"),
        "title": item.get("title"),
        "url": item.get("url"),
        "source_name": pnu.get("source_name"),
        "source_category": pnu.get("source_category"),
        "source_tags": pnu.get("source_tags") or pnu.get("tags") or [],
        "topics": pnu.get("topics") or [],
        "same_notice_group_id": pnu.get("same_notice_group_id"),
        "canonical_item_id": pnu.get("canonical_item_id") or notice_id,
        "is_canonical": pnu.get("is_canonical", True),
        "same_notice_source_ids": pnu.get("same_notice_source_ids") or [
            pnu.get("source_id")
        ],
        "content_hash": content_hash,
        "previous_content_hash": previous_content_hash,
        "archive_file": f"./archive/{item_month}.json",
        "archive_item_id": notice_id,
    }


def event_item_snapshot(item: dict) -> dict:
    return {
        key: copy.deepcopy(value)
        for key, value in item.items()
        if key != "_archive"
    }


def compact_event(event: dict) -> dict:
    item = event.get("item") or {}
    pnu = item.get("_pnu") or {}
    notice_id = str(event.get("notice_id") or item.get("id") or "")
    source_id = event.get("source_id") or pnu.get("source_id")
    return {
        "event_id": event.get("event_id"),
        "event_type": event.get("event_type"),
        "notice_id": notice_id,
        "source_id": source_id,
        "source_name": event.get("source_name") or pnu.get("source_name"),
        "source_category": event.get("source_category") or pnu.get("source_category"),
        "source_tags": event.get("source_tags") or pnu.get("source_tags") or pnu.get("tags") or [],
        "seen_at": event.get("seen_at"),
        "published_at": event.get("published_at") or pnu.get("published_at"),
        "title": event.get("title") or item.get("title"),
        "url": event.get("url") or item.get("url"),
        "topics": event.get("topics") or pnu.get("topics") or [],
        "same_notice_group_id": (
            event.get("same_notice_group_id")
            if "same_notice_group_id" in event
            else pnu.get("same_notice_group_id")
        ),
        "canonical_item_id": (
            event.get("canonical_item_id")
            or pnu.get("canonical_item_id")
            or notice_id
        ),
        "is_canonical": (
            event.get("is_canonical")
            if "is_canonical" in event
            else pnu.get("is_canonical", True)
        ),
        "same_notice_source_ids": (
            event.get("same_notice_source_ids")
            or pnu.get("same_notice_source_ids")
            or ([source_id] if source_id else [])
        ),
        "content_hash": event.get("content_hash"),
        "previous_content_hash": event.get("previous_content_hash"),
        "archive_file": event.get("archive_file"),
        "archive_item_id": event.get("archive_item_id") or notice_id,
    }


def event_id(
    event_time: str,
    event_type: str,
    notice_id: str,
    content_hash: str | None,
) -> str:
    return "|".join(
        [
            event_time,
            event_type,
            notice_id,
            (content_hash or "nohash")[:12],
        ]
    )


def rebuild_archive_docs(
    archive_docs: dict[str, dict],
    touched_months: set[str],
    last_modified_at: str | None,
) -> dict[str, dict]:
    return {
        month: rebuild_archive_doc(
            month,
            doc,
            last_modified_at if month in touched_months else doc.get("last_modified_at"),
        )
        for month, doc in archive_docs.items()
    }


def rebuild_archive_doc(
    month: str,
    doc: dict,
    last_modified_at: str | None,
) -> dict:
    items = sorted(doc.get("items", []), key=notice_sort_key, reverse=True)
    events = sorted(
        [compact_event(event) for event in doc.get("events", [])],
        key=event_sort_key,
    )
    return {
        "schema_version": "0.1",
        "archive_version": ARCHIVE_VERSION,
        "archive_type": "month",
        "archive_month": month,
        "last_modified_at": last_modified_at or doc.get("last_modified_at"),
        "timezone": TIMEZONE,
        "item_count": len(items),
        "event_count": len(events),
        "source_counts": source_counts(items),
        "items": items,
        "events": events,
    }


def build_archive_index(
    archive_docs: dict[str, dict],
    previous_index: dict | None,
    last_modified_at: str,
    pretty: bool,
) -> dict:
    month_entries = [
        month_index_entry(month, doc, pretty)
        for month, doc in sorted(archive_docs.items())
    ]
    all_events = [
        event
        for doc in archive_docs.values()
        for event in doc.get("events", [])
    ]
    latest_event = sorted(all_events, key=event_sort_key)[-1] if all_events else None
    previous_last_modified = (
        previous_index.get("last_modified_at")
        if previous_index
        else None
    )
    next_index = {
        "schema_version": "0.1",
        "archive_version": ARCHIVE_VERSION,
        "last_modified_at": previous_last_modified or last_modified_at,
        "timezone": TIMEZONE,
        "archive_url_pattern": "./archive/{YYYY-MM}.json",
        "month_count": len(month_entries),
        "notice_count": sum(entry["notice_count"] for entry in month_entries),
        "event_count": sum(entry["event_count"] for entry in month_entries),
        "latest_event_id": latest_event.get("event_id") if latest_event else None,
        "months": month_entries,
        "sources": source_index_entries(archive_docs),
    }
    if previous_index and archive_index_core(previous_index) == archive_index_core(next_index):
        return next_index
    return {
        **next_index,
        "last_modified_at": last_modified_at,
    }


def month_index_entry(month: str, doc: dict, pretty: bool) -> dict:
    file_meta = document_file_meta(doc, pretty)
    items = doc.get("items", [])
    events = doc.get("events", [])
    first_seen_values = [
        item.get("_archive", {}).get("first_seen_at")
        for item in items
        if item.get("_archive", {}).get("first_seen_at")
    ]
    last_seen_values = [
        item.get("_archive", {}).get("last_seen_at")
        for item in items
        if item.get("_archive", {}).get("last_seen_at")
    ]
    return {
        "month": month,
        "url": f"./archive/{month}.json",
        "notice_count": len(items),
        "event_count": len(events),
        "size_bytes": file_meta["size_bytes"],
        "sha256": file_meta["sha256"],
        "last_modified_at": doc.get("last_modified_at"),
        "first_seen_at": min(first_seen_values) if first_seen_values else None,
        "last_seen_at": max(last_seen_values) if last_seen_values else None,
    }


def source_index_entries(archive_docs: dict[str, dict]) -> list[dict]:
    source_data: dict[str, dict[str, Any]] = {}
    for doc in archive_docs.values():
        for item in doc.get("items", []):
            pnu = item.get("_pnu", {})
            source_id = pnu.get("source_id")
            if not source_id:
                continue
            archive = item.get("_archive", {})
            current = source_data.get(source_id, {})
            source_data = {
                **source_data,
                source_id: {
                    **current,
                    "id": source_id,
                    "notice_count": int(current.get("notice_count") or 0) + 1,
                    "event_count": int(current.get("event_count") or 0),
                    "first_seen_at": min_known(
                        current.get("first_seen_at"),
                        archive.get("first_seen_at"),
                    ),
                    "last_seen_at": max_known(
                        current.get("last_seen_at"),
                        archive.get("last_seen_at"),
                    ),
                },
            }
        for event in doc.get("events", []):
            source_id = event.get("source_id")
            if not source_id:
                continue
            current = source_data.get(source_id, {"id": source_id, "notice_count": 0})
            source_data = {
                **source_data,
                source_id: {
                    **current,
                    "event_count": int(current.get("event_count") or 0) + 1,
                    "first_seen_at": min_known(
                        current.get("first_seen_at"),
                        event.get("seen_at"),
                    ),
                    "last_seen_at": max_known(
                        current.get("last_seen_at"),
                        event.get("seen_at"),
                    ),
                },
            }
    return sorted(source_data.values(), key=lambda value: value["id"])


def archive_index_core(index: dict) -> dict:
    return {
        key: value
        for key, value in index.items()
        if key != "last_modified_at"
    }


def document_file_meta(doc: dict, pretty: bool) -> dict:
    payload = json_bytes(doc, pretty)
    return {
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def empty_archive_doc(month: str) -> dict:
    return {
        "schema_version": "0.1",
        "archive_version": ARCHIVE_VERSION,
        "archive_type": "month",
        "archive_month": month,
        "last_modified_at": None,
        "timezone": TIMEZONE,
        "item_count": 0,
        "event_count": 0,
        "source_counts": {},
        "items": [],
        "events": [],
    }


def source_counts(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        source_id = item.get("_pnu", {}).get("source_id")
        if source_id:
            counts = {**counts, source_id: counts.get(source_id, 0) + 1}
    return counts


def notice_sort_key(item: dict) -> tuple[str, str]:
    pnu = item.get("_pnu", {})
    archive = item.get("_archive", {})
    return (
        pnu.get("published_at") or archive.get("first_seen_at") or "",
        item.get("id") or "",
    )


def event_sort_key(event: dict) -> tuple[str, str]:
    return event.get("seen_at") or "", event.get("event_id") or ""


def item_content_hash(item: dict) -> str | None:
    pnu = item.get("_pnu", {})
    return pnu.get("content_hash") or item.get("content_hash")


def item_source_id(item: dict) -> str:
    return str(item.get("_pnu", {}).get("source_id") or item.get("source_id") or "")


def archive_metadata_core(item: dict) -> dict:
    pnu = item.get("_pnu", {})
    return {
        **{
            key: copy.deepcopy(value)
            for key, value in item.items()
            if key != "_archive" and key != "_pnu"
        },
        "_pnu": {
            key: copy.deepcopy(value)
            for key, value in pnu.items()
            if key not in {"fetched_at", "detail_checked_at"}
        },
    }


def months_needing_rebuild(archive_docs: dict[str, dict]) -> set[str]:
    return {
        month
        for month, doc in archive_docs.items()
        if doc.get("archive_version") != ARCHIVE_VERSION
        or any("item" in event for event in doc.get("events", []))
    }


def min_known(left: str | None, right: str | None) -> str | None:
    values = [value for value in [left, right] if value]
    return min(values) if values else None


def max_known(left: str | None, right: str | None) -> str | None:
    values = [value for value in [left, right] if value]
    return max(values) if values else None


def cleanup_legacy_archive_outputs(archive_dir: Path) -> None:
    for name in ["index.json", "events", "notices"]:
        path = archive_dir / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def write_json_if_changed(path: Path, value: dict, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json_text(value, pretty)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.write_text(content, encoding="utf-8")


def json_text(value: dict, pretty: bool) -> str:
    indent = 2 if pretty else None
    return json.dumps(value, ensure_ascii=False, indent=indent) + "\n"


def json_bytes(value: dict, pretty: bool) -> bytes:
    return json_text(value, pretty).encode("utf-8")
