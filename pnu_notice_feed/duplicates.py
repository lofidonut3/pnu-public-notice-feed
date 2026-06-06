from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict

SCHEMA_VERSION = "0.1"
DEFAULT_FEED_VERSION = "2026-06-04"

DEDUPLICATION_POLICY = {
    "scope": "metadata_only_high_confidence",
    "raw_items_preserved": True,
    "full_body_fetched_for_dedupe": False,
    "false_positive_policy": "avoid_suppressing_distinct_notices",
}

EXCLUDED_SOURCE_PREFIXES = (
    "pnu-dorm-",
    "pnu-job-recruit-",
)


def build_duplicates(
    items: list[dict],
    generated_at: str,
    feed_version: str = DEFAULT_FEED_VERSION,
) -> dict:
    candidates: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in items:
        key = duplicate_candidate_key(item)
        if key:
            candidates[key].append(item)

    groups = [
        duplicate_group(key, group_items)
        for key, group_items in sorted(candidates.items())
        if has_multiple_sources(group_items)
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "feed_version": feed_version,
        "generated_at": generated_at,
        "item_count": len(items),
        "group_count": len(groups),
        "policy": {**DEDUPLICATION_POLICY},
        "groups": groups,
    }


def duplicate_candidate_key(item: dict) -> tuple[str, str] | None:
    source_id = item_source_id(item)
    if source_is_excluded(source_id):
        return None

    published_date = item_published_date(item)
    title_key = normalize_title(item.get("title"))
    if not published_date or len(title_key) < 8:
        return None

    return published_date, title_key


def duplicate_group(key: tuple[str, str], items: list[dict]) -> dict:
    published_date, title_key = key
    sorted_items = sorted(items, key=lambda item: str(item.get("id") or ""))
    item_ids = [str(item["id"]) for item in sorted_items if item.get("id")]
    source_ids = sorted({item_source_id(item) for item in sorted_items})
    canonical_item = sorted(
        sorted_items,
        key=lambda item: (
            source_priority(item),
            str(item.get("id") or ""),
        ),
    )[0]
    evidence = [
        "cross_source",
        "same_normalized_title",
        "same_published_date",
        *shared_attachment_evidence(sorted_items),
    ]

    return {
        "id": duplicate_group_id(published_date, title_key),
        "relationship": "same_notice",
        "confidence": "high",
        "consumer_action": "dedupe_notifications",
        "canonical_item_id": str(canonical_item.get("id") or item_ids[0]),
        "item_ids": item_ids,
        "source_ids": source_ids,
        "published_dates": [published_date],
        "representative_title": str(canonical_item.get("title") or ""),
        "evidence": evidence,
    }


def has_multiple_sources(items: list[dict]) -> bool:
    return len({item_source_id(item) for item in items}) > 1


def duplicate_group_id(published_date: str, title_key: str) -> str:
    value = f"same_notice|{published_date}|{title_key}".encode("utf-8")
    digest = hashlib.sha256(value).hexdigest()[:16]
    return f"same_notice:{digest}"


def source_is_excluded(source_id: str) -> bool:
    return source_id.startswith(EXCLUDED_SOURCE_PREFIXES)


def item_source_id(item: dict) -> str:
    return str(item.get("_pnu", {}).get("source_id") or item.get("source_id") or "")


def source_priority(item: dict) -> int:
    source_id = item_source_id(item)
    category = str(item.get("_pnu", {}).get("source_category") or "")
    tags = {str(tag) for tag in item.get("_pnu", {}).get("source_tags", [])}

    if source_id == "pnu-main-notice":
        return 10
    if source_id in {"pnu-onestop-notices", "pnu-onestop-scholarship"}:
        return 20
    if category and not category.startswith("academic_unit_"):
        return 30
    if "college_notice" in tags:
        return 40
    if category.startswith("academic_unit_") or "department_notice" in tags:
        return 50
    return 60


def item_published_date(item: dict) -> str | None:
    value = item.get("_pnu", {}).get("published_at") or item.get("date_published")
    if not value:
        return None
    return str(value)[:10]


def normalize_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    text = re.sub(r"^\s*(\[[^\]]{1,50}\]\s*)+", "", text)
    text = re.sub(r"\s*새글\s*$", "", text)
    text = re.sub(r"[\"“”‘’'`]", "", text)
    text = re.sub(r"[\[\]{}()（）<>〈〉「」『』]", " ", text)
    text = re.sub(r"[^0-9a-z가-힣]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def shared_attachment_evidence(items: list[dict]) -> list[str]:
    attachment_sets = [
        names
        for item in items
        if (names := normalized_attachment_names(item))
    ]
    if len(attachment_sets) < 2:
        return []

    shared = set.intersection(*attachment_sets)
    return ["shared_attachment_names"] if shared else []


def normalized_attachment_names(item: dict) -> set[str]:
    return {
        normalized
        for attachment in item.get("_pnu", {}).get("attachments", [])
        if (normalized := normalize_attachment_name(attachment.get("name")))
    }


def normalize_attachment_name(value: str | None) -> str | None:
    text = unicodedata.normalize("NFKC", value or "").lower().strip()
    text = re.sub(r"\s*\(\s*\d+(?:\.\d+)?\s*(?:bytes?|kb|mb|gb)\s*\)\s*$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or text == "목록" or "." not in text:
        return None
    return text
