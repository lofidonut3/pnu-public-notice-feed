from scripts.dispatch_feed_update import build_dispatch_payload


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
