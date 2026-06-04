from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .cms_static_board import fetch_cms_static_board
from .onestop_js_board import fetch_onestop_js_board
from .types import Notice, Source

SCHEMA_VERSION = "0.1"
JSON_FEED_VERSION = "https://jsonfeed.org/version/1.1"
FEED_VERSION = "2026-06-04"
DEFAULT_LIMIT = 40
DEFAULT_SNIPPET_LIMIT = 500
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_REGISTRY = PROJECT_ROOT / "sources.json"
DEFAULT_STATE_PATH = PROJECT_ROOT / "cache" / "feed-state.json"
DEFAULT_PUBLIC_BASE_URL = "https://lofidonut3.github.io/pnu-public-notice-feed"
SUPPORTED_ADAPTERS = {"pusan-cms-static-board", "onestop-js-board"}
DISCLAIMER = (
    "Unofficial PNU Public Notice Feed. This project indexes public official "
    "notices and links back to the original sources. It is not operated by "
    "Pusan National University."
)
CONTENT_TEXT_NOTICE = (
    "This feed does not mirror the full notice body. Fetch the original notice "
    "URL for complete content."
)
LLMS_TXT = """# PNU Public Notice Feed

Unofficial public metadata relay for Pusan National University public notices.
This project is not operated by Pusan National University.

## Endpoints

- [JSON Feed](./feed.json): latest normalized public notice metadata.
- [Status](./status.json): source refresh status and failures.
- [Changes](./changes.json): added, updated, and removed item summaries since the previous feed.
- [Sources](./sources.json): official public source registry.
- [OpenAPI manifest](./openapi.json): static endpoint manifest.

## Machine-readable contracts

- [Feed schema](./schema/feed.schema.json)
- [Status schema](./schema/status.schema.json)
- [Changes schema](./schema/changes.schema.json)
- [Sources schema](./schema/sources.schema.json)

## Usage rules for agents

- Treat this as a metadata index, not an official PNU service.
- Always preserve the original notice URL when answering users.
- Treat `summary` and `_pnu.snippet` as short previews only.
- Fetch full notice text from `item._pnu.content_access.detail_url` or `item.url`.
- Fetch attachments from `item._pnu.attachments[].download_url`.
- Treat `content_mirrored: false` and `attachments_mirrored: false` as a hard boundary.
- Check `status.json` before relying on source freshness.
- Check `changes.json` for lightweight new item detection before fetching the full feed.
- Use `_pnu` fields in `feed.json` for source, attachment, fetched_at, and content_hash metadata.
"""
INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PNU Public Notice Feed</title>
  <link rel="alternate" type="application/feed+json" title="PNU Public Notice Feed" href="./feed.json">
  <style>
    body {
      color: #17202a;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.6;
      margin: 0;
      padding: 48px 20px;
    }
    main {
      margin: 0 auto;
      max-width: 760px;
    }
    h1 {
      font-size: 2rem;
      line-height: 1.2;
      margin: 0 0 12px;
    }
    h2 {
      font-size: 1.15rem;
      margin-top: 32px;
    }
    a {
      color: #0758a8;
    }
    code {
      background: #f2f4f7;
      border-radius: 4px;
      padding: 2px 5px;
    }
    .notice {
      border-left: 4px solid #d0d7de;
      padding-left: 16px;
    }
  </style>
</head>
<body>
  <main>
    <h1>PNU Public Notice Feed</h1>
    <p class="notice">Unofficial public metadata feed for public notices from Pusan National University. This project is not operated by Pusan National University.</p>
    <p>This site publishes a static, AI-friendly index of public notice metadata. It links back to official notice pages and attachment download URLs instead of mirroring full notice or attachment content.</p>

    <h2>Endpoints</h2>
    <ul>
      <li><a href="./feed.json">feed.json</a> - JSON Feed 1.1 compatible notice metadata</li>
      <li><a href="./status.json">status.json</a> - source refresh status</li>
      <li><a href="./changes.json">changes.json</a> - latest added, updated, and removed item summary</li>
      <li><a href="./sources.json">sources.json</a> - public source registry</li>
      <li><a href="./openapi.json">openapi.json</a> - static endpoint manifest</li>
      <li><a href="./llms.txt">llms.txt</a> - AI agent usage guide</li>
    </ul>

    <h2>Agent Notes</h2>
    <p>Use <code>summary</code> and <code>_pnu.snippet</code> as short previews only. Fetch full notice text from <code>item.url</code> or <code>item._pnu.content_access.detail_url</code>.</p>
  </main>
