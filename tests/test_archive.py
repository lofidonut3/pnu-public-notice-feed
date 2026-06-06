from pnu_notice_feed.archive import build_archive_documents, build_recent_events_document
from pnu_notice_feed.generator import CONTENT_TEXT_NOTICE


def test_archive_documents_create_added_event_for_new_notice():
    archive_docs, index = build_archive_documents(
        _feed([_item("1", "hash-1")]),
        pretty=True,
    )

    archive_doc = archive_docs["2026-06"]

    assert archive_doc["archive_type"] == "month"
    assert archive_doc["item_count"] == 1
    assert archive_doc["event_count"] == 1
    assert archive_doc["source_counts"] == {"pnu-main-notice": 1}
    assert archive_doc["items"][0]["_archive"] == {
        "archive_month": "2026-06",
        "first_seen_at": "2026-06-03T12:00:00+09:00",
        "last_seen_at": "2026-06-03T12:00:00+09:00",
        "last_changed_at": "2026-06-03T12:00:00+09:00",
        "current_content_hash": "hash-1",
    }
    assert archive_doc["events"][0]["event_type"] == "added"
    assert archive_doc["events"][0]["archive_file"] == "./archive/2026-06.json"
    assert archive_doc["events"][0]["archive_item_id"] == "pnu-main-notice:1"
    assert "item" not in archive_doc["events"][0]
    assert archive_doc["events"][0]["source_name"] == "부산대 대학공지"
    assert archive_doc["events"][0]["topics"] == ["academic"]
    assert index["notice_count"] == 1
    assert index["event_count"] == 1
    assert index["months"][0]["sha256"]


def test_archive_documents_do_not_append_event_when_hash_is_unchanged():
    archive_docs, index = build_archive_documents(
        _feed([_item("1", "hash-1")]),
        pretty=True,
    )

    next_archive_docs, next_index = build_archive_documents(
        _feed(
            [_item("1", "hash-1")],
            generated_at="2026-06-03T12:30:00+09:00",
        ),
        existing_archive_docs=archive_docs,
        previous_index=index,
        pretty=True,
    )

    assert next_archive_docs == archive_docs
    assert next_index == index


def test_archive_documents_append_updated_event_when_hash_changes():
    archive_docs, index = build_archive_documents(
        _feed([_item("1", "hash-1")]),
        pretty=True,
    )

    next_archive_docs, next_index = build_archive_documents(
        _feed(
            [_item("1", "hash-2", title="수정된 공지")],
            generated_at="2026-06-03T12:30:00+09:00",
        ),
        existing_archive_docs=archive_docs,
        previous_index=index,
        pretty=True,
    )

    events = next_archive_docs["2026-06"]["events"]
    assert [event["event_type"] for event in events] == ["added", "updated"]
    assert events[1]["previous_content_hash"] == "hash-1"
    assert events[1]["content_hash"] == "hash-2"
    assert events[1]["title"] == "수정된 공지"
    assert "item" not in events[1]
    assert next_archive_docs["2026-06"]["items"][0]["title"] == "수정된 공지"
    assert next_archive_docs["2026-06"]["items"][0]["_archive"]["first_seen_at"] == (
        "2026-06-03T12:00:00+09:00"
    )
    assert next_archive_docs["2026-06"]["items"][0]["_archive"]["last_changed_at"] == (
        "2026-06-03T12:30:00+09:00"
    )
    assert next_index["event_count"] == 2


def test_archive_documents_do_not_emit_removed_when_item_is_absent_from_current_feed():
    archive_docs, index = build_archive_documents(
        _feed([_item("1", "hash-1")]),
        pretty=True,
    )

    next_archive_docs, next_index = build_archive_documents(
        _feed([], generated_at="2026-06-03T12:30:00+09:00"),
        existing_archive_docs=archive_docs,
        previous_index=index,
        pretty=True,
    )

    assert next_archive_docs == archive_docs
    assert next_index == index


