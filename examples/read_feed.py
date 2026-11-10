#!/usr/bin/env python3
"""Read the public catalog, a topic preview, or a page after a saved cursor."""

import argparse
import hashlib
import json
import sys
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import urlopen


BASE_URL = "https://lofidonut3.github.io/pnu-public-notice-feed/"


def read_json(url, checksum=None):
    with urlopen(url, timeout=30) as response:
        body = response.read()
    if checksum and hashlib.sha256(body).hexdigest() != checksum:
        raise ValueError("Archive checksum mismatch. Retry from the same cursor.")
    return json.loads(body)


def event_key(event):
    return event["seen_at"], event["event_id"]


def resume(catalog_url, catalog, cursor, limit):
    events_url = urljoin(catalog_url, catalog["events_url"])
    recent = read_json(events_url)
    if (recent["checked_at"], recent["latest_event_id"]) != (
        catalog["checked_at"], catalog["latest_event_id"]
    ):
        raise ValueError("Catalog and event generations differ. Retry from the same cursor.")
    events = recent["events"]
    for index, event in enumerate(events):
        if event_key(event) == cursor:
            return events[index + 1:index + limit + 2]

    # On an ID miss, recover from event-bearing archives, including equal timestamps.
    index_url = urljoin(catalog_url, catalog["index_url"])
    index = read_json(index_url)
    if index["generated_at"] != catalog["checked_at"]:
        raise ValueError("Catalog and archive index generations differ. Retry from the same cursor.")
    found = False
    page = []
    for month in index["archives"]["months"]:
        if not month["event_count"]:
            continue
        archive = read_json(urljoin(index_url, month["url"]), month["sha256"])
        found = found or any(event_key(event) == cursor for event in archive["events"])
        # Keep only the first page and a look-ahead item, even during a long catch-up.
        next_events = {event["event_id"]: event for event in page}
        for event in archive["events"]:
            if event_key(event) > cursor:
                next_events[event["event_id"]] = event
        page = sorted(next_events.values(), key=event_key)[:limit + 1]
    if not found:
        raise ValueError("Saved event not found. Keep the cursor and inspect the archive.")
    return page


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--limit", type=int, default=5, help="Number of results (1 to 20)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--topic", help="Topic ID from the catalog")
    mode.add_argument("--event-id", help="Exact ID of the last processed event")
    parser.add_argument("--seen-at", help="Observation time of the same event")
    args = parser.parse_args()
    if not 1 <= args.limit <= 20 or bool(args.event_id) != bool(args.seen_at):
        parser.error("Use a limit from 1 to 20 and pass both cursor fields together.")

    catalog_url = urljoin(args.base_url.rstrip("/") + "/", "agent.json")
    try:
        catalog = read_json(catalog_url)
        result = catalog
        if args.topic:
            topic = next((t for t in catalog["topics"] if t["id"] == args.topic), None)
            if topic is None:
                raise ValueError("Unknown topic. Run without --topic to list available topics.")
            result = read_json(urljoin(catalog_url, topic["url"]))
            if result["checked_at"] != catalog["checked_at"]:
                raise ValueError("Catalog and topic generations differ. Retry the lookup.")
            result["is_truncated"] = result["is_truncated"] or len(result["items"]) > args.limit
            result["items"] = result["items"][:args.limit]
            result["item_count"] = len(result["items"])
        elif args.event_id:
            cursor = (args.seen_at, args.event_id)
            page = resume(catalog_url, catalog, cursor, args.limit)
            emitted = page[:args.limit]
            next_seen_at, next_id = event_key(emitted[-1]) if emitted else cursor
            fields = ("event_id", "seen_at", "event_type", "title", "url", "published_at",
                      "source_id", "archive_file", "archive_item_id")
            result = {
                "events": [{key: event[key] for key in fields} for event in emitted],
                "has_more": len(page) > args.limit,
                "next_cursor": {"seen_at": next_seen_at, "event_id": next_id},
            }
        output = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
        sys.stdout.buffer.write(output + b"\n")
    except (URLError, ValueError, KeyError) as error:
        parser.exit(1, f"Could not read feed: {error}\n")


if __name__ == "__main__":
    main()
