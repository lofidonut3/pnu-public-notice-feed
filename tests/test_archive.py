from pnu_notice_feed.archive import build_archive_documents
from pnu_notice_feed.generator import CONTENT_TEXT_NOTICE


def test_archive_documents_create_added_event_for_new_notice():
    notice_docs, event_docs, index = build_archive_documents(
        _feed([_item("1", "hash-1")]),
        pretty=True,
    )

    notice_doc = notice_docs["2026-06"]
    event_doc = event_docs["2026-06"]

    assert notice_doc["archive_type"] == "notices"
    assert notice_doc["item_count"] == 1
    assert notice_doc["source_counts"] == {"pnu-main-notice": 1}
    assert notice_doc["items"][0]["_archive"] == {
        "archive_month": "2026-06",
        "first_seen_at": "2026-06-03T12:00:00+09:00",
        "last_seen_at": "2026-06-03T12:00:00+09:00",
        "last_changed_at": "2026-06-03T12:00:00+09:00",
        "current_content_hash": "hash-1",
    }
    assert event_doc["event_count"] == 1
    assert event_doc["events"][0]["event_type"] == "added"
    assert event_doc["events"][0]["archive_notice_file"] == "../notices/2026-06.json"
    assert event_doc["events"][0]["archive_notice_id"] == "pnu-main-notice:1"
    assert index["notice_count"] == 1
    assert index["event_count"] == 1
    assert index["months"][0]["notices_sha256"]
    assert index["months"][0]["events_sha256"]


def test_archive_documents_do_not_append_event_when_hash_is_unchanged():
    notice_docs, event_docs, index = build_archive_documents(
        _feed([_item("1", "hash-1")]),
        pretty=True,
    )

    next_notice_docs, next_event_docs, next_index = build_archive_documents(
        _feed(
            [_item("1", "hash-1")],
            generated_at="2026-06-03T12:30:00+09:00",
        ),
        existing_notice_docs=notice_docs,
        existing_event_docs=event_docs,
        previous_index=index,
        pretty=True,
    )

    assert next_notice_docs == notice_docs
    assert next_event_docs == event_docs
    assert next_index == index


def test_archive_documents_append_updated_event_when_hash_changes():
    notice_docs, event_docs, index = build_archive_documents(
        _feed([_item("1", "hash-1")]),
        pretty=True,
    )

    next_notice_docs, next_event_docs, next_index = build_archive_documents(
        _feed(
            [_item("1", "hash-2", title="수정된 공지")],
            generated_at="2026-06-03T12:30:00+09:00",
        ),
        existing_notice_docs=notice_docs,
        existing_event_docs=event_docs,
        previous_index=index,
        pretty=True,
    )

    events = next_event_docs["2026-06"]["events"]
    assert [event["event_type"] for event in events] == ["added", "updated"]
    assert events[1]["previous_content_hash"] == "hash-1"
    assert events[1]["content_hash"] == "hash-2"
    assert next_notice_docs["2026-06"]["items"][0]["title"] == "수정된 공지"
    assert next_notice_docs["2026-06"]["items"][0]["_archive"]["first_seen_at"] == (
        "2026-06-03T12:00:00+09:00"
    )
    assert next_notice_docs["2026-06"]["items"][0]["_archive"]["last_changed_at"] == (
        "2026-06-03T12:30:00+09:00"
    )
    assert next_index["event_count"] == 2


def test_archive_documents_do_not_emit_removed_when_item_is_absent_from_current_feed():
    notice_docs, event_docs, index = build_archive_documents(
        _feed([_item("1", "hash-1")]),
        pretty=True,
    )

    next_notice_docs, next_event_docs, next_index = build_archive_documents(
        _feed([], generated_at="2026-06-03T12:30:00+09:00"),
        existing_notice_docs=notice_docs,
        existing_event_docs=event_docs,
        previous_index=index,
        pretty=True,
    )

    assert next_notice_docs == notice_docs
    assert next_event_docs == event_docs
    assert next_index == index


def _feed(items, generated_at="2026-06-03T12:00:00+09:00"):
    return {
        "_pnu": {
            "generated_at": generated_at,
        },
        "items": items,
    }


def _item(
    suffix,
    content_hash,
    title="공지",
    published_at="2026-06-02",
    fetched_at="2026-06-03T12:00:00+09:00",
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
            "content_hash": content_hash,
        },
    }
