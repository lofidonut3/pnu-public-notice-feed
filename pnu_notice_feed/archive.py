from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

ARCHIVE_VERSION = "0.1"
EVENT_STREAM_VERSION = "0.1"
RECENT_EVENT_LIMIT = 1000
TIMEZONE = "Asia/Seoul"


def write_archive_outputs(output_dir: Path, feed: dict, pretty: bool) -> None:
    archive_dir = output_dir / "archive"
    notice_docs = read_month_docs(archive_dir / "notices")
    event_docs = read_month_docs(archive_dir / "events")
    previous_index = read_json_if_exists(archive_dir / "index.json")

    next_notice_docs, next_event_docs, index = build_archive_documents(
        feed=feed,
        existing_notice_docs=notice_docs,
        existing_event_docs=event_docs,
        previous_index=previous_index,
        pretty=pretty,
    )

    for month, doc in next_notice_docs.items():
        write_json_if_changed(archive_dir / "notices" / f"{month}.json", doc, pretty)
    for month, doc in next_event_docs.items():
        write_json_if_changed(archive_dir / "events" / f"{month}.json", doc, pretty)
    write_json_if_changed(archive_dir / "index.json", index, pretty)
    write_json_if_changed(
        output_dir / "events.json",
        build_recent_events_document(next_event_docs, index),
        pretty,
    )


def archive_outputs_exist(output_dir: Path) -> bool:
    archive_dir = output_dir / "archive"
    index = read_json_if_exists(archive_dir / "index.json")
    if not index:
        return False
    for month in index.get("months", []):
        notices_url = month.get("notices_url")
        events_url = month.get("events_url")
        if notices_url and not (archive_dir / notices_url.removeprefix("./")).exists():
            return False
        if events_url and not (archive_dir / events_url.removeprefix("./")).exists():
            return False
    return True


def build_archive_documents(
    feed: dict,
    existing_notice_docs: dict[str, dict] | None = None,
    existing_event_docs: dict[str, dict] | None = None,
    previous_index: dict | None = None,
    pretty: bool = False,
) -> tuple[dict[str, dict], dict[str, dict], dict]:
    generated_at = str(feed.get("_pnu", {}).get("generated_at"))
    notice_docs = copy.deepcopy(existing_notice_docs or {})
    event_docs = copy.deepcopy(existing_event_docs or {})
    archived_items = archived_items_by_id(notice_docs)
    touched_notice_months: set[str] = set()
    touched_event_months: set[str] = set()

    for current_item in feed.get("items", []):
        item = normalize_archive_input_item(current_item)
        item_id = str(item["id"])
        pnu = item.get("_pnu", {})
        current_hash = item_content_hash(item)
        seen_at = str(pnu.get("fetched_at") or generated_at)
        existing = archived_items.get(item_id)

        if existing is None:
            notice_month = archive_month_for_item(item, seen_at)
            archived_item = archive_item(
                item,
                archive_month=notice_month,
                first_seen_at=seen_at,
                last_seen_at=seen_at,
                last_changed_at=seen_at,
            )
            notice_docs = upsert_archive_item(notice_docs, notice_month, archived_item)
            event_docs = add_event(
                event_docs,
                event_type="added",
                item=archived_item,
                notice_month=notice_month,
                event_time=seen_at,
                previous_content_hash=None,
            )
            touched_notice_months = {*touched_notice_months, notice_month}
            touched_event_months = {*touched_event_months, month_from_timestamp(seen_at)}
            continue

        existing_month, existing_item = existing
        previous_hash = item_content_hash(existing_item)
        if previous_hash == current_hash:
            continue

        existing_archive = existing_item.get("_archive", {})
        first_seen_at = str(existing_archive.get("first_seen_at") or seen_at)
        archived_item = archive_item(
            item,
            archive_month=existing_month,
            first_seen_at=first_seen_at,
            last_seen_at=generated_at,
            last_changed_at=generated_at,
        )
        notice_docs = upsert_archive_item(notice_docs, existing_month, archived_item)
        event_docs = add_event(
            event_docs,
            event_type="updated",
            item=archived_item,
            notice_month=existing_month,
            event_time=generated_at,
            previous_content_hash=previous_hash,
        )
        touched_notice_months = {*touched_notice_months, existing_month}
        touched_event_months = {*touched_event_months, month_from_timestamp(generated_at)}

    notice_docs = rebuild_notice_docs(notice_docs, touched_notice_months, generated_at)
    event_docs = rebuild_event_docs(event_docs, touched_event_months, generated_at)
    index = build_archive_index(
        notice_docs,
        event_docs,
        previous_index=previous_index,
        last_modified_at=generated_at,
        pretty=pretty,
    )
    return notice_docs, event_docs, index


