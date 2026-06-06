import json
import threading
import time
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from pnu_notice_feed import generator
from pnu_notice_feed.generator import (
    CONTENT_TEXT_NOTICE,
    JSON_FEED_VERSION,
    PublicSource,
    SourceResult,
    archive_input_from_state,
    assert_size_budget,
    build_latest,
    build_output_file_diagnostics,
    build_public_index,
    build_run_diff,
    build_rss,
    build_size_budget_diagnostics,
    build_state,
    build_status,
    all_sources_skipped,
    backoff_until_for_error,
    date_to_json_feed_timestamp,
    fetch_source_results,
    fetch_source_result,
    generate_outputs,
    load_sources,
    media_type_from_extension,
    next_check_at_from_interval,
    normalize_feed_item,
    notice_to_feed_item,
    outputs_match_source_metadata,
    should_write_public_outputs,
    size_budget_check,
    state_items_by_id,
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


def test_notice_to_feed_item_redacts_sensitive_query_values_from_preview_text():
    notice = Notice(
        source_id="pnu-main-notice",
        source_name="부산대 대학공지",
        notice_id="pnu-main-notice:secret",
        title="공지 제목",
        url="https://www.pusan.ac.kr/notice?secret=keep-in-url",
        published_at="2026-06-02",
        snippet=(
            "신청 링크 https://plato.pusan.ac.kr/local/apply.php"
            "?id=5818&secret=8rToK&token=abc123"
        ),
        attachments=[],
        tags=["pnu", "official"],
        content_hash="abc123",
    )

    item = notice_to_feed_item(notice, "2026-06-03T12:00:00+09:00")

    assert item["url"] == "https://www.pusan.ac.kr/notice?secret=keep-in-url"
    assert "secret=8rToK" not in item["summary"]
    assert "token=abc123" not in item["summary"]
    assert "secret=[redacted]" in item["summary"]
    assert "token=[redacted]" in item["summary"]
    assert item["_pnu"]["snippet"] == item["summary"]


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


def test_build_latest_sorts_items_by_published_date_desc():
    source = _source()
    old_notice = _notice(source, "1", "2026-06-01")
    new_notice = _notice(source, "2", "2026-06-03")
    result = _result(source, "2026-06-03T12:00:00+09:00", [old_notice, new_notice])

    latest = build_latest(
        [result],
        "2026-06-03T12:00:00+09:00",
        "https://feeds.example.test",
    )

    assert latest["version"] == JSON_FEED_VERSION
    assert latest["home_page_url"] == "https://feeds.example.test"
    assert latest["feed_url"] == "https://feeds.example.test/latest.json"
    assert latest["_pnu"]["schema_version"] == "0.1"
    assert latest["_pnu"]["index_url"] == "https://feeds.example.test/index.json"
    assert latest["_pnu"]["events_url"] == "https://feeds.example.test/events.json"
    assert latest["_pnu"]["rss_url"] == "https://feeds.example.test/rss.xml"
    assert latest["_pnu"]["schema_url"] == (
        "https://feeds.example.test/schema/latest.schema.json"
    )
    assert latest["_pnu"]["source_count"] == 1
    assert latest["_pnu"]["item_count"] == 2
    assert [item["id"] for item in latest["items"]] == [
        "pnu-main-notice:2",
        "pnu-main-notice:1",
    ]
    assert "not operated by Pusan National University" in latest["description"]
    assert latest["items"][0]["date_published"] == "2026-06-03T00:00:00+09:00"


def test_build_latest_limits_public_items_without_source_quota():
    source_a = _source("source-a")
    source_b = _source("source-b")
    checked_at = "2026-06-03T12:00:00+09:00"
    result_a = _result(
        source_a,
        checked_at,
        [
            _notice(source_a, "1", "2026-06-01"),
            _notice(source_a, "3", "2026-06-03"),
        ],
    )
    result_b = _result(
        source_b,
        checked_at,
        [_notice(source_b, "2", "2026-06-02")],
    )

    latest = build_latest(
        [result_a, result_b],
        checked_at,
        "https://feeds.example.test",
        item_limit=2,
    )

    assert latest["_pnu"]["item_count"] == 2
    assert latest["_pnu"]["total_item_count"] == 3
    assert latest["_pnu"]["item_limit"] == 2
    assert [item["id"] for item in latest["items"]] == [
        "source-a:3",
        "source-b:2",
    ]


def test_build_rss_creates_rss_compatibility_feed():
    source = _source()
    result = _result(
        source,
        "2026-06-03T12:00:00+09:00",
        [_notice(source, "1", "2026-06-03", snippet="짧은 미리보기")],
    )
    latest = build_latest(
        [result],
        "2026-06-03T12:00:00+09:00",
        "https://feeds.example.test",
    )

    rss = build_rss(latest)
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


def test_normalize_feed_item_redacts_cached_preview_text():
    item = {
        "id": "pnu-main-notice:1",
        "url": "https://www.pusan.ac.kr/notice",
        "title": "공지",
        "content_text": "old",
        "summary": "https://example.test/apply?secret=abc",
        "_pnu": {
            "snippet": "https://example.test/apply?token=def",
        },
    }

    normalized = normalize_feed_item(item)

    assert normalized["summary"] == "https://example.test/apply?secret=[redacted]"
    assert normalized["_pnu"]["snippet"] == (
        "https://example.test/apply?token=[redacted]"
    )


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
    assert status["degraded_source_count"] == 1
    assert status["ok_source_count"] == 1
    assert status["skipped_source_count"] == 0
    assert status["error_source_count"] == 1
    assert status["status_counts"] == {"ok": 1, "error": 1}
    assert status["sources"][0]["status"] == "ok"
    assert status["sources"][1]["status"] == "error"
    assert status["sources"][1]["last_success_at"] is None
    assert status["sources"][1]["last_error_at"] == checked_at
    assert status["sources"][1]["status"] == "error"
    assert status["sources"][1]["error_type"] == "timeout"
    assert status["sources"][1]["error"] == "network timeout"


def test_build_status_includes_source_duration_diagnostics():
    checked_at = "2026-06-03T12:00:00+09:00"
    source = _source()

    status = build_status(
        [
            SourceResult(
                source=source,
                checked_at=checked_at,
                items=[],
                last_success_at=checked_at,
                status="ok",
                duration_ms=123,
            )
        ],
        checked_at,
    )

    assert status["sources"][0]["duration_ms"] == 123


def test_public_source_preserves_optional_websquare_filters():
    source = PublicSource.from_json(
        {
            "id": "pnu-lei-korean-course-notices",
            "name": "부산대 언어교육원 한국어과정 공지사항",
            "adapter": "websquare-js-board",
            "official_url": "https://lei.pusan.ac.kr/page?menuCD=000000000000226",
            "category": "language_education_notice",
            "poll_interval_minutes": 30,
            "public_only": True,
            "tags": ["pnu", "official"],
            "menu_cd": "000000000000226",
            "cate_type_seq": "9",
            "mainbbs_tab_index": "0",
        }
    )

    adapter_source = source.to_adapter_source()

    assert adapter_source.menu_cd == "000000000000226"
    assert adapter_source.cate_type_seq == "9"
    assert adapter_source.mainbbs_tab_index == "0"


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
    assert status["degraded_source_count"] == 1
    assert status["skipped_source_count"] == 2
    assert status["poll_interval_skipped_source_count"] == 1
    assert status["backoff_source_count"] == 1
    assert status["error_source_count"] == 0
    assert status["status_counts"] == {"ok": 1, "skipped": 2}
    assert status["skipped_reason_counts"] == {
        "backoff": 1,
        "poll_interval": 1,
    }


def test_build_run_diff_reports_added_updated_and_removed_items():
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

    run_diff = build_run_diff(old_state, new_state)

    assert run_diff["run_diff_scope"] == "latest_generator_run"
    assert run_diff["durable_history"] is False
    assert run_diff["removed_semantics"] == (
        "missing_from_current_generator_state_not_official_deletion"
    )
    assert run_diff["added_count"] == 1
    assert run_diff["updated_count"] == 1
    assert run_diff["removed_count"] == 1
    assert run_diff["generated_at"] == new_checked_at
    assert run_diff["previous_generated_at"] == old_checked_at
    assert run_diff["added"][0]["id"] == "pnu-main-notice:new"
    assert run_diff["updated"][0]["id"] == "pnu-main-notice:changed"
    assert run_diff["removed"][0]["id"] == "pnu-main-notice:old"


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
    assert generated["duplicates"]["groups"][0]["canonical_item_id"] == (
        "pnu-main-notice:1"
    )
    latest_items = {
        item["id"]: item
        for item in generated["latest"]["items"]
    }
    assert latest_items["pnu-main-notice:1"]["_pnu"]["same_notice_group_id"]
    assert latest_items["pnu-main-notice:1"]["_pnu"]["is_canonical"] is True
    assert latest_items["pnu-onestop-notices:1"]["_pnu"]["is_canonical"] is False
    assert "scholarship" in latest_items["pnu-main-notice:1"]["_pnu"]["topics"]
    assert generated["baseline_source_ids"] == [
        "pnu-main-notice",
        "pnu-onestop-notices",
    ]


def test_generate_outputs_keeps_run_diff_state_and_duplicates_full_when_feed_is_limited(
    tmp_path,
    monkeypatch,
):
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
                notice_id=f"{source.id}:old-duplicate",
                title="공통 장학 공지",
                url=f"https://example.test/{source.id}/old-duplicate",
                published_at="2026-05-01",
                snippet=None,
                attachments=[],
                tags=source.tags,
                content_hash=f"{source.id}:old-duplicate",
            ),
            Notice(
                source_id=source.id,
                source_name=source.name,
                notice_id=f"{source.id}:new",
                title=f"{source.id} 최신 공지",
                url=f"https://example.test/{source.id}/new",
                published_at="2026-06-04",
                snippet=None,
                attachments=[],
                tags=source.tags,
                content_hash=f"{source.id}:new",
            ),
        ]

    monkeypatch.setattr(generator, "fetch_source", fake_fetch_source)

    generated = generate_outputs(
        sources_path=sources_path,
        state_path=state_path,
        limit=20,
        public_base_url="https://feeds.example.test",
        now=datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        feed_item_limit=2,
    )

    assert generated["latest"]["_pnu"]["item_count"] == 2
    assert generated["latest"]["_pnu"]["total_item_count"] == 4
    assert sorted(generated["run_diff"]["added"][index]["id"] for index in range(4)) == [
        "pnu-main-notice:new",
        "pnu-main-notice:old-duplicate",
        "pnu-onestop-notices:new",
        "pnu-onestop-notices:old-duplicate",
    ]
    state_items = [
        item["id"]
        for source in generated["state"]["sources"].values()
        for item in source["items"]
    ]
    assert len(state_items) == 4
    assert generated["duplicates"]["group_count"] == 1
    assert generated["duplicates"]["groups"][0]["item_ids"] == [
        "pnu-main-notice:old-duplicate",
        "pnu-onestop-notices:old-duplicate",
    ]