</body>
</html>
"""


@dataclass(frozen=True)
class PublicSource:
    id: str
    name: str
    adapter: str
    official_url: str
    category: str
    poll_interval_minutes: int
    public_only: bool
    tags: list[str]
    access_policy: str = "public_official_url_only"
    menu_cd: str | None = None
    notes: str | None = None

    @classmethod
    def from_json(cls, data: dict) -> "PublicSource":
        public_only = bool(data.get("public_only", True))
        if not public_only:
            raise ValueError(f"source must be public_only: {data.get('id')}")

        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            adapter=str(data["adapter"]),
            official_url=str(data["official_url"]),
            category=str(data.get("category", "notice")),
            poll_interval_minutes=int(data.get("poll_interval_minutes", 30)),
            public_only=public_only,
            access_policy=str(data.get("access_policy", "public_official_url_only")),
            tags=[str(tag) for tag in data.get("tags", [])],
            menu_cd=str(data["menu_cd"]) if data.get("menu_cd") else None,
            notes=str(data["notes"]) if data.get("notes") else None,
        )

    def to_adapter_source(self) -> Source:
        return Source(
            id=self.id,
            name=self.name,
            adapter=self.adapter,
            entry_url=self.official_url,
            tags=self.tags,
            menu_cd=self.menu_cd,
        )


@dataclass(frozen=True)
class SourceResult:
    source: PublicSource
    checked_at: str
    items: list[dict]
    last_success_at: str | None
    status: str
    next_check_at: str | None = None
    backoff_until: str | None = None
    error_count: int = 0
    skipped_reason: str | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.status == "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate PNU public notice feeds.")
    parser.add_argument(
        "--sources",
        default=str(DEFAULT_SOURCE_REGISTRY),
        help="Path to public notice source registry JSON.",
    )
    parser.add_argument(
        "--output-dir",
        default="public",
        help="Directory where feed.json and status.json will be written.",
    )
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE_PATH),
        help="Path to feed generator state JSON.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Maximum notices to fetch per source.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print generated JSON files.",
    )
    parser.add_argument(
        "--public-base-url",
        default=DEFAULT_PUBLIC_BASE_URL,
        help="Published base URL used in feed metadata.",
    )
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir)
    state_path = Path(args.state)
    sources_path = Path(args.sources)

    try:
        generated = generate_outputs(
            sources_path=sources_path,
            state_path=state_path,
            limit=args.limit,
            public_base_url=args.public_base_url,
        )
        sync_static_assets(output_dir, sources_path, args.public_base_url)
        if generated["all_sources_skipped"] and outputs_exist(
            output_dir,
            state_path,
        ) and outputs_match_public_base_url(
            output_dir,
            args.public_base_url,
        ) and outputs_match_current_format(output_dir):
            return 0
        write_outputs(
            output_dir=output_dir,
            feed=generated["feed"],
            status=generated["status"],
            pretty=args.pretty,
        )
        write_state(
            path=state_path,
            state=generated["state"],
            pretty=args.pretty,
        )
    except Exception as error:  # noqa: BLE001 - CLI boundary should show explicit failures.
        print(f"feed generation failed: {error}", file=sys.stderr)
        return 1

    return 0


def generate_outputs(
    sources_path: Path,
    limit: int,
    state_path: Path = DEFAULT_STATE_PATH,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
    now: datetime | None = None,
) -> dict[str, dict]:
    generated_at = iso_now(now)
    sources = load_sources(sources_path)
    state = load_state(state_path)
    results = [
        fetch_source_result(source, limit, generated_at, state)
        for source in sources
    ]
    feed = build_feed(results, generated_at, public_base_url)
    status = build_status(results, generated_at)
    updated_state = build_state(results, generated_at)
    return {
        "feed": feed,
        "status": status,
        "state": updated_state,
        "all_sources_skipped": all_sources_skipped(results),
    }


def load_sources(path: Path) -> list[PublicSource]:
    if not path.exists():
        raise ValueError(f"source registry not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    sources = [PublicSource.from_json(item) for item in data.get("sources", [])]
    validate_sources(sources)
    return sources


def validate_sources(sources: list[PublicSource]) -> None:
    ids = [source.id for source in sources]
    duplicate_ids = sorted({source_id for source_id in ids if ids.count(source_id) > 1})
    if duplicate_ids:
        raise ValueError(f"duplicate source id: {', '.join(duplicate_ids)}")

    unsupported = sorted(
        {
            source.adapter
            for source in sources
            if source.adapter not in SUPPORTED_ADAPTERS
        }
    )
    if unsupported:
        raise ValueError(f"unsupported adapter in sources: {', '.join(unsupported)}")

    invalid_intervals = [
        source.id
        for source in sources
        if source.poll_interval_minutes < 1
    ]
    if invalid_intervals:
        raise ValueError(
            "poll_interval_minutes must be positive for: "
            + ", ".join(sorted(invalid_intervals))
        )

    missing_menu_cd = [
        source.id
        for source in sources
        if source.adapter == "onestop-js-board" and not source.menu_cd
    ]
    if missing_menu_cd:
        raise ValueError(
            "menu_cd is required for onestop-js-board sources: "
            + ", ".join(sorted(missing_menu_cd))
        )


def fetch_source_result(
    source: PublicSource,
    limit: int,
    checked_at: str,
    state: dict | None = None,
) -> SourceResult:
    source_state = get_source_state(state, source.id)
    skip_reason, next_check_at = source_skip_reason(source, source_state, checked_at)
    if skip_reason:
        cached_items = list(cached_items_by_id(source_state).values())
        return SourceResult(
            source=source,
            checked_at=source_state.get("last_checked_at") or checked_at,
            items=cached_items,
            last_success_at=source_state.get("last_success_at"),
            status="skipped",
            next_check_at=next_check_at,
            backoff_until=source_state.get("backoff_until"),
            error_count=int(source_state.get("error_count") or 0),
            skipped_reason=skip_reason,
            error=source_state.get("error") if skip_reason == "backoff" else None,
        )

    try:
        cached_items = cached_items_by_id(source_state)
        notices = fetch_source(
            source,
            limit,
            seen_notice_ids=set(cached_items),
        )
        fetched_items = [
            notice_to_feed_item(notice, checked_at)
            for notice in notices
        ]
        merged_items = merge_cached_items(
            list(cached_items.values()),
            fetched_items,
            limit,
        )
        return SourceResult(
            source=source,
            checked_at=checked_at,
            items=merged_items,
            last_success_at=checked_at,
            status="ok",
            next_check_at=next_check_at_from_interval(
                checked_at,
                source.poll_interval_minutes,
            ),
        )
    except Exception as error:  # noqa: BLE001 - source failures belong in status.json.
        cached_items = list(cached_items_by_id(source_state).values())
        error_count = int(source_state.get("error_count") or 0) + 1
        backoff_until = backoff_until_for_error(
            checked_at,
            source.poll_interval_minutes,
            error_count,
        )
        return SourceResult(
            source=source,
            checked_at=checked_at,
            items=cached_items,
            last_success_at=source_state.get("last_success_at"),
            status="error",
            next_check_at=backoff_until,
            backoff_until=backoff_until,
            error_count=error_count,
            error=str(error),
        )


def fetch_source(
    source: PublicSource,
    limit: int,
    seen_notice_ids: set[str] | None = None,
) -> list[Notice]:
    adapter_source = source.to_adapter_source()
    if source.adapter == "pusan-cms-static-board":
        return fetch_cms_static_board(
            adapter_source,
            limit,
            seen_notice_ids=seen_notice_ids or set(),
        )
    if source.adapter == "onestop-js-board":
        return fetch_onestop_js_board(adapter_source, limit)
    raise ValueError(f"unsupported adapter: {source.adapter}")


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "sources": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def get_source_state(state: dict | None, source_id: str) -> dict:
    if not state:
        return {}
    sources = state.get("sources", {})
    return sources.get(source_id, {})


def cached_items_by_id(source_state: dict) -> dict[str, dict]:
    return {
        str(item["id"]): item
        for item in source_state.get("items", [])
        if item.get("id")
    }


def merge_cached_items(
    cached_items: list[dict],
    fetched_items: list[dict],
    limit: int,
) -> list[dict]:
    merged = {
        item["id"]: item
        for item in cached_items
        if item.get("id")
    }
    for item in fetched_items:
        merged = {**merged, item["id"]: item}
    return sorted(
        merged.values(),
        key=lambda item: (item.get("_pnu", {}).get("published_at") or "", item["id"]),
        reverse=True,
    )[:limit]


def build_state(results: list[SourceResult], generated_at: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "feed_version": FEED_VERSION,
        "generated_at": generated_at,
        "sources": {
            result.source.id: {
                "last_checked_at": result.checked_at,
                "last_success_at": result.last_success_at,
                "last_error_at": result.checked_at if result.error else None,
                "next_check_at": result.next_check_at,
                "backoff_until": result.backoff_until,
                "error_count": result.error_count,
                "status": result.status,
                "skipped_reason": result.skipped_reason,
                "error": result.error,
                "items": [normalize_feed_item(item) for item in result.items],
            }
            for result in results
        },
    }


def build_feed(
    results: list[SourceResult],
    generated_at: str,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
    snippet_limit: int = DEFAULT_SNIPPET_LIMIT,
) -> dict:
    items = [
        normalize_feed_item(item)
        for result in results
        for item in result.items
    ]
    sorted_items = sorted(
        items,
        key=lambda item: (item["_pnu"].get("published_at") or "", item["id"]),
        reverse=True,
    )
    base_url = public_base_url.rstrip("/")

    return {
        "version": JSON_FEED_VERSION,
        "title": "PNU Public Notice Feed",
        "home_page_url": base_url,
        "feed_url": f"{base_url}/feed.json",
        "description": DISCLAIMER,
        "_pnu": {
            "schema_version": SCHEMA_VERSION,
            "feed_version": FEED_VERSION,
            "generated_at": generated_at,
            "status_url": f"{base_url}/status.json",
            "changes_url": f"{base_url}/changes.json",
            "sources_url": f"{base_url}/sources.json",
            "schema_url": f"{base_url}/schema/feed.schema.json",
            "source_count": len(results),
            "item_count": len(sorted_items),
            "sources": [source_to_feed_json(result) for result in results],
        },
        "items": sorted_items,
    }


def build_status(results: list[SourceResult], generated_at: str) -> dict:
    source_statuses = [source_to_status_json(result) for result in results]
    failed_count = len([result for result in results if result.status == "error"])

    return {
        "schema_version": SCHEMA_VERSION,
        "feed_version": FEED_VERSION,
        "generated_at": generated_at,
        "overall_status": "ok" if failed_count == 0 else "partial",
        "source_count": len(results),
        "failed_source_count": failed_count,
        "sources": source_statuses,
    }


def notice_to_feed_item(
    notice: Notice,
    fetched_at: str,
    snippet_limit: int = DEFAULT_SNIPPET_LIMIT,
) -> dict:
    snippet = truncate_text(notice.snippet, snippet_limit)
    return {
        "id": notice.notice_id,
        "url": notice.url,
        "title": notice.title,
        "content_text": CONTENT_TEXT_NOTICE,
        "summary": snippet,
        "date_published": date_to_json_feed_timestamp(notice.published_at),
        "_pnu": {
            "source_id": notice.source_id,
            "source_name": notice.source_name,
            "published_at": notice.published_at,
            "fetched_at": fetched_at,
            "snippet": snippet,
            "content_access": {
                "detail_url": notice.url,
                "requires_login": False,
                "content_mirrored": False,
                "attachments_mirrored": False,
            },
            "attachments": [
                attachment_to_feed_json(attachment)
                for attachment in notice.attachments
            ],
            "tags": notice.tags,
            "content_hash": notice.content_hash,
        },
    }


def normalize_feed_item(item: dict) -> dict:
    pnu = item.get("_pnu", {})
    snippet = pnu.get("snippet")
    normalized = {
        **item,
        "content_text": CONTENT_TEXT_NOTICE,
        "summary": item.get("summary", snippet),
    }
    return {
        **normalized,
        "_pnu": pnu,
    }


def source_to_feed_json(result: SourceResult) -> dict:
    return {
        "id": result.source.id,
        "name": result.source.name,
        "official_url": result.source.official_url,
        "adapter": result.source.adapter,
        "category": result.source.category,
        "poll_interval_minutes": result.source.poll_interval_minutes,
        "public_only": result.source.public_only,
        "access_policy": result.source.access_policy,
        "last_checked_at": result.checked_at,
        "last_success_at": result.last_success_at,
    }


def source_to_status_json(result: SourceResult) -> dict:
    return {
        "id": result.source.id,
        "name": result.source.name,
        "official_url": result.source.official_url,
        "adapter": result.source.adapter,
        "category": result.source.category,
        "poll_interval_minutes": result.source.poll_interval_minutes,
        "public_only": result.source.public_only,
        "access_policy": result.source.access_policy,
        "status": result.status,
        "last_checked_at": result.checked_at,
        "last_success_at": result.last_success_at,
        "last_error_at": result.checked_at if result.error else None,
        "next_check_at": result.next_check_at,
        "backoff_until": result.backoff_until,
        "error_count": result.error_count,
        "skipped_reason": result.skipped_reason,
        "item_count": len(result.items),
        "error_type": error_type(result.error),
        "error": result.error,
    }


def attachment_to_feed_json(attachment) -> dict:
    extension = attachment.type or file_extension_from_name(attachment.name)
    return {
        "name": attachment.name,
        "url": attachment.url,
        "download_url": attachment.url,
        "type": attachment.type,
        "media_type": media_type_from_extension(extension),
        "file_extension": extension,
    }


def write_outputs(output_dir: Path, feed: dict, status: dict, pretty: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_feed = read_json_if_exists(output_dir / "feed.json")
    changes = build_changes(previous_feed, feed)
    write_json(output_dir / "feed.json", feed, pretty)
    write_json(output_dir / "status.json", status, pretty)
    write_json(output_dir / "changes.json", changes, pretty)


def sync_static_assets(
    output_dir: Path,
    sources_path: Path,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_text_if_changed(output_dir / "index.html", INDEX_HTML)
    copy_text_if_changed(sources_path, output_dir / "sources.json")
    copy_text_with_base_url(
        PROJECT_ROOT / "openapi.json",
        output_dir / "openapi.json",
        public_base_url,
    )
    write_text_if_changed(output_dir / "llms.txt", LLMS_TXT)

    schema_output_dir = output_dir / "schema"
    schema_output_dir.mkdir(parents=True, exist_ok=True)
    for schema_path in sorted((PROJECT_ROOT / "schema").glob("*.schema.json")):
        copy_text_with_base_url(
            schema_path,
            schema_output_dir / schema_path.name,
            public_base_url,
        )


def outputs_exist(output_dir: Path, state_path: Path) -> bool:
    return all(
        path.exists()
        for path in [
            output_dir / "feed.json",
            output_dir / "status.json",
            output_dir / "changes.json",
            state_path,
        ]
    )


def outputs_match_public_base_url(output_dir: Path, public_base_url: str) -> bool:
    feed = read_json_if_exists(output_dir / "feed.json")
    if not feed:
        return False
    base_url = public_base_url.rstrip("/")
    return feed.get("feed_url") == f"{base_url}/feed.json"


def outputs_match_current_format(output_dir: Path) -> bool:
    feed = read_json_if_exists(output_dir / "feed.json")
    if not feed:
        return False
    if not (output_dir / "index.html").exists():
        return False
    for item in feed.get("items", []):
        if item.get("content_text") != CONTENT_TEXT_NOTICE:
            return False
        if "summary" not in item:
            return False
    return True


def all_sources_skipped(results: list[SourceResult]) -> bool:
    return bool(results) and all(result.status == "skipped" for result in results)


def write_state(path: Path, state: dict, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, state, pretty)


def write_json(path: Path, value: dict, pretty: bool) -> None:
    indent = 2 if pretty else None
    write_text_if_changed(
        path,
        json.dumps(value, ensure_ascii=False, indent=indent) + "\n",
    )


def copy_text_if_changed(source: Path, target: Path) -> None:
    if not source.exists():
        raise ValueError(f"static asset not found: {source}")
    write_text_if_changed(target, source.read_text(encoding="utf-8"))


def copy_text_with_base_url(source: Path, target: Path, public_base_url: str) -> None:
    if not source.exists():
        raise ValueError(f"static asset not found: {source}")
    content = source.read_text(encoding="utf-8").replace(
        "https://example.invalid/pnu-public-notice-feed",
        public_base_url.rstrip("/"),
    )
    write_text_if_changed(target, content)


def write_text_if_changed(path: Path, content: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.write_text(content, encoding="utf-8")


def read_json_if_exists(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_changes(previous_feed: dict | None, current_feed: dict) -> dict:
    previous_items = feed_items_by_id(previous_feed) if previous_feed else {}
    current_items = feed_items_by_id(current_feed)

    added_ids = sorted(set(current_items) - set(previous_items))
    removed_ids = sorted(set(previous_items) - set(current_items))
    updated_ids = sorted(
        item_id
        for item_id in set(current_items) & set(previous_items)
        if item_content_hash(current_items[item_id])
        != item_content_hash(previous_items[item_id])
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "feed_version": FEED_VERSION,
        "generated_at": current_feed["_pnu"]["generated_at"],
        "previous_generated_at": (
            previous_feed.get("_pnu", {}).get("generated_at")
            if previous_feed
            else None
        ),
        "added_count": len(added_ids),
        "updated_count": len(updated_ids),
        "removed_count": len(removed_ids),
        "added": [change_item(current_items[item_id]) for item_id in added_ids],
        "updated": [change_item(current_items[item_id]) for item_id in updated_ids],
        "removed": [
            change_item(previous_items[item_id])
            for item_id in removed_ids
        ],
    }


def feed_items_by_id(feed: dict | None) -> dict[str, dict]:
    if not feed:
        return {}
    return {
        str(item["id"]): item
        for item in feed.get("items", [])
        if item.get("id")
    }


def change_item(item: dict) -> dict:
    pnu = item.get("_pnu", {})
    return {
        "id": item["id"],
        "source_id": pnu.get("source_id") or item.get("source_id"),
        "title": item.get("title"),
        "url": item.get("url"),
        "published_at": pnu.get("published_at") or item.get("published_at"),
        "content_hash": item_content_hash(item),
    }


def item_content_hash(item: dict) -> str | None:
    pnu = item.get("_pnu", {})
    return pnu.get("content_hash") or item.get("content_hash")


def truncate_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit].rstrip()


def error_type(error: str | None) -> str | None:
    if error is None:
        return None
    lowered = error.lower()
    if "timeout" in lowered:
        return "timeout"
    if "unsupported adapter" in lowered:
        return "configuration"
    if "http" in lowered or "urlopen" in lowered:
        return "network"
    return "unknown"


def source_skip_reason(
    source: PublicSource,
    source_state: dict,
    checked_at: str,
) -> tuple[str | None, str | None]:
    if not source_state.get("items"):
        return None, None

    current = parse_iso(checked_at)
    backoff_until = source_state.get("backoff_until")
    if backoff_until and parse_iso(backoff_until) > current:
        return "backoff", backoff_until

    last_checked_at = source_state.get("last_checked_at")
    if not last_checked_at:
        return None, None

    next_check_at = next_check_at_from_interval(
        last_checked_at,
        source.poll_interval_minutes,
    )
    if parse_iso(next_check_at) > current:
        return "poll_interval", next_check_at

    return None, next_check_at


def next_check_at_from_interval(checked_at: str, interval_minutes: int) -> str:
    return (parse_iso(checked_at) + timedelta(minutes=interval_minutes)).isoformat(
        timespec="seconds"
    )


def backoff_until_for_error(
    checked_at: str,
    interval_minutes: int,
    error_count: int,
) -> str:
    delay_minutes = min(interval_minutes * (2 ** max(error_count - 1, 0)), 360)
    return (parse_iso(checked_at) + timedelta(minutes=delay_minutes)).isoformat(
        timespec="seconds"
    )


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def file_extension_from_name(name: str) -> str | None:
    suffix = Path(name).suffix.lstrip(".").lower()
    return suffix or None


def media_type_from_extension(extension: str | None) -> str | None:
    if not extension:
        return None
    media_types = {
        "csv": "text/csv",
        "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "hwp": "application/x-hwp",
        "hwpx": "application/hwp+zip",
        "pdf": "application/pdf",
        "txt": "text/plain",
        "xls": "application/vnd.ms-excel",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "zip": "application/zip",
    }
    return media_types.get(extension.lower())


def date_to_json_feed_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        published_date = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return value
    return published_date.replace(tzinfo=ZoneInfo("Asia/Seoul")).isoformat(
        timespec="seconds"
    )


def iso_now(value: datetime | None = None) -> str:
    current = value or datetime.now(ZoneInfo("Asia/Seoul"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return current.isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