def build_recent_events_document(
    event_docs: dict[str, dict],
    archive_index: dict,
    event_limit: int = RECENT_EVENT_LIMIT,
) -> dict:
    all_events = sorted(
        [
            event
            for doc in event_docs.values()
            for event in doc.get("events", [])
        ],
        key=lambda value: (value.get("seen_at") or "", value.get("event_id") or ""),
    )
    limited_events = all_events[-event_limit:]
    return {
        "schema_version": "0.1",
        "event_stream_version": EVENT_STREAM_VERSION,
        "generated_at": archive_index.get("last_modified_at"),
        "timezone": TIMEZONE,
        "event_count": len(limited_events),
        "total_event_count": len(all_events),
        "event_limit": event_limit,
        "latest_event_id": archive_index.get("latest_event_id"),
        "archive_index_url": "./archive/index.json",
        "archive_events_url_pattern": "./archive/events/{YYYY-MM}.json",
        "events": limited_events,
    }


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


def archived_items_by_id(notice_docs: dict[str, dict]) -> dict[str, tuple[str, dict]]:
    result: dict[str, tuple[str, dict]] = {}
    for month, doc in notice_docs.items():
        for item in doc.get("items", []):
            item_id = item.get("id")
            if item_id:
                result[str(item_id)] = (month, item)
    return result


def normalize_archive_input_item(item: dict) -> dict:
    pnu = copy.deepcopy(item.get("_pnu", {}))
    archive_item_copy = {
        key: copy.deepcopy(value)
        for key, value in item.items()
        if key != "_archive"
    }
    return {
        **archive_item_copy,
        "_pnu": pnu,
    }


def archive_month_for_item(item: dict, first_seen_at: str) -> str:
    pnu = item.get("_pnu", {})
    published_at = pnu.get("published_at") or item.get("date_published")
    if isinstance(published_at, str) and len(published_at) >= 7:
        return published_at[:7]
    return month_from_timestamp(first_seen_at)


def month_from_timestamp(value: str) -> str:
    return value[:7]


def archive_item(
    item: dict,
    archive_month: str,
    first_seen_at: str,
    last_seen_at: str,
    last_changed_at: str,
) -> dict:
    normalized = normalize_archive_input_item(item)
    return {
        **normalized,
        "_archive": {
            "archive_month": archive_month,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
            "last_changed_at": last_changed_at,
            "current_content_hash": item_content_hash(normalized),
        },
    }


def upsert_archive_item(
    notice_docs: dict[str, dict],
    month: str,
    item: dict,
) -> dict[str, dict]:
    doc = notice_docs.get(month) or empty_notice_doc(month)
    items = {
        str(existing["id"]): existing
        for existing in doc.get("items", [])
        if existing.get("id")
    }
    items = {**items, str(item["id"]): item}
    next_doc = {
        **doc,
        "items": sorted(
            items.values(),
            key=notice_sort_key,
            reverse=True,
        ),
    }
    return {**notice_docs, month: next_doc}


def add_event(
    event_docs: dict[str, dict],
    event_type: str,
    item: dict,
    notice_month: str,
    event_time: str,
    previous_content_hash: str | None,
) -> dict[str, dict]:
    event_month = month_from_timestamp(event_time)
    doc = event_docs.get(event_month) or empty_event_doc(event_month)
    event = event_for_item(
        item=item,
        event_type=event_type,
        event_time=event_time,
        notice_month=notice_month,
        previous_content_hash=previous_content_hash,
    )
    events = {
        str(existing["event_id"]): existing
        for existing in doc.get("events", [])
        if existing.get("event_id")
    }
    events = {**events, str(event["event_id"]): event}
    next_doc = {
        **doc,
        "events": sorted(
            events.values(),
            key=lambda value: (value.get("seen_at") or "", value.get("event_id") or ""),
        ),
    }
    return {**event_docs, event_month: next_doc}