def test_recent_events_document_uses_latest_events_as_agent_cursor_stream():
    archive_docs, index = build_archive_documents(
        _feed(
            [
                _item("1", "hash-1", fetched_at="2026-06-03T12:00:00+09:00"),
                _item("2", "hash-2", fetched_at="2026-06-03T12:30:00+09:00"),
                _item("3", "hash-3", fetched_at="2026-06-03T13:00:00+09:00"),
            ],
            generated_at="2026-06-03T13:00:00+09:00",
        ),
        pretty=True,
    )

    events = build_recent_events_document(
        archive_docs,
        index,
        event_limit=2,
    )

    assert events["schema_version"] == "0.1"
    assert events["event_stream_version"] == "0.3"
    assert events["generated_at"] == index["last_modified_at"]
    assert events["event_count"] == 2
    assert events["total_event_count"] == 3
    assert events["event_limit"] == 2
    assert events["latest_event_id"] == index["latest_event_id"]
    assert events["oldest_event_id"] == events["events"][0]["event_id"]
    assert events["oldest_seen_at"] == "2026-06-03T12:30:00+09:00"
    assert events["latest_seen_at"] == "2026-06-03T13:00:00+09:00"
    assert events["is_truncated"] is True
    assert events["index_url"] == "./index.json"
    assert events["archive_url_pattern"] == "./archive/{YYYY-MM}.json"
    assert [event["notice_id"] for event in events["events"]] == [
        "pnu-main-notice:2",
        "pnu-main-notice:3",
    ]
    assert events["events"][0]["archive_file"] == "./archive/2026-06.json"
    assert events["events"][0]["archive_item_id"] == "pnu-main-notice:2"
    assert "item" not in events["events"][0]


def test_archive_documents_store_baseline_items_without_added_events():
    archive_docs, index = build_archive_documents(
        _feed(
            [_item("1", "hash-1")],
            baseline_source_ids=["pnu-main-notice"],
        ),
        pretty=True,
    )

    archive_doc = archive_docs["2026-06"]
    assert archive_doc["item_count"] == 1
    assert archive_doc["event_count"] == 0
    assert archive_doc["events"] == []
    assert archive_doc["items"][0]["_archive"]["baseline_imported_at"] == (
        "2026-06-03T12:00:00+09:00"
    )
    assert index["notice_count"] == 1
    assert index["event_count"] == 0


def test_archive_documents_remove_existing_events_for_baseline_items():
    archive_docs, index = build_archive_documents(
        _feed([_item("1", "hash-1")]),
        pretty=True,
    )
    assert archive_docs["2026-06"]["event_count"] == 1

    next_archive_docs, next_index = build_archive_documents(
        _feed(
            [_item("1", "hash-1")],
            generated_at="2026-06-03T12:30:00+09:00",
            baseline_source_ids=["pnu-main-notice"],
        ),
        existing_archive_docs=archive_docs,
        previous_index=index,
        pretty=True,
    )

    assert next_archive_docs["2026-06"]["events"] == []
    assert next_archive_docs["2026-06"]["event_count"] == 0
    assert next_index["event_count"] == 0


def test_archive_documents_update_metadata_without_updated_event_when_hash_unchanged():
    archive_docs, index = build_archive_documents(
        _feed([_item("1", "hash-1")]),
        pretty=True,
    )

    next_archive_docs, next_index = build_archive_documents(
        _feed(
            [
                _item(
                    "1",
                    "hash-1",
                    topics=["academic", "scholarship"],
                )
            ],
            generated_at="2026-06-03T12:30:00+09:00",
        ),
        existing_archive_docs=archive_docs,
        previous_index=index,
        pretty=True,
    )

    archive_doc = next_archive_docs["2026-06"]
    assert archive_doc["event_count"] == 1
    assert [event["event_type"] for event in archive_doc["events"]] == ["added"]
    assert archive_doc["items"][0]["_pnu"]["topics"] == ["academic", "scholarship"]


def _feed(
    items,
    generated_at="2026-06-03T12:00:00+09:00",
    baseline_source_ids=None,
):
    return {
        "_pnu": {
            "generated_at": generated_at,
            "baseline_source_ids": baseline_source_ids or [],
        },
        "items": items,
    }


def _item(
    suffix,
    content_hash,
    title="공지",
    published_at="2026-06-02",
    fetched_at="2026-06-03T12:00:00+09:00",
    topics=None,
):
    return {
        "id": f"pnu-main-notice:{suffix}",
        "url": f"https://www.pusan.ac.kr/notice/{suffix}",
        "title": title,
        "content_text": CONTENT_TEXT_NOTICE,
        "summary": "본문 일부",
        "date_published": "2026-06-02T00:00:00+09:00",
        "_pnu": {
            "source_id": "pnu-main-notice",
            "source_name": "부산대 대학공지",
            "source_category": "university_notice",
            "source_tags": ["pnu", "official", "main_notice"],
            "published_at": published_at,
            "fetched_at": fetched_at,
            "snippet": "본문 일부",
            "content_access": {
                "detail_url": f"https://www.pusan.ac.kr/notice/{suffix}",
                "requires_login": False,
                "content_mirrored": False,
                "attachments_mirrored": False,
            },
            "attachments": [],
            "tags": ["pnu", "official"],
            "topics": topics or ["academic"],
            "same_notice_group_id": None,
            "canonical_item_id": f"pnu-main-notice:{suffix}",
            "is_canonical": True,
            "same_notice_source_ids": ["pnu-main-notice"],
            "content_hash": content_hash,
        },
    }
