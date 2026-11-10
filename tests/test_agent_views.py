import json
from pathlib import Path

from pnu_notice_feed import generator
from pnu_notice_feed.types import Notice
from scripts.verify_feed import verify_agent_views


def test_agent_views_use_uncapped_current_items_and_real_publication_heartbeat(tmp_path, monkeypatch):
    registry_path = tmp_path / "sources.json"
    state_path = tmp_path / "state.json"
    output = tmp_path / "public"
    source_ids = ("pnu-main-notice", "pnu-onestop-notices")
    registry_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": source_id,
                        "name": source_id,
                        "official_url": f"https://example.test/{source_id}",
                        "adapter": "pusan-cms-static-board",
                        "category": "notice",
                        "poll_interval_minutes": 30,
                        "public_only": True,
                    }
                    for source_id in source_ids
                ]
            }
        ),
        encoding="utf-8",
    )
    polled_at = "2026-06-05T12:00:00+09:00"
    fetched = []

    def notice(source, key, title, date, preview=None):
        return Notice(
            source_id=source.id,
            source_name=source.name,
            notice_id=f"{source.id}:{key}",
            title=title,
            url=f"https://example.test/{source.id}/{key}",
            published_at=date,
            snippet=preview,
            attachments=[],
            tags=source.tags,
            content_hash=f"{source.id}:{key}",
        )

    def fetch(source, _limit, cached_items=None, checked_at=None):
        fetched.append(source.id)
        common = notice(source, "common", "장학금 공통 선발 공고", "2026-06-03", "요약" * 200)
        if source.id != source_ids[0]:
            return [common]
        return [
            common,
            notice(source, "general", "일반 공지", "2026-06-04"),
            *[
                notice(source, str(n), f"장학금 공고 {n}", "2026-06-01")
                for n in range(21)
            ],
        ]

    monkeypatch.setattr(generator, "iso_now", lambda now=None: polled_at)
    monkeypatch.setattr(generator, "fetch_source", fetch)
    args = [
        "--sources", str(registry_path), "--state", str(state_path),
        "--output-dir", str(output), "--feed-item-limit", "1",
    ]

    def read(path: str) -> dict:
        return json.loads((output / path).read_text(encoding="utf-8"))

    assert generator.main(args) == 0
    events = read("events.json")
    latest_id = events["latest_event_id"]
    assert read("latest.json")["items"][0]["id"] == f"{source_ids[0]}:general"
    topic = read("topics/scholarship.json")
    assert topic["matching_count"] == 22
    assert topic["item_count"] == 20
    assert topic["is_truncated"] is True
    assert topic["items"][0]["id"] == f"{source_ids[0]}:common"
    assert topic["items"][0]["preview"] == "요약" * 120
    assert sum(item["title"] == "장학금 공통 선발 공고" for item in topic["items"]) == 1
    assert read("topics/dormitory.json")["items"] == []
    assert verify_agent_views(output, events) == []

    # A missing additive file is rebuilt on a skipped poll without publishing
    # a new event heartbeat or changing the old consumer's bytes.
    (output / "topics" / "scholarship.json").unlink()
    previous_events = (output / "events.json").read_bytes()
    previous_index = (output / "index.json").read_bytes()
    fetched.clear()
    polled_at = "2026-06-05T12:01:00+09:00"
    assert generator.main(args) == 0
    assert fetched == []
    assert (output / "events.json").read_bytes() == previous_events
    assert (output / "index.json").read_bytes() == previous_index
    assert read("topics/scholarship.json") == topic

    polled_at = "2026-06-05T13:00:00+09:00"
    assert generator.main(args) == 0
    quiet_events = read("events.json")
    assert quiet_events["latest_event_id"] == latest_id
    assert read("agent.json")["checked_at"] == polled_at
    assert read("topics/scholarship.json")["checked_at"] == polled_at
    assert verify_agent_views(output, quiet_events) == []
