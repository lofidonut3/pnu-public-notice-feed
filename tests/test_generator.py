from datetime import datetime
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from pnu_notice_feed import generator
from pnu_notice_feed.generator import (
    CONTENT_TEXT_NOTICE,
    JSON_FEED_VERSION,
    PublicSource,
    SourceResult,
    archive_input_from_state,
    build_changes,
    build_feed,
    build_rss,
    build_state,
    build_status,
    all_sources_skipped,
    backoff_until_for_error,
    date_to_json_feed_timestamp,
    fetch_source_result,
    generate_outputs,
    load_sources,
    media_type_from_extension,
    next_check_at_from_interval,
    normalize_feed_item,
    notice_to_feed_item,
    sync_static_assets,
)

from pnu_notice_feed.types import Attachment, Notice


def test_notice_to_feed_item_uses_stable_public_schema():
    notice = Notice(
        source_id="pnu-main-notice",
        source_name="부산대 대학공지",
        notice_id="pnu-main-notice:1509234",
        title="공지 제목",
        url="https://www.pusan.ac.kr/notice",
        published_at="2026-06-02",
        snippet="본문 일부",
        attachments=[
            Attachment(
                name="첨부.pdf",
                url="https://www.pusan.ac.kr/file.pdf",
                type="pdf",
            )
        ],
        tags=["pnu", "official"],
        content_hash="abc123",
    )

    item = notice_to_feed_item(notice, "2026-06-03T12:00:00+09:00")

    assert item == {
        "id": "pnu-main-notice:1509234",
        "url": "https://www.pusan.ac.kr/notice",
        "title": "공지 제목",
        "content_text": CONTENT_TEXT_NOTICE,
        "summary": "본문 일부",
        "date_published": "2026-06-02T00:00:00+09:00",
        "_pnu": {
            "source_id": "pnu-main-notice",
            "source_name": "부산대 대학공지",
            "published_at": "2026-06-02",
            "fetched_at": "2026-06-03T12:00:00+09:00",
            "snippet": "본문 일부",
            "content_access": {
                "detail_url": "https://www.pusan.ac.kr/notice",
                "requires_login": False,
                "content_mirrored": False,
                "attachments_mirrored": False,
            },
            "attachments": [
                {
                    "name": "첨부.pdf",
                    "url": "https://www.pusan.ac.kr/file.pdf",
                    "download_url": "https://www.pusan.ac.kr/file.pdf",
                    "type": "pdf",
                    "media_type": "application/pdf",
                    "file_extension": "pdf",
                }
            ],
            "tags": ["pnu", "official"],
            "content_hash": "abc123",
        },
    }


def test_notice_to_feed_item_includes_detail_checked_at_when_present():
    notice = Notice(
        source_id="pnu-main-notice",
        source_name="부산대 대학공지",
        notice_id="pnu-main-notice:1509234",
        title="공지 제목",
        url="https://www.pusan.ac.kr/notice",
        published_at="2026-06-02",
        snippet="본문 일부",
        attachments=[],
        tags=["pnu", "official"],
        content_hash="abc123",
        detail_checked_at="2026-06-03T12:00:00+09:00",
    )

    item = notice_to_feed_item(notice, "2026-06-03T12:00:00+09:00")

    assert item["_pnu"]["detail_checked_at"] == "2026-06-03T12:00:00+09:00"


def test_build_feed_sorts_items_by_published_date_desc():
    source = _source()
    old_notice = _notice(source, "1", "2026-06-01")
    new_notice = _notice(source, "2", "2026-06-03")
    result = _result(source, "2026-06-03T12:00:00+09:00", [old_notice, new_notice])

    feed = build_feed(
        [result],
        "2026-06-03T12:00:00+09:00",
        "https://feeds.example.test",
    )

    assert feed["version"] == JSON_FEED_VERSION
    assert feed["home_page_url"] == "https://feeds.example.test"
    assert feed["feed_url"] == "https://feeds.example.test/feed.json"
    assert feed["_pnu"]["schema_version"] == "0.1"
    assert feed["_pnu"]["changes_url"] == "https://feeds.example.test/changes.json"
    assert feed["_pnu"]["source_count"] == 1
    assert feed["_pnu"]["item_count"] == 2
    assert [item["id"] for item in feed["items"]] == [
        "pnu-main-notice:2",
        "pnu-main-notice:1",
    ]
    assert "not operated by Pusan National University" in feed["description"]
    assert feed["items"][0]["date_published"] == "2026-06-03T00:00:00+09:00"