def event_for_item(
    item: dict,
    event_type: str,
    event_time: str,
    notice_month: str,
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
        "content_hash": content_hash,
        "previous_content_hash": previous_content_hash,
        "archive_notice_file": f"../notices/{notice_month}.json",
        "archive_notice_id": notice_id,
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


def rebuild_notice_docs(
    notice_docs: dict[str, dict],
    touched_months: set[str],
    last_modified_at: str,
) -> dict[str, dict]:
    return {
        month: rebuild_notice_doc(
            month,
            doc,
            last_modified_at if month in touched_months else doc.get("last_modified_at"),
        )
        for month, doc in notice_docs.items()
    }


def rebuild_notice_doc(
    month: str,
    doc: dict,
    last_modified_at: str | None,
) -> dict:
    items = sorted(doc.get("items", []), key=notice_sort_key, reverse=True)
    return {
        "schema_version": "0.1",
        "archive_version": ARCHIVE_VERSION,
        "archive_type": "notices",
        "archive_month": month,
        "last_modified_at": last_modified_at or doc.get("last_modified_at"),
        "timezone": TIMEZONE,
        "item_count": len(items),
        "source_counts": source_counts(items),
        "items": items,
    }


def rebuild_event_docs(
    event_docs: dict[str, dict],
    touched_months: set[str],
    last_modified_at: str,
) -> dict[str, dict]:
    return {
        month: rebuild_event_doc(
            month,
            doc,
            last_modified_at if month in touched_months else doc.get("last_modified_at"),
        )
        for month, doc in event_docs.items()
    }


def rebuild_event_doc(
    month: str,
    doc: dict,
    last_modified_at: str | None,
) -> dict:
    events = sorted(
        doc.get("events", []),
        key=lambda value: (value.get("seen_at") or "", value.get("event_id") or ""),
    )
    return {
        "schema_version": "0.1",
        "archive_version": ARCHIVE_VERSION,
        "archive_type": "events",
        "archive_month": month,
        "last_modified_at": last_modified_at or doc.get("last_modified_at"),
        "timezone": TIMEZONE,
        "event_count": len(events),
        "events": events,
    }


def build_archive_index(
    notice_docs: dict[str, dict],
    event_docs: dict[str, dict],
    previous_index: dict | None,
    last_modified_at: str,
    pretty: bool,
) -> dict:
    months = sorted(set(notice_docs) | set(event_docs))
    month_entries = [
        month_index_entry(
            month,
            notice_docs.get(month),
            event_docs.get(month),
            pretty,
        )
        for month in months
    ]
    source_entries = source_index_entries(notice_docs, event_docs)
    all_events = [
        event
        for doc in event_docs.values()
        for event in doc.get("events", [])
    ]
    latest_event = sorted(
        all_events,
        key=lambda value: (value.get("seen_at") or "", value.get("event_id") or ""),
    )[-1] if all_events else None
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
        "notice_count": sum(entry["notice_count"] for entry in month_entries),
        "event_count": sum(entry["event_count"] for entry in month_entries),
        "latest_event_id": latest_event.get("event_id") if latest_event else None,
        "months": month_entries,
        "sources": source_entries,
    }
    if previous_index and archive_index_core(previous_index) == archive_index_core(next_index):
        return next_index
    return {
        **next_index,
        "last_modified_at": last_modified_at,
    }


def month_index_entry(
    month: str,
    notice_doc: dict | None,
    event_doc: dict | None,
    pretty: bool,
) -> dict:
    notice_meta = document_file_meta(notice_doc, pretty) if notice_doc else empty_file_meta()
    event_meta = document_file_meta(event_doc, pretty) if event_doc else empty_file_meta()
    notice_items = notice_doc.get("items", []) if notice_doc else []
    events = event_doc.get("events", []) if event_doc else []
    first_seen_values = [
        item.get("_archive", {}).get("first_seen_at")
        for item in notice_items
        if item.get("_archive", {}).get("first_seen_at")
    ]
    last_seen_values = [
        item.get("_archive", {}).get("last_seen_at")
        for item in notice_items
        if item.get("_archive", {}).get("last_seen_at")
    ]
    last_modified_values = [
        value
        for value in [
            notice_doc.get("last_modified_at") if notice_doc else None,
            event_doc.get("last_modified_at") if event_doc else None,
        ]
        if value
    ]
    return {
        "month": month,
        "notices_url": f"./notices/{month}.json" if notice_doc else None,
        "events_url": f"./events/{month}.json" if event_doc else None,
        "notice_count": len(notice_items),
        "event_count": len(events),
        "notices_size_bytes": notice_meta["size_bytes"],
        "events_size_bytes": event_meta["size_bytes"],
        "notices_sha256": notice_meta["sha256"],
        "events_sha256": event_meta["sha256"],
        "last_modified_at": max(last_modified_values) if last_modified_values else None,
        "first_seen_at": min(first_seen_values) if first_seen_values else None,
        "last_seen_at": max(last_seen_values) if last_seen_values else None,
    }


def source_index_entries(
    notice_docs: dict[str, dict],
    event_docs: dict[str, dict],
) -> list[dict]:
    source_data: dict[str, dict[str, Any]] = {}
    for doc in notice_docs.values():
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
    for doc in event_docs.values():
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


def empty_file_meta() -> dict:
    return {
        "size_bytes": 0,
        "sha256": None,
    }


def empty_notice_doc(month: str) -> dict:
    return {
        "schema_version": "0.1",
        "archive_version": ARCHIVE_VERSION,
        "archive_type": "notices",
        "archive_month": month,
        "last_modified_at": None,
        "timezone": TIMEZONE,
        "item_count": 0,
        "source_counts": {},
        "items": [],
    }


def empty_event_doc(month: str) -> dict:
    return {
        "schema_version": "0.1",
        "archive_version": ARCHIVE_VERSION,
        "archive_type": "events",
        "archive_month": month,
        "last_modified_at": None,
        "timezone": TIMEZONE,
        "event_count": 0,
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


def item_content_hash(item: dict) -> str | None:
    pnu = item.get("_pnu", {})
    return pnu.get("content_hash") or item.get("content_hash")


def min_known(left: str | None, right: str | None) -> str | None:
    values = [value for value in [left, right] if value]
    return min(values) if values else None


def max_known(left: str | None, right: str | None) -> str | None:
    values = [value for value in [left, right] if value]
    return max(values) if values else None


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