def test_generate_outputs_includes_run_diagnostics(tmp_path, monkeypatch):
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
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    def fake_fetch_source(source, limit, cached_items=None, checked_at=None):
        return [_notice(source, "1", "2026-06-04")]

    monkeypatch.setattr(generator, "fetch_source", fake_fetch_source)

    generated = generate_outputs(
        sources_path=sources_path,
        state_path=state_path,
        limit=20,
        public_base_url="https://feeds.example.test",
        now=datetime(2026, 6, 5, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        fetch_concurrency=4,
        per_host_concurrency=1,
    )

    diagnostics = generated["diagnostics"]
    assert diagnostics["source_count"] == 1
    assert diagnostics["fetched_source_count"] == 1
    assert diagnostics["skipped_source_count"] == 0
    assert diagnostics["error_source_count"] == 0
    assert diagnostics["fetch_concurrency"] == 4
    assert diagnostics["per_host_concurrency"] == 1
    assert diagnostics["total_item_count"] == 1
    assert diagnostics["latest_item_count"] == 1
    assert diagnostics["duration_ms"] >= 0
    assert diagnostics["source_results"][0]["id"] == "pnu-main-notice"
    assert diagnostics["source_results"][0]["duration_ms"] >= 0


def test_fetch_source_results_preserves_source_registry_order(monkeypatch):
    source_a = _source("source-a")
    source_b = _source("source-b")

    def fake_fetch_source_result(source, limit, checked_at, state):
        if source.id == "source-a":
            time.sleep(0.02)
        return SourceResult(
            source=source,
            checked_at=checked_at,
            items=[],
            last_success_at=checked_at,
            status="ok",
        )

    monkeypatch.setattr(generator, "fetch_source_result", fake_fetch_source_result)

    results = fetch_source_results(
        [source_a, source_b],
        limit=20,
        generated_at="2026-06-05T12:00:00+09:00",
        state={},
        fetch_concurrency=2,
        per_host_concurrency=2,
    )

    assert [result.source.id for result in results] == ["source-a", "source-b"]


def test_fetch_source_results_limits_same_host_concurrency(monkeypatch):
    source_a = _source("source-a")
    source_b = _source("source-b")
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_fetch_source_result(source, limit, checked_at, state):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return SourceResult(
            source=source,
            checked_at=checked_at,
            items=[],
            last_success_at=checked_at,
            status="ok",
        )

    monkeypatch.setattr(generator, "fetch_source_result", fake_fetch_source_result)

    fetch_source_results(
        [source_a, source_b],
        limit=20,
        generated_at="2026-06-05T12:00:00+09:00",
        state={},
        fetch_concurrency=2,
        per_host_concurrency=1,
    )

    assert max_active == 1


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


def test_build_public_index_combines_status_archives_dedupe_and_diagnostics():
    latest = {
        "home_page_url": "https://feeds.example.test",
        "_pnu": {
            "generated_at": "2026-06-05T12:00:00+09:00",
            "item_count": 2,
            "total_item_count": 4,
            "item_limit": 150,
        },
    }
    status = {
        "overall_status": "partial",
        "source_count": 2,
        "ok_source_count": 1,
        "skipped_source_count": 0,
        "poll_interval_skipped_source_count": 0,
        "backoff_source_count": 0,
        "error_source_count": 1,
        "degraded_source_count": 1,
        "failed_source_count": 1,
        "status_counts": {"ok": 1, "error": 1},
        "skipped_reason_counts": {},
        "sources": [{"id": "source-a", "status": "ok"}],
    }
    run_diff = {
        "run_diff_scope": "latest_generator_run",
        "added_count": 1,
    }
    duplicates = {
        "policy": {"scope": "metadata_only_high_confidence"},
        "group_count": 1,
        "groups": [{"id": "same_notice:1"}],
    }
    archives = {
        "archive_url_pattern": "./archive/{YYYY-MM}.json",
        "months": [{"month": "2026-06", "url": "./archive/2026-06.json"}],
    }
    events = {
        "event_count": 3,
        "total_event_count": 5,
        "event_limit": 1000,
        "latest_event_id": "event-5",
        "oldest_event_id": "event-3",
        "oldest_seen_at": "2026-06-05T11:00:00+09:00",
        "latest_seen_at": "2026-06-05T12:00:00+09:00",
        "is_truncated": True,
    }

    index = build_public_index(
        latest=latest,
        status=status,
        run_diff=run_diff,
        duplicates=duplicates,
        archives=archives,
        events=events,
        diagnostics={"duration_ms": 25},
        public_base_url="https://feeds.example.test",
    )

    assert index["home_page_url"] == "https://feeds.example.test"
    assert index["endpoints"]["latest"] == "https://feeds.example.test/latest.json"
    assert index["status"]["overall_status"] == "partial"
    assert index["status"]["degraded_source_count"] == 1
    assert index["status"]["status_counts"] == {"ok": 1, "error": 1}
    assert index["event_stream"]["latest_event_id"] == "event-5"
    assert index["archives"]["months"][0]["url"] == "./archive/2026-06.json"
    assert index["same_notice_groups"] == [{"id": "same_notice:1"}]
    assert index["diagnostics"]["latest_run_diff"]["added_count"] == 1
    assert index["diagnostics"]["run"]["duration_ms"] == 25


def test_build_state_stores_compact_items_and_hydrates_cached_items():
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
    assert source_state["baseline_completed_at"] == checked_at
    assert source_state["last_success_at"] == checked_at
    assert source_state["last_error_at"] is None
    assert source_state["status"] == "ok"
    assert source_state["next_check_at"] == "2026-06-04T12:30:00+09:00"
    assert source_state["items"][0]["id"] == "pnu-main-notice:1"
    assert "content_text" not in source_state["items"][0]
    assert "date_published" not in source_state["items"][0]
    assert "source_category" not in source_state["items"][0]["_pnu"]
    assert "topics" not in source_state["items"][0]["_pnu"]

    hydrated = state_items_by_id(state)["pnu-main-notice:1"]
    assert hydrated["content_text"] == CONTENT_TEXT_NOTICE
    assert hydrated["date_published"] == "2026-06-04T00:00:00+09:00"
    assert hydrated["_pnu"]["source_name"] == "부산대 대학공지"
    assert hydrated["_pnu"]["source_category"] == "university_notice"
    assert hydrated["_pnu"]["topics"] == ["academic"]


def test_build_state_diagnostics_reports_compact_state_size():
    source = _source()
    checked_at = "2026-06-04T12:00:00+09:00"

    generated = build_state(
        [_result(source, checked_at, [_notice(source, "1", "2026-06-04")])],
        checked_at,
    )

    diagnostics = generator.build_state_diagnostics(generated)

    assert diagnostics["source_count"] == 1
    assert diagnostics["item_count"] == 1
    assert diagnostics["estimated_compact_json_bytes"] > 0


def test_build_output_file_diagnostics_reports_archive_and_largest_files(tmp_path):
    output_dir = tmp_path / "public"
    archive_dir = output_dir / "archive"
    archive_dir.mkdir(parents=True)
    (output_dir / "latest.json").write_text("{}", encoding="utf-8")
    (archive_dir / "2026-06.json").write_text("archive", encoding="utf-8")
    (output_dir / "rss.xml").write_text("rss", encoding="utf-8")

    diagnostics = build_output_file_diagnostics(output_dir)

    assert diagnostics["file_count"] == 3
    assert diagnostics["archive_file_count"] == 1
    assert diagnostics["archive_total_bytes"] == len("archive")
    assert diagnostics["largest_files"][0]["path"] == "archive/2026-06.json"


def test_size_budget_diagnostics_fails_when_budget_is_exceeded(tmp_path, monkeypatch):
    output_dir = tmp_path / "public"
    output_dir.mkdir()
    (output_dir / "latest.json").write_text("large", encoding="utf-8")
    state_path = tmp_path / "feed-state.json"
    state_path.write_text("state", encoding="utf-8")
    monkeypatch.setitem(
        generator.SIZE_BUDGETS,
        "public_total",
        {"warning_bytes": 1, "failure_bytes": 2},
    )

    diagnostics = build_size_budget_diagnostics(output_dir, state_path)

    assert diagnostics["overall_status"] == "fail"
    assert [
        check["name"]
        for check in diagnostics["checks"]
        if check["status"] == "fail"
    ] == ["public_total"]
    try:
        assert_size_budget(diagnostics)
    except ValueError as error:
        assert "public_total" in str(error)
    else:
        raise AssertionError("expected size budget failure")


def test_size_budget_check_warns_before_failure():
    assert size_budget_check("x", 5, 10, 20, "bytes")["status"] == "ok"
    assert size_budget_check("x", 10, 10, 20, "bytes")["status"] == "warn"
    assert size_budget_check("x", 20, 10, 20, "bytes")["status"] == "fail"


def test_check_size_budget_cli_prints_feed_health_snapshot(tmp_path, capsys):
    output_dir = tmp_path / "public"
    output_dir.mkdir()
    state_path = tmp_path / "feed-state.json"
    state_path.write_text("{}", encoding="utf-8")
    _write_json(
        output_dir / "index.json",
        {
            "generated_at": "2026-06-06T12:00:00+09:00",
            "status": {
                "overall_status": "ok",
                "source_count": 1,
                "ok_source_count": 1,
                "skipped_source_count": 0,
                "poll_interval_skipped_source_count": 0,
                "backoff_source_count": 0,
                "error_source_count": 0,
                "degraded_source_count": 0,
                "sources": [{"id": "source-a", "status": "ok"}],
            },
            "event_stream": {"event_count": 1},
            "latest": {"item_count": 1},
            "same_notice_group_count": 0,
        },
    )
    _write_json(
        output_dir / "events.json",
        {
            "event_count": 1,
            "total_event_count": 1,
            "event_limit": 1000,
            "is_truncated": False,
            "events": [{"event_id": "event-1"}],
        },
    )
    _write_json(
        output_dir / "latest.json",
        {
            "_pnu": {"item_count": 1, "total_item_count": 1},
            "items": [{"id": "source-a:1"}],
        },
    )

    result = generator.main(
        [
            "--check-size-budget",
            "--output-dir",
            str(output_dir),
            "--state",
            str(state_path),
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert "PNU Public Notice Feed health snapshot" in output
    assert "result: ok" in output


def test_should_write_public_outputs_skips_when_no_notice_or_status_change(tmp_path):
    output_dir = tmp_path / "public"
    state_path = tmp_path / "feed-state.json"
    output_dir.mkdir()
    state_path.write_text("{}", encoding="utf-8")
    latest = {
        "feed_url": "https://feeds.example.test/latest.json",
        "_pnu": {
            "sources": [
                {
                    "id": "source-a",
                    "name": "Source A",
                    "official_url": "https://example.test/a",
                    "adapter": "k2web-board",
                    "category": "notice",
                    "poll_interval_minutes": 30,
                    "public_only": True,
                    "access_policy": "public_official_url_only",
                }
            ]
        },
        "items": [
            {
                "id": "source-a:1",
                "url": "https://example.test/a/1",
                "title": "Notice",
                "content_text": CONTENT_TEXT_NOTICE,
                "summary": None,
                "_pnu": {"source_id": "source-a"},
            }
        ],
    }
    index = {
        "home_page_url": "https://feeds.example.test",
        "archives": {"months": []},
        "status": {
            "overall_status": "ok",
            "source_count": 1,
            "ok_source_count": 1,
            "skipped_source_count": 0,
            "poll_interval_skipped_source_count": 0,
            "backoff_source_count": 0,
            "error_source_count": 0,
            "degraded_source_count": 0,
            "failed_source_count": 0,
            "status_counts": {"ok": 1},
            "skipped_reason_counts": {},
            "sources": [{"id": "source-a", "status": "ok", "error_count": 0}],
        },
    }
    for name, value in {
        "latest.json": latest,
        "index.json": index,
        "events.json": {
            "event_stream_version": generator.EVENT_STREAM_VERSION,
            "events": [],
        },
    }.items():
        (output_dir / name).write_text(json.dumps(value), encoding="utf-8")
    (output_dir / "rss.xml").write_text("<rss></rss>", encoding="utf-8")
    (output_dir / "index.html").write_text("<html></html>", encoding="utf-8")

    generated = {
        "latest": latest,
        "run_diff": {"added_count": 0, "updated_count": 0, "removed_count": 0},
        "status": {
            **index["status"],
            "sources": [
                {
                    **index["status"]["sources"][0],
                    "status": "skipped",
                    "skipped_reason": "poll_interval",
                    "last_checked_at": "2026-06-05T12:00:00+09:00",
                    "duration_ms": 123,
                }
            ],
        },
    }

    assert not should_write_public_outputs(
        output_dir,
        state_path,
        generated,
        "https://feeds.example.test",
    )


def test_should_write_public_outputs_writes_when_event_stream_version_is_old(tmp_path):
    output_dir = tmp_path / "public"
    state_path = tmp_path / "feed-state.json"
    output_dir.mkdir()
    state_path.write_text("{}", encoding="utf-8")
    latest = {
        "feed_url": "https://feeds.example.test/latest.json",
        "_pnu": {"sources": []},
        "items": [],
    }
    index = {
        "home_page_url": "https://feeds.example.test",
        "archives": {"months": []},
        "status": {
            "overall_status": "ok",
            "source_count": 0,
            "failed_source_count": 0,
            "sources": [],
        },
    }
    for name, value in {
        "latest.json": latest,
        "index.json": index,
        "events.json": {"event_stream_version": "0.3", "events": []},
    }.items():
        (output_dir / name).write_text(json.dumps(value), encoding="utf-8")
    (output_dir / "rss.xml").write_text("<rss></rss>", encoding="utf-8")
    (output_dir / "index.html").write_text("<html></html>", encoding="utf-8")

    assert should_write_public_outputs(
        output_dir,
        state_path,
        {
            "latest": latest,
            "run_diff": {"added_count": 0, "updated_count": 0, "removed_count": 0},
            "status": index["status"],
        },
        "https://feeds.example.test",
    )


def test_should_write_public_outputs_writes_when_notice_changes(tmp_path):
    output_dir = tmp_path / "public"
    state_path = tmp_path / "feed-state.json"
    output_dir.mkdir()
    state_path.write_text("{}", encoding="utf-8")

    assert should_write_public_outputs(
        output_dir,
        state_path,
        {
            "latest": {"_pnu": {"sources": []}},
            "run_diff": {"added_count": 1},
            "status": {"sources": []},
        },
        "https://feeds.example.test",
    )


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
    assert result.items[0]["id"] == cached_item["id"]
    assert result.items[0]["title"] == cached_item["title"]
    assert result.items[0]["_pnu"]["content_hash"] == "cached-hash"
    assert result.items[0]["_pnu"]["source_category"] == "notice"
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
    assert result.items[0]["id"] == cached_item["id"]
    assert result.items[0]["title"] == cached_item["title"]
    assert result.items[0]["_pnu"]["source_category"] == "university_notice"
    assert result.items[0]["_pnu"]["topics"] == ["academic"]


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

    sync_static_assets(output_dir, source_path, "https://feeds.example.test/pnu")

    assert not (output_dir / "sources.json").exists()
    assert (output_dir / "index.html").exists()
    assert (output_dir / "openapi.json").exists()
    assert (output_dir / "llms.txt").exists()
    assert (output_dir / "robots.txt").exists()
    assert (output_dir / "sitemap.xml").exists()
    assert (output_dir / "schema" / "index.schema.json").exists()
    assert (output_dir / "schema" / "latest.schema.json").exists()

    index_html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://feeds.example.test/pnu/">' in index_html
    assert '"@type": "Dataset"' in index_html
    assert "부산대학교" in index_html
    assert "https://example.invalid" not in index_html
    assert "Sitemap: https://feeds.example.test/pnu/sitemap.xml" in (
        output_dir / "robots.txt"
    ).read_text(encoding="utf-8")
    assert "https://feeds.example.test/pnu/events.json" in (
        output_dir / "sitemap.xml"
    ).read_text(encoding="utf-8")


def test_outputs_match_source_metadata_detects_registry_changes(tmp_path):
    output_dir = tmp_path / "public"
    output_dir.mkdir()
    old_latest = {
        "_pnu": {
            "sources": [
                {
                    "id": "source-a",
                    "name": "Source A",
                    "official_url": "https://example.test/a",
                    "adapter": "k2web-board",
                    "category": "notice",
                    "poll_interval_minutes": 30,
                    "public_only": True,
                    "access_policy": "public_official_url_only",
                    "last_checked_at": "2026-06-05T11:00:00+09:00",
                    "last_success_at": "2026-06-05T11:00:00+09:00",
                }
            ]
        }
    }
    new_latest = {
        "_pnu": {
            "sources": [
                {
                    **old_latest["_pnu"]["sources"][0],
                    "poll_interval_minutes": 60,
                    "last_checked_at": "2026-06-05T12:00:00+09:00",
                }
            ]
        }
    }
    (output_dir / "latest.json").write_text(
        json.dumps(old_latest),
        encoding="utf-8",
    )

    assert not outputs_match_source_metadata(output_dir, new_latest)
    assert outputs_match_source_metadata(output_dir, old_latest)


def test_sources_registry_uses_polling_tiers():
    data = json.loads((Path(__file__).resolve().parents[1] / "sources.json").read_text(
        encoding="utf-8",
    ))
    intervals = {
        source["id"]: source["poll_interval_minutes"]
        for source in data["sources"]
    }

    assert intervals["pnu-main-notice"] == 30
    assert intervals["pnu-onestop-notices"] == 30
    assert intervals["pnu-onestop-scholarship"] == 30
    assert len(set(intervals.values())) > 1
    assert all(interval >= 30 for interval in intervals.values())


def test_sources_registry_includes_academic_unit_sources_without_duplicate_urls():
    data = json.loads((Path(__file__).resolve().parents[1] / "sources.json").read_text(
        encoding="utf-8",
    ))
    academic_sources = [
        source
        for source in data["sources"]
        if source["id"].startswith("pnu-academic-")
    ]
    urls = [source["official_url"] for source in academic_sources]

    assert len(academic_sources) >= 250
    assert all(
        source["adapter"] in {"k2web-board", "legacy-php-board"}
        for source in academic_sources
    )
    assert all(
        source["official_url"].startswith("https://me.pusan.ac.kr/")
        for source in academic_sources
        if source["adapter"] == "legacy-php-board"
    )
    assert all(source["poll_interval_minutes"] == 180 for source in academic_sources)
    assert len(urls) == len(set(urls))


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


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