def test_build_rss_creates_rss_compatibility_feed():
    source = _source()
    result = _result(
        source,
        "2026-06-03T12:00:00+09:00",
        [_notice(source, "1", "2026-06-03", snippet="짧은 미리보기")],
    )
    feed = build_feed(
        [result],
        "2026-06-03T12:00:00+09:00",
        "https://feeds.example.test",
    )

    rss = build_rss(feed)
    root = ElementTree.fromstring(rss)
    channel = root.find("channel")
    item = channel.find("item")

    assert root.tag == "rss"
    assert root.attrib["version"] == "2.0"
    assert channel.findtext("title") == "PNU Public Notice Feed"
    assert channel.findtext("link") == "https://feeds.example.test"
    assert channel.findtext("lastBuildDate") == "Wed, 03 Jun 2026 12:00:00 +0900"
    assert item.findtext("title") == "공지 1"
    assert item.findtext("link") == "https://www.pusan.ac.kr/kor/CMS/Board/PopupBoard.do?id=1"
    assert item.findtext("guid") == "pnu-main-notice:1"
    assert item.find("guid").attrib["isPermaLink"] == "false"
    assert item.findtext("pubDate") == "Wed, 03 Jun 2026 00:00:00 +0900"
    assert item.findtext("description") == "짧은 미리보기"
    assert item.findtext("category") == "pnu-main-notice"
    assert item.findtext("source") == "부산대 대학공지"
    assert item.find("source").attrib["url"] == "https://www.pusan.ac.kr/kor/CMS/Board/PopupBoard.do"


def test_normalize_feed_item_migrates_cached_snippet_to_summary():
    item = {
        "id": "pnu-main-notice:1",
        "url": "https://www.pusan.ac.kr/notice",
        "title": "공지",
        "content_text": "예전 cache snippet",
        "_pnu": {
            "snippet": "예전 cache snippet",
        },
    }

    normalized = normalize_feed_item(item)

    assert normalized["content_text"] == CONTENT_TEXT_NOTICE
    assert normalized["summary"] == "예전 cache snippet"
    assert normalized["_pnu"] == item["_pnu"]


def test_build_status_reports_partial_failure():
    checked_at = datetime(2026, 6, 3, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")).isoformat(
        timespec="seconds"
    )
    ok_source = _source()
    failed_source = PublicSource(
        id="pnu-onestop-notices",
        name="부산대 학지시 공지",
        adapter="onestop-js-board",
        official_url="https://onestop.pusan.ac.kr/page?menuCD=000000000000386",
        category="academic_notice",
        poll_interval_minutes=30,
        public_only=True,
        tags=["pnu", "official"],
        menu_cd="000000000000386",
    )

    status = build_status(
        [
            SourceResult(
                source=ok_source,
                checked_at=checked_at,
                items=[
                    notice_to_feed_item(
                        _notice(ok_source, "1", "2026-06-03"),
                        checked_at,
                    )
                ],
                last_success_at=checked_at,
                status="ok",
            ),
            SourceResult(
                source=failed_source,
                checked_at=checked_at,
                items=[],
                last_success_at=None,
                status="error",
                error="network timeout",
            ),
        ],
        checked_at,
    )

    assert status["overall_status"] == "partial"
    assert status["failed_source_count"] == 1
    assert status["sources"][0]["status"] == "ok"
    assert status["sources"][1]["status"] == "error"
    assert status["sources"][1]["last_success_at"] is None
    assert status["sources"][1]["last_error_at"] == checked_at
    assert status["sources"][1]["status"] == "error"
    assert status["sources"][1]["error_type"] == "timeout"
    assert status["sources"][1]["error"] == "network timeout"


def test_build_status_counts_backoff_skip_as_partial_not_poll_interval_skip():
    checked_at = "2026-06-03T12:00:00+09:00"
    ok_source = _source("pnu-main-notice")
    backoff_source = _source("pnu-onestop-notices")
    poll_skip_source = _source("pnu-onestop-scholarship")

    status = build_status(
        [
            SourceResult(
                source=ok_source,
                checked_at=checked_at,
                items=[],
                last_success_at=checked_at,
                status="ok",
            ),
            SourceResult(
                source=backoff_source,
                checked_at=checked_at,
                items=[],
                last_success_at="2026-06-03T11:00:00+09:00",
                status="skipped",
                skipped_reason="backoff",
                error="network timeout",
            ),
            SourceResult(
                source=poll_skip_source,
                checked_at=checked_at,
                items=[],
                last_success_at=checked_at,
                status="skipped",
                skipped_reason="poll_interval",
            ),
        ],
        checked_at,
    )

    assert status["overall_status"] == "partial"
    assert status["failed_source_count"] == 1


