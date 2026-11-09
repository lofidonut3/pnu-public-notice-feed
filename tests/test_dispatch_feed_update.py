from scripts.dispatch_feed_update import build_dispatch_payload
from urllib.error import HTTPError
import pytest
from scripts import dispatch_feed_update as dispatch


def test_build_dispatch_payload_uses_cursor_as_wake_hint():
    payload = build_dispatch_payload(
        {
            "generated_at": "2026-07-19T12:00:00+09:00",
            "endpoints": {
                "events": "https://feeds.example.test/events.json",
                "index": "https://feeds.example.test/index.json",
            },
            "event_stream": {
                "latest_event_id": "event-2",
                "latest_seen_at": "2026-07-19T12:00:00+09:00",
            },
            "diagnostics": {
                "latest_run_diff": {
                    "added_count": 1,
                    "updated_count": 2,
                }
            },
        }
    )

    assert payload == {
        "generated_at": "2026-07-19T12:00:00+09:00",
        "latest_event_id": "event-2",
        "latest_seen_at": "2026-07-19T12:00:00+09:00",
        "added_count": 1,
        "updated_count": 2,
        "events_url": "https://feeds.example.test/events.json",
        "index_url": "https://feeds.example.test/index.json",
    }


def test_build_dispatch_payload_skips_metadata_only_run():
    assert build_dispatch_payload(
        {
            "diagnostics": {
                "latest_run_diff": {"added_count": 0, "updated_count": 0}
            }
        }
    ) is None


def test_permanent_auth_failure_is_not_retried_or_leaked(monkeypatch):
    calls=[]
    def reject(request,timeout):
        calls.append(request.full_url)
        raise HTTPError(request.full_url,401,'Unauthorized',{},None)
    monkeypatch.setattr(dispatch,'urlopen',reject)
    monkeypatch.setattr(dispatch.time,'sleep',lambda _: (_ for _ in ()).throw(AssertionError('permanent auth error retried')))
    with pytest.raises(RuntimeError,match='HTTP 401') as failure:
        dispatch.dispatch_repository_event('owner/repo','synthetic-test-secret',{})
    assert len(calls)==1
    assert 'synthetic-test-secret' not in str(failure.value)
