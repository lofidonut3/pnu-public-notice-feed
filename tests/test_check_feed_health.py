import json

from scripts.check_feed_health import (
    HealthReport,
    SizeSummary,
    Thresholds,
    build_report,
    check_feed_health,
)


def test_build_report_treats_poll_interval_skip_as_healthy():
    report = build_report(
        _index(
            status={
                "overall_status": "ok",
                "source_count": 2,
                "ok_source_count": 1,
                "skipped_source_count": 1,
                "poll_interval_skipped_source_count": 1,
                "backoff_source_count": 0,
                "error_source_count": 0,
                "degraded_source_count": 0,
                "sources": [
                    {"id": "source-a", "status": "ok"},
                    {
                        "id": "source-b",
                        "status": "skipped",
                        "skipped_reason": "poll_interval",
                    },
                ],
            }
        ),
        _events(),
        _latest(),
        _sizes(),
        _thresholds(),
    )

    assert report.issues == []
    assert report.warnings == []
    assert any("degraded 0" in line for line in report.lines)
    assert report.lines[-1] == "result: ok"


def test_build_report_fails_when_degraded_sources_exceed_threshold():
    report = build_report(
        _index(
            status={
                "overall_status": "partial",
                "source_count": 1,
                "ok_source_count": 0,
                "skipped_source_count": 1,
                "poll_interval_skipped_source_count": 0,
                "backoff_source_count": 1,
                "error_source_count": 0,
                "degraded_source_count": 1,
                "sources": [
                    {
                        "id": "source-a",
                        "status": "skipped",
                        "skipped_reason": "backoff",
                        "error_count": 3,
                    }
                ],
            }
        ),
        _events(),
        _latest(),
        _sizes(),
        _thresholds(max_degraded_sources=0),
    )

    assert report.issues == ["degraded_source_count 1 exceeds 0"]
    assert any("source-a" in line for line in report.lines)
    assert report.lines[-1] == "result: fail"


def test_build_report_detects_event_count_mismatch():
    events = _events()
    events = {**events, "event_count": 2}

    report = build_report(
        _index(),
        events,
        _latest(),
        _sizes(),
        _thresholds(),
    )

    assert "events.event_count does not match events array length" in report.issues


def test_check_feed_health_loads_local_public_files(tmp_path):
    public_dir = tmp_path / "public"
    public_dir.mkdir()
    state_path = tmp_path / "feed-state.json"
    state_path.write_text("{}", encoding="utf-8")
    _write_json(public_dir / "index.json", _index())
    _write_json(public_dir / "events.json", _events())
    _write_json(public_dir / "latest.json", _latest())

    report = check_feed_health(
        public_dir=public_dir,
        state_path=state_path,
        base_url=None,
        timeout_seconds=1,
        thresholds=_thresholds(),
    )

    assert isinstance(report, HealthReport)
    assert report.issues == []
    assert any("public_total:" in line for line in report.lines)
    assert any("state:" in line for line in report.lines)


def _index(status=None):
    status = status or {
        "overall_status": "ok",
        "source_count": 1,
        "ok_source_count": 1,
        "skipped_source_count": 0,
        "poll_interval_skipped_source_count": 0,
        "backoff_source_count": 0,
        "error_source_count": 0,
        "degraded_source_count": 0,
        "sources": [{"id": "source-a", "status": "ok"}],
    }
    return {
        "generated_at": "2026-06-06T12:00:00+09:00",
        "status": status,
        "event_stream": {"event_count": 1},
        "latest": {"item_count": 1},
        "same_notice_group_count": 0,
    }


def _events():
    return {
        "event_count": 1,
        "total_event_count": 1,
        "event_limit": 1000,
        "is_truncated": False,
        "events": [{"event_id": "event-1"}],
    }


def _latest():
    return {
        "_pnu": {
            "item_count": 1,
            "total_item_count": 1,
        },
        "items": [{"id": "source-a:1"}],
    }


def _sizes():
    return SizeSummary(
        public_total_bytes=100,
        archive_total_bytes=50,
        state_bytes=10,
        index_bytes=10,
        events_bytes=20,
        latest_bytes=30,
    )


def _thresholds(
    max_degraded_sources=100,
    max_backoff_sources=100,
    max_error_sources=50,
):
    return Thresholds(
        max_degraded_sources=max_degraded_sources,
        max_backoff_sources=max_backoff_sources,
        max_error_sources=max_error_sources,
        max_public_total_mib=500,
        max_state_mib=50,
        min_event_count=1,
        fail_on_truncated_events=False,
    )


def _write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