def test_build_changes_reports_added_updated_and_removed_items():
    source = _source()
    old_checked_at = "2026-06-03T12:00:00+09:00"
    old_state = build_state(
        [
            _result(
                source,
                old_checked_at,
                [
                    _notice(source, "old", "2026-06-01"),
                    _notice(source, "changed", "2026-06-02"),
                ],
            )
        ],
        old_checked_at,
    )
    changed_notice = _notice(source, "changed", "2026-06-02", content_hash="new-hash")
    new_checked_at = "2026-06-04T12:00:00+09:00"
    new_state = build_state(
        [
            _result(
                source,
                new_checked_at,
                [
                    changed_notice,
                    _notice(source, "new", "2026-06-04"),
                ],
            )
        ],
        new_checked_at,
    )

    changes = build_changes(old_state, new_state)

    assert changes["added_count"] == 1
    assert changes["updated_count"] == 1
    assert changes["removed_count"] == 1
    assert changes["generated_at"] == new_checked_at
    assert changes["previous_generated_at"] == old_checked_at
    assert changes["added"][0]["id"] == "pnu-main-notice:new"
    assert changes["updated"][0]["id"] == "pnu-main-notice:changed"
    assert changes["removed"][0]["id"] == "pnu-main-notice:old"


def test_generate_outputs_includes_duplicate_groups(tmp_path, monkeypatch):
    sources_path = tmp_path / "sources.json"
    state_path = tmp_path / "feed-state.json"
    sources_path.write_text(
        """
        {
          "schema_version": "0.1",
          "sources": [
            {
              "id": "pnu-main-notice",
              "name": "부산대 대학공지",
              "official_url": "https://www.pusan.ac.kr/kor/CMS/Board/PopupBoard.do",
              "adapter": "pusan-cms-static-board",
              "category": "notice",
              "poll_interval_minutes": 30,
              "public_only": true,
              "tags": ["pnu", "official"]
            },
            {
              "id": "pnu-onestop-notices",
              "name": "부산대 학지시 공지",
              "official_url": "https://onestop.pusan.ac.kr/page?menuCD=000000000000386",
              "adapter": "pusan-cms-static-board",
              "category": "notice",
              "poll_interval_minutes": 30,
              "public_only": true,
              "tags": ["pnu", "official"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    def fake_fetch_source(source, limit, cached_items=None, checked_at=None):
        return [
            Notice(
                source_id=source.id,
                source_name=source.name,
                notice_id=f"{source.id}:1",
                title=(
                    "[장학]한국농어촌희망재단 2026학년도 2학기 청년창업농장학금 선발 안내"
                    if source.id == "pnu-main-notice"
                    else "한국농어촌희망재단 2026학년도 2학기 청년창업농장학금 선발 안내"
                ),
                url=f"https://example.test/{source.id}/1",
                published_at="2026-06-04",
                snippet=None,
                attachments=[],
                tags=source.tags,
                content_hash=source.id,
            )
        ]

    monkeypatch.setattr(generator, "fetch_source", fake_fetch_source)

    generated = generate_outputs(
        sources_path=sources_path,
        state_path=state_path,
        limit=20,
        public_base_url="https://feeds.example.test",
        now=datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert generated["duplicates"]["generated_at"] == "2026-06-05T12:00:00+09:00"
    assert generated["duplicates"]["group_count"] == 1
    assert generated["duplicates"]["groups"][0]["item_ids"] == [
        "pnu-main-notice:1",
        "pnu-onestop-notices:1",
    ]


def test_archive_input_is_built_from_state_items():
    source = _source()
    checked_at = "2026-06-04T12:00:00+09:00"
    state = build_state(
        [
            _result(
                source,
                checked_at,
                [
                    _notice(source, "old", "2026-06-01"),
                    _notice(source, "new", "2026-06-04"),
                ],
            )
        ],
        checked_at,
    )

    archive_input = archive_input_from_state(state)

    assert archive_input["_pnu"]["generated_at"] == checked_at
    assert sorted(item["id"] for item in archive_input["items"]) == [
        "pnu-main-notice:new",
        "pnu-main-notice:old",
    ]


def test_build_state_preserves_cached_items_and_success_metadata():
    source = _source()
    checked_at = "2026-06-04T12:00:00+09:00"
    result = _result(
        source,
        checked_at,
        [_notice(source, "1", "2026-06-04")],
    )

    state = build_state([result], checked_at)

    source_state = state["sources"]["pnu-main-notice"]
    assert source_state["last_checked_at"] == checked_at
    assert source_state["last_success_at"] == checked_at
    assert source_state["last_error_at"] is None
    assert source_state["status"] == "ok"
    assert source_state["next_check_at"] == "2026-06-04T12:30:00+09:00"
    assert source_state["items"][0]["id"] == "pnu-main-notice:1"


def test_all_sources_skipped_only_when_every_source_is_skipped():
    source = _source()
    skipped = SourceResult(
        source=source,
        checked_at="2026-06-04T12:00:00+09:00",
        items=[],
        last_success_at="2026-06-04T11:00:00+09:00",
        status="skipped",
        skipped_reason="poll_interval",
    )
    ok = _result(source, "2026-06-04T12:00:00+09:00", [])

    assert all_sources_skipped([skipped])
    assert not all_sources_skipped([skipped, ok])
    assert not all_sources_skipped([])


def test_fetch_source_result_reuses_cached_items_on_source_failure():
    source = PublicSource(
        id="broken-source",
        name="Broken Source",
        adapter="unsupported-adapter",
        official_url="https://example.com/notices",
        category="notice",
        poll_interval_minutes=30,
        public_only=True,
        tags=["official"],
    )
    cached_item = notice_to_feed_item(
        Notice(
            source_id=source.id,
            source_name=source.name,
            notice_id="broken-source:1",
            title="Cached notice",
            url="https://example.com/notices/1",
            published_at="2026-06-01",
            snippet="cached",
            attachments=[],
            tags=source.tags,
            content_hash="cached-hash",
        ),
        "2026-06-03T12:00:00+09:00",
    )
    state = {
        "sources": {
            source.id: {
                "last_success_at": "2026-06-03T12:00:00+09:00",
                "items": [cached_item],
            }
        }
    }

    result = fetch_source_result(
        source,
        limit=20,
        checked_at="2026-06-04T12:00:00+09:00",
        state=state,
    )

    assert not result.success
    assert result.last_success_at == "2026-06-03T12:00:00+09:00"
    assert result.items == [cached_item]
    assert "unsupported adapter" in result.error
    assert result.status == "error"
    assert result.backoff_until == "2026-06-04T12:30:00+09:00"


def test_fetch_source_result_skips_when_poll_interval_has_not_elapsed():
    source = _source()
    cached_item = notice_to_feed_item(
        _notice(source, "1", "2026-06-01"),
        "2026-06-04T12:00:00+09:00",
    )
    state = {
        "sources": {
            source.id: {
                "last_checked_at": "2026-06-04T12:00:00+09:00",
                "last_success_at": "2026-06-04T12:00:00+09:00",
                "items": [cached_item],
            }
        }
    }

    result = fetch_source_result(
        source,
        limit=20,
        checked_at="2026-06-04T12:05:00+09:00",
        state=state,
    )

    assert result.status == "skipped"
    assert result.skipped_reason == "poll_interval"
    assert result.next_check_at == "2026-06-04T12:30:00+09:00"
    assert result.items == [cached_item]


def test_fetch_source_result_respects_backoff_without_cached_items():
    source = PublicSource(
        id="broken-source",
        name="Broken Source",
        adapter="unsupported-adapter",
        official_url="https://example.com/notices",
        category="notice",
        poll_interval_minutes=30,
        public_only=True,
        tags=["official"],
    )
    state = {
        "sources": {
            source.id: {
                "last_checked_at": "2026-06-04T12:00:00+09:00",
                "last_success_at": None,
                "backoff_until": "2026-06-04T12:30:00+09:00",
                "error_count": 1,
                "error": "unsupported adapter",
                "items": [],
            }
        }
    }

    result = fetch_source_result(
        source,
        limit=20,
        checked_at="2026-06-04T12:05:00+09:00",
        state=state,
    )

    assert result.status == "skipped"
    assert result.skipped_reason == "backoff"
    assert result.next_check_at == "2026-06-04T12:30:00+09:00"
    assert result.error == "unsupported adapter"
    assert result.items == []


def test_backoff_until_for_error_uses_exponential_delay_capped_at_six_hours():
    assert (
        backoff_until_for_error("2026-06-04T12:00:00+09:00", 30, 1)
        == "2026-06-04T12:30:00+09:00"
    )
    assert (
        backoff_until_for_error("2026-06-04T12:00:00+09:00", 30, 2)
        == "2026-06-04T13:00:00+09:00"
    )
    assert (
        backoff_until_for_error("2026-06-04T12:00:00+09:00", 30, 20)
        == "2026-06-04T18:00:00+09:00"
    )


def test_load_sources_rejects_non_public_source(tmp_path):
    source_path = tmp_path / "sources.json"
    source_path.write_text(
        """
        {
          "sources": [
            {
              "id": "private-source",
              "name": "Private Source",
              "official_url": "https://example.com/private",
              "adapter": "pusan-cms-static-board",
              "public_only": false
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    try:
        load_sources(source_path)
    except ValueError as error:
        assert "source must be public_only" in str(error)
    else:
        raise AssertionError("expected non-public source to be rejected")


def test_load_sources_rejects_duplicate_source_ids(tmp_path):
    source_path = tmp_path / "sources.json"
    source_path.write_text(
        """
        {
          "sources": [
            {
              "id": "same-source",
              "name": "Source 1",
              "official_url": "https://example.com/1",
              "adapter": "pusan-cms-static-board",
              "public_only": true
            },
            {
              "id": "same-source",
              "name": "Source 2",
              "official_url": "https://example.com/2",
              "adapter": "pusan-cms-static-board",
              "public_only": true
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    try:
        load_sources(source_path)
    except ValueError as error:
        assert "duplicate source id" in str(error)
    else:
        raise AssertionError("expected duplicate source ids to be rejected")


def test_load_sources_requires_onestop_menu_cd(tmp_path):
    source_path = tmp_path / "sources.json"
    source_path.write_text(
        """
        {
          "sources": [
            {
              "id": "onestop-without-menu",
              "name": "Onestop",
              "official_url": "https://onestop.pusan.ac.kr/page?menuCD=000000000000386",
              "adapter": "onestop-js-board",
              "public_only": true
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    try:
        load_sources(source_path)
    except ValueError as error:
        assert "menu_cd is required" in str(error)
    else:
        raise AssertionError("expected missing menu_cd to be rejected")


def test_sync_static_assets_makes_public_output_self_contained(tmp_path):
    source_path = tmp_path / "sources.json"
    output_dir = tmp_path / "public"
    source_path.write_text('{"schema_version":"0.1","sources":[]}\n', encoding="utf-8")

    sync_static_assets(output_dir, source_path)

    assert (output_dir / "sources.json").exists()
    assert (output_dir / "openapi.json").exists()
    assert (output_dir / "llms.txt").exists()
    assert (output_dir / "schema" / "feed.schema.json").exists()


def test_date_to_json_feed_timestamp_preserves_unknown_formats():
    assert date_to_json_feed_timestamp("2026-06-04") == "2026-06-04T00:00:00+09:00"
    assert date_to_json_feed_timestamp("2026.06.04") == "2026.06.04"
    assert date_to_json_feed_timestamp(None) is None


def test_media_type_from_extension_maps_common_attachment_types():
    assert media_type_from_extension("xlsx").startswith("application/")
    assert media_type_from_extension("pdf") == "application/pdf"
    assert media_type_from_extension("unknown") is None


def _source(source_id: str = "pnu-main-notice") -> PublicSource:
    return PublicSource(
        id=source_id,
        name="부산대 대학공지",
        adapter="pusan-cms-static-board",
        official_url="https://www.pusan.ac.kr/kor/CMS/Board/PopupBoard.do",
        category="university_notice",
        poll_interval_minutes=30,
        public_only=True,
        tags=["pnu", "official"],
    )


def _result(
    source: PublicSource,
    checked_at: str,
    notices: list[Notice],
) -> SourceResult:
    return SourceResult(
        source=source,
        checked_at=checked_at,
        items=[notice_to_feed_item(notice, checked_at) for notice in notices],
        last_success_at=checked_at,
        status="ok",
        next_check_at=next_check_at_from_interval(
            checked_at,
            source.poll_interval_minutes,
        ),
    )


def _notice(
    source: PublicSource,
    suffix: str,
    published_at: str,
    content_hash: str | None = None,
    snippet: str | None = None,
) -> Notice:
    return Notice(
        source_id=source.id,
        source_name=source.name,
        notice_id=f"{source.id}:{suffix}",
        title=f"공지 {suffix}",
        url=f"{source.official_url}?id={suffix}",
        published_at=published_at,
        snippet=snippet,
        attachments=[],
        tags=source.tags,
        content_hash=content_hash or f"hash-{suffix}",
    )
