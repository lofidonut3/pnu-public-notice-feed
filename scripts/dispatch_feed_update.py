from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_INDEX_PATH = Path("public/index.json")
DEFAULT_EVENT_TYPE = "pnu-feed-updated"
DEFAULT_EVENTS_URL = "https://lofidonut3.github.io/pnu-public-notice-feed/events.json"
DEFAULT_INDEX_URL = "https://lofidonut3.github.io/pnu-public-notice-feed/index.json"


def build_dispatch_payload(index: dict) -> dict | None:
    diagnostics = index.get("diagnostics") or {}
    run_diff = diagnostics.get("latest_run_diff") or {}
    added_count = int(run_diff.get("added_count") or 0)
    updated_count = int(run_diff.get("updated_count") or 0)
    if added_count + updated_count == 0:
        return None

    event_stream = index.get("event_stream") or {}
    endpoints = index.get("endpoints") or {}
    return {
        "generated_at": index.get("generated_at"),
        "latest_event_id": event_stream.get("latest_event_id"),
        "latest_seen_at": event_stream.get("latest_seen_at"),
        "added_count": added_count,
        "updated_count": updated_count,
        "events_url": endpoints.get("events") or DEFAULT_EVENTS_URL,
        "index_url": endpoints.get("index") or DEFAULT_INDEX_URL,
    }


def dispatch_repository_event(
    repository: str,
    token: str,
    payload: dict,
    *,
    event_type: str = DEFAULT_EVENT_TYPE,
    attempts: int = 3,
) -> None:
    url = f"https://api.github.com/repos/{repository}/dispatches"
    body = json.dumps(
        {"event_type": event_type, "client_payload": payload},
        ensure_ascii=False,
    ).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "pnu-public-notice-feed-dispatch/0.1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                if response.status != 204:
                    raise RuntimeError(f"unexpected dispatch status: {response.status}")
            return
        except (HTTPError, URLError, RuntimeError) as error:
            last_error = error
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"repository dispatch failed after {attempts} attempts: {last_error}")


def main() -> int:
    repository = os.environ.get("WATCH_DISPATCH_REPOSITORY", "").strip()
    token = os.environ.get("WATCH_DISPATCH_TOKEN", "").strip()
    if not repository or not token:
        print("Watch dispatch is not configured; skipping.")
        return 0

    index_path = Path(os.environ.get("FEED_INDEX_PATH", str(DEFAULT_INDEX_PATH)))
    index = json.loads(index_path.read_text(encoding="utf-8"))
    payload = build_dispatch_payload(index)
    if payload is None:
        print("No added or updated notice events; skipping dispatch.")
        return 0

    dispatch_repository_event(repository, token, payload)
    print(
        "Dispatched pnu-feed-updated "
        f"to {repository} at cursor {payload.get('latest_event_id')}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
