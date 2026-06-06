from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import re
import sys
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from .archive import (
    ARCHIVE_VERSION,
    EVENT_STREAM_VERSION,
    archive_outputs_exist,
    write_archive_outputs,
)
from .cms_static_board import fetch_cms_static_board
from .duplicates import build_duplicates
from .job_board import fetch_job_notice_board, fetch_job_recruit_board
from .k2web_board import fetch_k2web_board
from .legacy_php_board import fetch_legacy_php_board
from .library_pyxis_board import fetch_library_pyxis_board
from .onestop_js_board import fetch_onestop_js_board
from .simple_html_board import fetch_plato_ubboard, fetch_simple_html_board
from .topics import infer_topics
from .types import Notice, Source
from .websquare_js_board import fetch_websquare_js_board

SCHEMA_VERSION = "0.1"
JSON_FEED_VERSION = "https://jsonfeed.org/version/1.1"
FEED_VERSION = "2026-06-04"
DEFAULT_LIMIT = 40
DEFAULT_FEED_ITEM_LIMIT = 150
DEFAULT_SNIPPET_LIMIT = 500
DEFAULT_FETCH_CONCURRENCY = 4
DEFAULT_PER_HOST_CONCURRENCY = 1
BYTES_PER_MIB = 1024 * 1024
SIZE_BUDGETS = {
    "public_total": {
        "warning_bytes": 500 * BYTES_PER_MIB,
        "failure_bytes": 800 * BYTES_PER_MIB,
    },
    "archive_total": {
        "warning_bytes": 400 * BYTES_PER_MIB,
        "failure_bytes": 700 * BYTES_PER_MIB,
    },
    "single_public_file": {
        "warning_bytes": 25 * BYTES_PER_MIB,
        "failure_bytes": 50 * BYTES_PER_MIB,
    },
    "state_file": {
        "warning_bytes": 25 * BYTES_PER_MIB,
        "failure_bytes": 50 * BYTES_PER_MIB,
    },
    "generator_runtime": {
        "warning_ms": 8 * 60 * 1000,
        "failure_ms": 10 * 60 * 1000,
    },
}
SENSITIVE_QUERY_PARAM_RE = re.compile(
    r"([?&](?:secret|token|access_token|auth|authorization|api[_-]?key|key|password|passwd)=)([^\s&#]+)",
    re.IGNORECASE,
)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_REGISTRY = PROJECT_ROOT / "sources.json"
DEFAULT_STATE_PATH = PROJECT_ROOT / "cache" / "feed-state.json"
DEFAULT_PUBLIC_BASE_URL = "https://lofidonut3.github.io/pnu-public-notice-feed"
SUPPORTED_ADAPTERS = {
    "pusan-cms-static-board",
    "onestop-js-board",
    "websquare-js-board",
    "k2web-board",
    "legacy-php-board",
    "job-notice-html-board",
    "job-recruit-html-board",
    "library-pyxis-board",
    "simple-html-board",
    "plato-ubboard",
}
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

- [Index](./index.json): compact manifest with sources, source status, archive manifest, same-notice groups, and latest run diagnostics.
- [Events](./events.json): primary recent event stream for cursor-based agent checks.
- [Latest](./latest.json): JSON Feed 1.1 compatible latest-discovery public notice metadata, currently limited to the latest 150 items globally.
- [RSS](./rss.xml): RSS 2.0 compatibility feed for feed readers and automation tools.
- [Archive](./archive/YYYY-MM.json): monthly durable archive with notice metadata and observed events.
- [OpenAPI manifest](./openapi.json): static endpoint manifest.

## Machine-readable contracts

- [Index schema](./schema/index.schema.json)
- [Events schema](./schema/events.schema.json)
- [Latest schema](./schema/latest.schema.json)
- [Archive month schema](./schema/archive-month.schema.json)

## Endpoint roles for agents

- Primary cursor endpoint: `events.json`.
- Metadata/source/status/dedupe manifest: `index.json`.
- Durable catch-up endpoint: `archive/YYYY-MM.json`.
- Latest discovery endpoint: `latest.json`.
- Compatibility endpoint: `rss.xml`.

## Usage rules for agents

- Treat this as a metadata index, not an official PNU service.
- Always preserve the original notice URL when answering users.
- Treat `summary` and `_pnu.snippet` as short previews only.
- Fetch full notice text from `item._pnu.content_access.detail_url` or `item.url`.
- Fetch attachments from `item._pnu.attachments[].download_url`.
- Treat `content_mirrored: false` and `attachments_mirrored: false` as a hard boundary.
- Check `index.json.status` before relying on source freshness.
- Treat `index.json.status.overall_status: partial` as usable feed output with some source freshness degraded; inspect the relevant source's `last_success_at`, `last_error_at`, `backoff_until`, and `error_count`.
- Treat `status.skipped_reason: poll_interval` as normal rate limiting, not a source failure. Use `degraded_source_count`, `backoff_source_count`, and `error_source_count` for freshness risk.
- Use `events.json` as the primary cursor-based notice stream.
- Store a local `latest_event_id` or `seen_at` cursor and process newer events.
- Treat each event as a compact routing record; use `archive_file` and `archive_item_id` when full notice metadata is needed.
- Use event `same_notice_group_id`, `canonical_item_id`, `is_canonical`, and `same_notice_source_ids` before sending notifications for multiple matching items from different sources.
- Use `index.json.same_notice_groups` as the full same-notice manifest and fallback lookup.
- Use `latest.json` only as a latest discovery feed, not as the primary cursor endpoint or a complete archive.
- Use `index.json.diagnostics.latest_run_diff` only as a latest generator-run diagnostic, not as durable history.
- Use `index.json.archives` and monthly archive files for catch-up after downtime.
- Use `rss.xml` only as a compatibility feed; prefer JSON endpoints for structured agent workflows.
- Use archive item `_pnu` fields or `latest.json` for source, attachment, fetched_at, and content_hash metadata.
- No project-specific client library is required. Any HTTP/JSON client can consume these endpoints directly.
"""
INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PNU Public Notice Feed</title>
  <link rel="alternate" type="application/feed+json" title="PNU Public Notice Feed" href="./latest.json">
  <link rel="alternate" type="application/rss+xml" title="PNU Public Notice Feed RSS" href="./rss.xml">
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
    <p>This site publishes static, AI-friendly public notice metadata. It links back to official notice pages and attachment download URLs instead of mirroring full notice or attachment content.</p>

    <h2>Endpoints</h2>
    <ul>
      <li><a href="./index.json">index.json</a> - compact manifest with sources, status, archive, same-notice groups, and diagnostics</li>
      <li><a href="./events.json">events.json</a> - primary recent event stream for cursor-based checks</li>
      <li><a href="./latest.json">latest.json</a> - JSON Feed 1.1 compatible latest-discovery notice metadata</li>
      <li><a href="./rss.xml">rss.xml</a> - RSS 2.0 compatibility feed</li>
      <li><a href="./archive/2026-06.json">archive/YYYY-MM.json</a> - monthly durable archive files</li>
      <li><a href="./openapi.json">openapi.json</a> - static endpoint manifest</li>
      <li><a href="./llms.txt">llms.txt</a> - AI agent usage guide</li>
    </ul>

    <h2>Agent Notes</h2>
    <p>Use <code>events.json</code> as the primary cursor stream. Each event is a compact routing record with <code>archive_file</code> and <code>archive_item_id</code> for durable metadata lookup.</p>
    <p>No project-specific client library is required. Any HTTP/JSON client can keep a local cursor and fetch archive files when detailed metadata is needed.</p>
    <p>Use event duplicate fields or <code>index.json.same_notice_groups</code> before sending notifications for multiple matching items from different sources. Use <code>latest.json</code> for latest discovery and <code>rss.xml</code> for compatibility.</p>
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
    board_id: str | None = None
    cate_type_seq: str | None = None
    bbs_type_seq: str | None = None
    mainbbs_tab_index: str | None = None
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
            board_id=str(data["board_id"]) if data.get("board_id") else None,
            cate_type_seq=str(data["cate_type_seq"]) if data.get("cate_type_seq") else None,
            bbs_type_seq=str(data["bbs_type_seq"]) if data.get("bbs_type_seq") else None,
            mainbbs_tab_index=(
                str(data["mainbbs_tab_index"])
                if data.get("mainbbs_tab_index") is not None
                else None
            ),
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
            board_id=self.board_id,
            cate_type_seq=self.cate_type_seq,
            bbs_type_seq=self.bbs_type_seq,
            mainbbs_tab_index=self.mainbbs_tab_index,
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
    duration_ms: int | None = None

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
        help="Directory where public feed outputs will be written.",
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
        "--feed-item-limit",
        type=int,
        default=DEFAULT_FEED_ITEM_LIMIT,
        help="Maximum latest notices to publish in latest.json.",
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
    parser.add_argument(
        "--fetch-concurrency",
        type=int,
        default=DEFAULT_FETCH_CONCURRENCY,
        help="Maximum number of sources to fetch concurrently.",
    )
    parser.add_argument(
        "--per-host-concurrency",
        type=int,
        default=DEFAULT_PER_HOST_CONCURRENCY,
        help="Maximum number of concurrent source fetches for the same host.",
    )
    parser.add_argument(
        "--check-size-budget",
        action="store_true",
        help="Check generated public/cache size budgets and exit.",
    )
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir)
    state_path = Path(args.state)
    sources_path = Path(args.sources)

    try:
        if args.check_size_budget:
            diagnostics = build_size_budget_diagnostics(output_dir, state_path)
            print(json.dumps(diagnostics, ensure_ascii=False, indent=2))
            assert_size_budget(diagnostics)
            print_feed_health_snapshot(output_dir, state_path)
            return 0

        generated = generate_outputs(
            sources_path=sources_path,
            state_path=state_path,
            limit=args.limit,
            public_base_url=args.public_base_url,
            feed_item_limit=args.feed_item_limit,
            fetch_concurrency=args.fetch_concurrency,
            per_host_concurrency=args.per_host_concurrency,
        )
        sync_static_assets(output_dir, sources_path, args.public_base_url)
        if generated["all_sources_skipped"] and outputs_exist(
            output_dir,
            state_path,
        ) and outputs_match_public_base_url(
            output_dir,
            args.public_base_url,
        ) and outputs_match_source_metadata(
            output_dir,
            generated["latest"],
        ) and outputs_match_current_format(
            output_dir,
        ) and archive_outputs_exist(
            output_dir,
        ) and archive_outputs_match_current_versions(
            output_dir,
        ):
            return 0
        if should_write_public_outputs(
            output_dir=output_dir,
            state_path=state_path,
            generated=generated,
            public_base_url=args.public_base_url,
        ):
            write_outputs(
                output_dir=output_dir,
                latest=generated["latest"],
                rss=generated["rss"],
                status=generated["status"],
                run_diff=generated["run_diff"],
                duplicates=generated["duplicates"],
                state=generated["state"],
                diagnostics=generated["diagnostics"],
                baseline_source_ids=generated["baseline_source_ids"],
                public_base_url=args.public_base_url,
                pretty=args.pretty,
            )
        write_state(
            path=state_path,
            state=generated["state"],
            pretty=args.pretty,
        )
        assert_size_budget(
            build_size_budget_diagnostics(
                output_dir,
                state_path,
                runtime_ms=generated["diagnostics"].get("duration_ms"),
            )
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
    feed_item_limit: int = DEFAULT_FEED_ITEM_LIMIT,
    fetch_concurrency: int = DEFAULT_FETCH_CONCURRENCY,
    per_host_concurrency: int = DEFAULT_PER_HOST_CONCURRENCY,
) -> dict[str, dict]:
    generation_started_at = time.perf_counter()
    generated_at = iso_now(now)
    sources = load_sources(sources_path)
    state = load_state(state_path)
    results = fetch_source_results(
        sources,
        limit,
        generated_at,
        state,
        fetch_concurrency=fetch_concurrency,
        per_host_concurrency=per_host_concurrency,
    )
    all_items = collect_result_items(results)
    duplicates = build_duplicates(all_items, generated_at, FEED_VERSION)
    enriched_results = apply_duplicate_metadata_to_results(results, duplicates)
    latest = build_latest(
        enriched_results,
        generated_at,
        public_base_url,
        item_limit=feed_item_limit,
    )
    status = build_status(enriched_results, generated_at)
    baseline_source_ids = baseline_source_ids_for_results(enriched_results, state)
    updated_state = build_state(enriched_results, generated_at, state)
    run_diff = build_run_diff(state, updated_state)
    diagnostics = build_run_diagnostics(
        results=enriched_results,
        latest=latest,
        state=updated_state,
        generated_at=generated_at,
        generation_started_at=generation_started_at,
        fetch_concurrency=fetch_concurrency,
        per_host_concurrency=per_host_concurrency,
    )
    return {
        "latest": latest,
        "rss": build_rss(latest),
        "status": status,
        "run_diff": run_diff,
        "duplicates": duplicates,
        "state": updated_state,
        "diagnostics": diagnostics,
        "baseline_source_ids": baseline_source_ids,
        "all_sources_skipped": all_sources_skipped(enriched_results),
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

    missing_websquare_menu_cd = [
        source.id
        for source in sources
        if source.adapter == "websquare-js-board" and not source.menu_cd
    ]
    if missing_websquare_menu_cd:
        raise ValueError(
            "menu_cd is required for websquare-js-board sources: "
            + ", ".join(sorted(missing_websquare_menu_cd))
        )


def fetch_source_results(
    sources: list[PublicSource],
    limit: int,
    generated_at: str,
    state: dict | None,
    fetch_concurrency: int = DEFAULT_FETCH_CONCURRENCY,
    per_host_concurrency: int = DEFAULT_PER_HOST_CONCURRENCY,
) -> list[SourceResult]:
    fetch_concurrency = positive_int(fetch_concurrency, "fetch_concurrency")
    per_host_concurrency = positive_int(
        per_host_concurrency,
        "per_host_concurrency",
    )
    if fetch_concurrency == 1 or len(sources) <= 1:
        return [
            fetch_source_result(source, limit, generated_at, state)
            for source in sources
        ]

    host_limiters: dict[str, threading.Semaphore] = {}
    host_limiter_lock = threading.Lock()

    def limiter_for(source: PublicSource) -> threading.Semaphore:
        nonlocal host_limiters
        host = source_host(source)
        with host_limiter_lock:
            limiter = host_limiters.get(host)
            if limiter is None:
                limiter = threading.Semaphore(per_host_concurrency)
                host_limiters = {**host_limiters, host: limiter}
            return limiter

    def fetch_one(index: int, source: PublicSource) -> tuple[int, SourceResult]:
        limiter = limiter_for(source)
        with limiter:
            return index, fetch_source_result(source, limit, generated_at, state)

    with ThreadPoolExecutor(max_workers=fetch_concurrency) as executor:
        futures = [
            executor.submit(fetch_one, index, source)
            for index, source in enumerate(sources)
        ]
        pairs = [future.result() for future in as_completed(futures)]

    return [
        result
        for _index, result in sorted(pairs, key=lambda pair: pair[0])
    ]


def fetch_source_result(
    source: PublicSource,
    limit: int,
    checked_at: str,
    state: dict | None = None,
) -> SourceResult:
    started_at = time.perf_counter()
    source_state = get_source_state(state, source.id)
    skip_reason, next_check_at = source_skip_reason(source, source_state, checked_at)
    if skip_reason:
        cached_items = list(cached_items_by_id(source_state, source).values())
        return source_result_with_duration(
            SourceResult(
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
            ),
            started_at,
        )

    try:
        cached_items = cached_items_by_id(source_state, source)
        notices = fetch_source(
            source,
            limit,
            cached_items=cached_items,
            checked_at=checked_at,
        )
        fetched_items = [
            enrich_item_with_source_metadata(
                notice_to_feed_item(notice, checked_at),
                source,
            )
            for notice in notices
        ]
        merged_items = merge_cached_items(
            [
                enrich_item_with_source_metadata(item, source)
                for item in cached_items.values()
            ],
            fetched_items,
            limit,
        )
        return source_result_with_duration(
            SourceResult(
                source=source,
                checked_at=checked_at,
                items=merged_items,
                last_success_at=checked_at,
                status="ok",
                next_check_at=next_check_at_from_interval(
                    checked_at,
                    source.poll_interval_minutes,
                ),
            ),
            started_at,
        )
    except Exception as error:  # noqa: BLE001 - source failures belong in index status.
        cached_items = list(cached_items_by_id(source_state, source).values())
        error_count = int(source_state.get("error_count") or 0) + 1
        backoff_until = backoff_until_for_error(
            checked_at,
            source.poll_interval_minutes,
            error_count,
        )
        return source_result_with_duration(
            SourceResult(
                source=source,
                checked_at=checked_at,
                items=cached_items,
                last_success_at=source_state.get("last_success_at"),
                status="error",
                next_check_at=backoff_until,
                backoff_until=backoff_until,
                error_count=error_count,
                error=str(error),
            ),
            started_at,
        )


def fetch_source(
    source: PublicSource,
    limit: int,
    cached_items: dict[str, dict] | None = None,
    checked_at: str | None = None,
) -> list[Notice]:
    adapter_source = source.to_adapter_source()
    if source.adapter == "pusan-cms-static-board":
        return fetch_cms_static_board(
            adapter_source,
            limit,
            cached_items=cached_items,
            checked_at=checked_at,
        )
    if source.adapter == "onestop-js-board":
        return fetch_onestop_js_board(adapter_source, limit)
    if source.adapter == "websquare-js-board":
        return fetch_websquare_js_board(adapter_source, limit)
    if source.adapter == "k2web-board":
        return fetch_k2web_board(adapter_source, limit)
    if source.adapter == "legacy-php-board":
        return fetch_legacy_php_board(adapter_source, limit)
    if source.adapter == "job-notice-html-board":
        return fetch_job_notice_board(adapter_source, limit)
    if source.adapter == "job-recruit-html-board":
        return fetch_job_recruit_board(adapter_source, limit)
    if source.adapter == "library-pyxis-board":
        return fetch_library_pyxis_board(adapter_source, limit)
    if source.adapter == "simple-html-board":
        return fetch_simple_html_board(adapter_source, limit)
    if source.adapter == "plato-ubboard":
        return fetch_plato_ubboard(adapter_source, limit)
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


def cached_items_by_id(
    source_state: dict,
    source: PublicSource | None = None,
) -> dict[str, dict]:
    source_metadata = (
        source_to_state_json(source)
        if source is not None
        else source_state.get("source", {})
    )
    return {
        str(item["id"]): hydrate_state_item(item, source_metadata)
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


def enrich_item_with_source_metadata(item: dict, source: PublicSource) -> dict:
    pnu = item.get("_pnu", {})
    source_tags = list(source.tags)
    topics = infer_topics(
        str(item.get("title") or ""),
        source.category,
        source_tags,
    )
    return {
        **item,
        "_pnu": {
            **pnu,
            "source_category": source.category,
            "source_tags": source_tags,
            "topics": topics,
        },
    }


def apply_duplicate_metadata_to_results(
    results: list[SourceResult],
    duplicates: dict,
) -> list[SourceResult]:
    membership = duplicate_membership_by_item_id(duplicates)
    return [
        replace(
            result,
            items=[
                apply_duplicate_metadata_to_item(item, membership.get(str(item.get("id"))))
                for item in result.items
            ],
        )
        for result in results
    ]


def duplicate_membership_by_item_id(duplicates: dict) -> dict[str, dict]:
    membership: dict[str, dict] = {}
    for group in duplicates.get("groups", []):
        item_ids = [str(item_id) for item_id in group.get("item_ids", [])]
        source_ids = [str(source_id) for source_id in group.get("source_ids", [])]
        canonical_item_id = str(group.get("canonical_item_id") or "")
        for item_id in item_ids:
            membership = {
                **membership,
                item_id: {
                    "same_notice_group_id": group.get("id"),
                    "canonical_item_id": canonical_item_id,
                    "is_canonical": item_id == canonical_item_id,
                    "same_notice_source_ids": source_ids,
                },
            }
    return membership


def apply_duplicate_metadata_to_item(
    item: dict,
    duplicate_metadata: dict | None,
) -> dict:
    pnu = item.get("_pnu", {})
    if not duplicate_metadata:
        return {
            **item,
            "_pnu": {
                **pnu,
                "same_notice_group_id": None,
                "canonical_item_id": str(item.get("id") or ""),
                "is_canonical": True,
                "same_notice_source_ids": [str(pnu.get("source_id") or "")],
            },
        }
    return {
        **item,
        "_pnu": {
            **pnu,
            **duplicate_metadata,
        },
    }


def baseline_source_ids_for_results(
    results: list[SourceResult],
    previous_state: dict | None,
) -> list[str]:
    return [
        result.source.id
        for result in results
        if result.status == "ok"
        and result.items
        and source_needs_initial_baseline(
            get_source_state(previous_state, result.source.id),
        )
    ]


def baseline_completed_at_for_source(
    result: SourceResult,
    previous_state: dict | None,
    generated_at: str,
) -> str | None:
    source_state = get_source_state(previous_state, result.source.id)
    existing = source_state.get("baseline_completed_at")
    if existing:
        return str(existing)
    if source_state.get("last_success_at") or source_state.get("items"):
        return generated_at if result.status == "ok" else None
    if result.status == "ok" and result.items:
        return generated_at
    return None


def source_needs_initial_baseline(source_state: dict) -> bool:
    return (
        not source_state.get("baseline_completed_at")
        and not source_state.get("last_success_at")
        and not source_state.get("items")
    )


def build_state(
    results: list[SourceResult],
    generated_at: str,
    previous_state: dict | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "feed_version": FEED_VERSION,
        "generated_at": generated_at,
        "sources": {
            result.source.id: {
                "source": source_to_state_json(result.source),
                "baseline_completed_at": baseline_completed_at_for_source(
                    result,
                    previous_state,
                    generated_at,
                ),
                "last_checked_at": result.checked_at,
                "last_success_at": result.last_success_at,
                "last_error_at": result.checked_at if result.error else None,
                "next_check_at": result.next_check_at,
                "backoff_until": result.backoff_until,
                "error_count": result.error_count,
                "status": result.status,
                "skipped_reason": result.skipped_reason,
                "error": result.error,
                "items": [
                    compact_state_item(
                        enrich_item_with_source_metadata(item, result.source),
                    )
                    for item in result.items
                ],
            }
            for result in results
        },
    }


def source_to_state_json(source: PublicSource) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "official_url": source.official_url,
        "adapter": source.adapter,
        "category": source.category,
        "poll_interval_minutes": source.poll_interval_minutes,
        "public_only": source.public_only,
        "access_policy": source.access_policy,
        "tags": list(source.tags),
    }


def compact_state_item(item: dict) -> dict:
    normalized = normalize_feed_item(item)
    pnu = normalized.get("_pnu", {})
    compact_pnu = {
        "source_id": pnu.get("source_id"),
        "published_at": pnu.get("published_at"),
        "fetched_at": pnu.get("fetched_at"),
        "snippet": pnu.get("snippet"),
        "attachments": pnu.get("attachments", []),
        "content_hash": pnu.get("content_hash"),
    }
    optional_keys = [
        "detail_checked_at",
    ]
    for key in optional_keys:
        if pnu.get(key) is not None:
            compact_pnu = {**compact_pnu, key: pnu.get(key)}

    duplicate_keys = [
        "same_notice_group_id",
        "canonical_item_id",
        "is_canonical",
        "same_notice_source_ids",
    ]
    for key in duplicate_keys:
        if key in pnu:
            compact_pnu = {**compact_pnu, key: pnu.get(key)}
    content_access = pnu.get("content_access")
    if content_access and content_access != default_content_access(normalized.get("url")):
        compact_pnu = {**compact_pnu, "content_access": content_access}

    compact = {
        "id": normalized.get("id"),
        "url": normalized.get("url"),
        "title": normalized.get("title"),
        "_pnu": compact_pnu,
    }
    summary = normalized.get("summary")
    if summary and summary != pnu.get("snippet"):
        compact = {**compact, "summary": summary}
    return compact


def hydrate_state_item(item: dict, source_metadata: dict | None = None) -> dict:
    source_metadata = source_metadata or {}
    pnu = item.get("_pnu", {})
    source_id = (
        pnu.get("source_id")
        or source_metadata.get("id")
        or str(item.get("id") or "").split(":", 1)[0]
    )
    source_name = pnu.get("source_name") or source_metadata.get("name") or source_id
    source_tags = [
        str(tag)
        for tag in (
            pnu.get("source_tags")
            or source_metadata.get("tags")
            or pnu.get("tags")
            or []
        )
    ]
    source_category = pnu.get("source_category") or source_metadata.get("category")
    url = item.get("url") or pnu.get("content_access", {}).get("detail_url")
    snippet = (
        pnu.get("snippet")
        if pnu.get("snippet") is not None
        else item.get("summary")
    )
    published_at = pnu.get("published_at")
    hydrated_pnu = {
        **pnu,
        "source_id": source_id,
        "source_name": source_name,
        "published_at": published_at,
        "snippet": snippet,
        "content_access": pnu.get("content_access") or default_content_access(url),
        "attachments": pnu.get("attachments", []),
        "tags": pnu.get("tags") or source_tags,
        "source_category": source_category,
        "source_tags": source_tags,
        "topics": pnu.get("topics")
        or infer_topics(
            str(item.get("title") or ""),
            str(source_category or ""),
            source_tags,
        ),
    }
    hydrated = {
        **item,
        "url": url,
        "content_text": CONTENT_TEXT_NOTICE,
        "summary": item.get("summary") or snippet,
        "date_published": item.get("date_published")
        or date_to_json_feed_timestamp(published_at),
        "_pnu": hydrated_pnu,
    }
    return normalize_feed_item(hydrated)


def default_content_access(url: str | None) -> dict:
    return {
        "detail_url": url,
        "requires_login": False,
        "content_mirrored": False,
        "attachments_mirrored": False,
    }


def build_latest(
    results: list[SourceResult],
    generated_at: str,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
    snippet_limit: int = DEFAULT_SNIPPET_LIMIT,
    item_limit: int = DEFAULT_FEED_ITEM_LIMIT,
) -> dict:
    items = collect_result_items(results)
    sorted_items = sorted(
        items,
        key=lambda item: (item["_pnu"].get("published_at") or "", item["id"]),
        reverse=True,
    )
    limited_items = sorted_items[:item_limit]
    base_url = public_base_url.rstrip("/")

    return {
        "version": JSON_FEED_VERSION,
        "title": "PNU Public Notice Feed",
        "home_page_url": base_url,
        "feed_url": f"{base_url}/latest.json",
        "description": DISCLAIMER,
        "_pnu": {
            "schema_version": SCHEMA_VERSION,
            "feed_version": FEED_VERSION,
            "generated_at": generated_at,
            "index_url": f"{base_url}/index.json",
            "events_url": f"{base_url}/events.json",
            "rss_url": f"{base_url}/rss.xml",
            "schema_url": f"{base_url}/schema/latest.schema.json",
            "source_count": len(results),
            "item_count": len(limited_items),
            "total_item_count": len(sorted_items),
            "item_limit": item_limit,
            "sources": [source_to_feed_json(result) for result in results],
        },
        "items": limited_items,
    }


def collect_result_items(results: list[SourceResult]) -> list[dict]:
    return [
        normalize_feed_item(item)
        for result in results
        for item in result.items
    ]


def build_status(results: list[SourceResult], generated_at: str) -> dict:
    source_statuses = [source_to_status_json(result) for result in results]
    failed_count = len([result for result in results if source_is_degraded(result)])
    status_counts = source_result_status_counts(results)
    skipped_reason_counts = source_result_skipped_reason_counts(results)

    return {
        "schema_version": SCHEMA_VERSION,
        "feed_version": FEED_VERSION,
        "generated_at": generated_at,
        "overall_status": "ok" if failed_count == 0 else "partial",
        "source_count": len(results),
        "ok_source_count": status_counts.get("ok", 0),
        "skipped_source_count": status_counts.get("skipped", 0),
        "poll_interval_skipped_source_count": skipped_reason_counts.get(
            "poll_interval",
            0,
        ),
        "backoff_source_count": skipped_reason_counts.get("backoff", 0),
        "error_source_count": status_counts.get("error", 0),
        "degraded_source_count": failed_count,
        "failed_source_count": failed_count,
        "status_counts": status_counts,
        "skipped_reason_counts": skipped_reason_counts,
        "sources": source_statuses,
    }


def source_is_degraded(result: SourceResult) -> bool:
    return result.status == "error" or result.skipped_reason == "backoff"


def source_result_status_counts(results: list[SourceResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        status = str(result.status or "unknown")
        counts = {**counts, status: int(counts.get(status, 0)) + 1}
    return counts


def source_result_skipped_reason_counts(results: list[SourceResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        if result.status != "skipped" or not result.skipped_reason:
            continue
        reason = str(result.skipped_reason)
        counts = {**counts, reason: int(counts.get(reason, 0)) + 1}
    return counts


def build_run_diagnostics(
    results: list[SourceResult],
    latest: dict,
    state: dict,
    generated_at: str,
    generation_started_at: float,
    fetch_concurrency: int,
    per_host_concurrency: int,
) -> dict:
    durations = [
        result.duration_ms
        for result in results
        if result.duration_ms is not None
    ]
    latest_pnu = latest.get("_pnu", {})
    return {
        "generated_at": generated_at,
        "duration_ms": duration_ms_since(generation_started_at),
        "fetch_concurrency": positive_int(fetch_concurrency, "fetch_concurrency"),
        "per_host_concurrency": positive_int(
            per_host_concurrency,
            "per_host_concurrency",
        ),
        "source_count": len(results),
        "fetched_source_count": len(
            [result for result in results if result.status == "ok"]
        ),
        "skipped_source_count": len(
            [result for result in results if result.status == "skipped"]
        ),
        "error_source_count": len(
            [result for result in results if result.status == "error"]
        ),
        "total_item_count": latest_pnu.get("total_item_count"),
        "latest_item_count": latest_pnu.get("item_count"),
        "latest_item_limit": latest_pnu.get("item_limit"),
        "source_duration_ms": {
            "min": min(durations) if durations else None,
            "max": max(durations) if durations else None,
            "avg": round(sum(durations) / len(durations), 2) if durations else None,
        },
        "state": build_state_diagnostics(state),
        "source_results": [source_to_diagnostics_json(result) for result in results],
    }


def build_state_diagnostics(state: dict) -> dict:
    sources = state.get("sources", {})
    item_count = sum(
        len(source_state.get("items", []))
        for source_state in sources.values()
    )
    return {
        "source_count": len(sources),
        "item_count": item_count,
        "estimated_compact_json_bytes": len(
            json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ),
    }


def source_to_diagnostics_json(result: SourceResult) -> dict:
    return {
        "id": result.source.id,
        "host": source_host(result.source),
        "adapter": result.source.adapter,
        "status": result.status,
        "skipped_reason": result.skipped_reason,
        "duration_ms": result.duration_ms,
        "item_count": len(result.items),
        "poll_interval_minutes": result.source.poll_interval_minutes,
        "next_check_at": result.next_check_at,
        "backoff_until": result.backoff_until,
        "error_type": error_type(result.error),
    }


def build_rss(feed: dict) -> str:
    channel = ElementTree.Element("channel")
    base_url = str(feed.get("home_page_url") or "").rstrip("/")
    generated_at = str(feed.get("_pnu", {}).get("generated_at") or "")
    source_urls = {
        str(source.get("id")): source.get("official_url")
        for source in feed.get("_pnu", {}).get("sources", [])
        if source.get("id")
    }

    add_text(channel, "title", str(feed.get("title") or "PNU Public Notice Feed"))
    add_text(channel, "link", base_url or str(feed.get("feed_url") or ""))
    add_text(channel, "description", str(feed.get("description") or DISCLAIMER))
    add_text(channel, "language", "ko-KR")
    add_text(channel, "lastBuildDate", rss_datetime(generated_at))
    add_text(channel, "generator", "PNU Public Notice Feed")
    add_text(channel, "docs", "https://www.rssboard.org/rss-specification")

    for item in feed.get("items", []):
        channel.append(rss_item(item, source_urls))

    rss = ElementTree.Element("rss", {"version": "2.0"})
    rss.append(channel)
    ElementTree.indent(rss, space="  ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ElementTree.tostring(rss, encoding="unicode", short_empty_elements=False)
        + "\n"
    )


def rss_item(item: dict, source_urls: dict[str, str | None]) -> ElementTree.Element:
    pnu = item.get("_pnu", {})
    element = ElementTree.Element("item")
    item_id = str(item.get("id") or "")
    source_id = str(pnu.get("source_id") or "")
    source_name = str(pnu.get("source_name") or source_id or "PNU notice")

    add_text(element, "title", str(item.get("title") or item_id))
    add_text(element, "link", str(item.get("url") or ""))
    guid = add_text(element, "guid", item_id)
    guid.set("isPermaLink", "false")
    add_text(
        element,
        "pubDate",
        rss_datetime(item.get("date_published") or pnu.get("published_at")),
    )
    add_text(element, "description", rss_description(item))
    add_text(element, "category", source_id)
    source = add_text(element, "source", source_name)
    source_url = source_urls.get(source_id)
    if source_url:
        source.set("url", str(source_url))
    return element


def rss_description(item: dict) -> str:
    pnu = item.get("_pnu", {})
    summary = item.get("summary") or pnu.get("snippet") or ""
    if summary:
        return str(summary)
    return CONTENT_TEXT_NOTICE


def add_text(parent: ElementTree.Element, tag: str, value: str) -> ElementTree.Element:
    child = ElementTree.SubElement(parent, tag)
    child.text = value
    return child


def rss_datetime(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return format_datetime(parsed)


def notice_to_feed_item(
    notice: Notice,
    fetched_at: str,
    snippet_limit: int = DEFAULT_SNIPPET_LIMIT,
) -> dict:
    snippet = truncate_text(sanitize_preview_text(notice.snippet), snippet_limit)
    pnu = {
        "source_id": notice.source_id,
        "source_name": notice.source_name,
        "published_at": notice.published_at,
        "fetched_at": fetched_at,
        "snippet": snippet,
        "content_access": default_content_access(notice.url),
        "attachments": [
            attachment_to_feed_json(attachment)
            for attachment in notice.attachments
        ],
        "tags": notice.tags,
        "content_hash": notice.content_hash,
    }
    if notice.detail_checked_at:
        pnu = {**pnu, "detail_checked_at": notice.detail_checked_at}
    return {
        "id": notice.notice_id,
        "url": notice.url,
        "title": notice.title,
        "content_text": CONTENT_TEXT_NOTICE,
        "summary": snippet,
        "date_published": date_to_json_feed_timestamp(notice.published_at),
        "_pnu": pnu,
    }


def normalize_feed_item(item: dict) -> dict:
    pnu = item.get("_pnu", {})
    snippet = sanitize_preview_text(pnu.get("snippet"))
    summary = sanitize_preview_text(item.get("summary", snippet))
    normalized = {
        **item,
        "content_text": CONTENT_TEXT_NOTICE,
        "summary": summary,
    }
    return {
        **normalized,
        "_pnu": {
            **pnu,
            "snippet": snippet,
        },
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
        "duration_ms": result.duration_ms,
        "item_count": len(result.items),
        "error_type": error_type(result.error),
        "error": result.error,
    }


def build_public_index(
    latest: dict,
    status: dict,
    run_diff: dict,
    duplicates: dict,
    archives: dict,
    events: dict,
    diagnostics: dict | None = None,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
) -> dict:
    base_url = public_base_url.rstrip("/")
    latest_pnu = latest.get("_pnu", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "feed_version": FEED_VERSION,
        "generated_at": latest_pnu.get("generated_at"),
        "title": "PNU Public Notice Feed",
        "description": DISCLAIMER,
        "home_page_url": base_url,
        "endpoints": {
            "index": f"{base_url}/index.json",
            "events": f"{base_url}/events.json",
            "latest": f"{base_url}/latest.json",
            "rss": f"{base_url}/rss.xml",
            "openapi": f"{base_url}/openapi.json",
            "llms": f"{base_url}/llms.txt",
            "archive_url_pattern": f"{base_url}/archive/{{YYYY-MM}}.json",
        },
        "data_boundary": {
            "metadata_relay": True,
            "content_mirrored": False,
            "attachments_mirrored": False,
            "requires_login": False,
            "official_service": False,
        },
        "event_stream": {
            "url": "./events.json",
            "event_count": events.get("event_count"),
            "total_event_count": events.get("total_event_count"),
            "event_limit": events.get("event_limit"),
            "latest_event_id": events.get("latest_event_id"),
            "oldest_event_id": events.get("oldest_event_id"),
            "oldest_seen_at": events.get("oldest_seen_at"),
            "latest_seen_at": events.get("latest_seen_at"),
            "is_truncated": events.get("is_truncated"),
        },
        "latest": {
            "url": "./latest.json",
            "item_count": latest_pnu.get("item_count"),
            "total_item_count": latest_pnu.get("total_item_count"),
            "item_limit": latest_pnu.get("item_limit"),
        },
        "status": {
            "overall_status": status.get("overall_status"),
            "source_count": status.get("source_count"),
            "ok_source_count": status.get("ok_source_count"),
            "skipped_source_count": status.get("skipped_source_count"),
            "poll_interval_skipped_source_count": status.get(
                "poll_interval_skipped_source_count"
            ),
            "backoff_source_count": status.get("backoff_source_count"),
            "error_source_count": status.get("error_source_count"),
            "degraded_source_count": status.get(
                "degraded_source_count",
                status.get("failed_source_count"),
            ),
            "failed_source_count": status.get("failed_source_count"),
            "status_counts": status.get("status_counts", {}),
            "skipped_reason_counts": status.get("skipped_reason_counts", {}),
            "sources": status.get("sources", []),
        },
        "archives": archives,
        "dedupe_policy": duplicates.get("policy", {}),
        "same_notice_groups": duplicates.get("groups", []),
        "same_notice_group_count": duplicates.get("group_count", 0),
        "diagnostics": {
            "run": diagnostics or {},
            "latest_run_diff": run_diff,
        },
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


def write_outputs(
    output_dir: Path,
    latest: dict,
    rss: str,
    status: dict,
    run_diff: dict,
    duplicates: dict,
    state: dict,
    diagnostics: dict,
    baseline_source_ids: list[str],
    public_base_url: str,
    pretty: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_legacy_public_outputs(output_dir)
    write_json(output_dir / "latest.json", latest, pretty)
    write_text_if_changed(output_dir / "rss.xml", rss)
    archives, events = write_archive_outputs(
        output_dir,
        archive_input_from_state(state, baseline_source_ids=baseline_source_ids),
        pretty,
    )
    diagnostics_with_outputs = {
        **diagnostics,
        "output": build_output_file_diagnostics(output_dir),
    }
    write_json(
        output_dir / "index.json",
        build_public_index(
            latest=latest,
            status=status,
            run_diff=run_diff,
            duplicates=duplicates,
            archives=archives,
            events=events,
            diagnostics=diagnostics_with_outputs,
            public_base_url=public_base_url,
        ),
        pretty,
    )


def sync_static_assets(
    output_dir: Path,
    sources_path: Path,
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_text_if_changed(output_dir / "index.html", INDEX_HTML)
    copy_text_with_base_url(
        PROJECT_ROOT / "openapi.json",
        output_dir / "openapi.json",
        public_base_url,
    )
    write_text_if_changed(output_dir / "llms.txt", LLMS_TXT)

    schema_output_dir = output_dir / "schema"
    schema_output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_stale_schema_outputs(schema_output_dir)
    for schema_path in sorted((PROJECT_ROOT / "schema").glob("*.schema.json")):
        copy_text_with_base_url(
            schema_path,
            schema_output_dir / schema_path.name,
            public_base_url,
        )


def cleanup_legacy_public_outputs(output_dir: Path) -> None:
    for name in [
        "feed.json",
        "status.json",
        "run-diff.json",
        "duplicates.json",
        "sources.json",
    ]:
        path = output_dir / name
        if path.exists():
            path.unlink()


def cleanup_stale_schema_outputs(schema_output_dir: Path) -> None:
    wanted = {
        schema_path.name
        for schema_path in (PROJECT_ROOT / "schema").glob("*.schema.json")
    }
    for schema_path in schema_output_dir.glob("*.schema.json"):
        if schema_path.name not in wanted:
            schema_path.unlink()


def outputs_exist(output_dir: Path, state_path: Path) -> bool:
    return all(
        path.exists()
        for path in [
            output_dir / "index.json",
            output_dir / "latest.json",
            output_dir / "rss.xml",
            output_dir / "events.json",
            state_path,
        ]
    )


def outputs_match_public_base_url(output_dir: Path, public_base_url: str) -> bool:
    latest = read_json_if_exists(output_dir / "latest.json")
    index = read_json_if_exists(output_dir / "index.json")
    if not latest or not index:
        return False
    base_url = public_base_url.rstrip("/")
    return (
        latest.get("feed_url") == f"{base_url}/latest.json"
        and index.get("home_page_url") == base_url
    )


def outputs_match_source_metadata(output_dir: Path, latest: dict) -> bool:
    previous_latest = read_json_if_exists(output_dir / "latest.json")
    if not previous_latest:
        return False
    return public_source_signatures(previous_latest) == public_source_signatures(latest)


def should_write_public_outputs(
    output_dir: Path,
    state_path: Path,
    generated: dict,
    public_base_url: str,
) -> bool:
    if not outputs_exist(output_dir, state_path):
        return True
    if not outputs_match_public_base_url(output_dir, public_base_url):
        return True
    if not outputs_match_source_metadata(output_dir, generated["latest"]):
        return True
    if not outputs_match_current_format(output_dir):
        return True
    if not archive_outputs_exist(output_dir):
        return True
    if not archive_outputs_match_current_versions(output_dir):
        return True
    if run_diff_has_notice_changes(generated["run_diff"]):
        return True
    previous_index = read_json_if_exists(output_dir / "index.json")
    if not previous_index:
        return True
    return status_signature(previous_index.get("status", {})) != status_signature(
        generated["status"]
    )


def run_diff_has_notice_changes(run_diff: dict) -> bool:
    return any(
        int(run_diff.get(key) or 0) > 0
        for key in ["added_count", "updated_count", "removed_count"]
    )


def status_signature(status: dict) -> dict:
    return {
        "overall_status": status.get("overall_status"),
        "source_count": status.get("source_count"),
        "failed_source_count": status.get("failed_source_count"),
        "sources": [
            source_status_signature(source)
            for source in status.get("sources", [])
        ],
    }


def source_status_signature(source: dict) -> dict:
    skipped_reason = source.get("skipped_reason")
    status = source.get("status")
    if status == "skipped" and skipped_reason == "poll_interval":
        status = "ok"
        skipped_reason = None
    return {
        "id": source.get("id"),
        "status": status,
        "error_type": source.get("error_type"),
        "error_count": source.get("error_count"),
        "skipped_reason": skipped_reason,
    }


def public_source_signatures(latest: dict) -> list[dict]:
    return [
        {
            "id": source.get("id"),
            "name": source.get("name"),
            "official_url": source.get("official_url"),
            "adapter": source.get("adapter"),
            "category": source.get("category"),
            "poll_interval_minutes": source.get("poll_interval_minutes"),
            "public_only": source.get("public_only"),
            "access_policy": source.get("access_policy"),
        }
        for source in latest.get("_pnu", {}).get("sources", [])
    ]


def outputs_match_current_format(output_dir: Path) -> bool:
    latest = read_json_if_exists(output_dir / "latest.json")
    index = read_json_if_exists(output_dir / "index.json")
    if not latest or not index:
        return False
    status = index.get("status", {})
    for key in [
        "status_counts",
        "skipped_reason_counts",
        "degraded_source_count",
        "poll_interval_skipped_source_count",
        "backoff_source_count",
        "error_source_count",
    ]:
        if key not in status:
            return False
    if not (output_dir / "index.html").exists():
        return False
    if any(
        (output_dir / path).exists()
        for path in [
            "feed.json",
            "status.json",
            "run-diff.json",
            "duplicates.json",
            "sources.json",
            "archive/index.json",
        ]
    ):
        return False
    for item in latest.get("items", []):
        if item.get("content_text") != CONTENT_TEXT_NOTICE:
            return False
        if "summary" not in item:
            return False
    return True


def archive_outputs_match_current_versions(output_dir: Path) -> bool:
    events = read_json_if_exists(output_dir / "events.json")
    if not events or events.get("event_stream_version") != EVENT_STREAM_VERSION:
        return False

    index = read_json_if_exists(output_dir / "index.json")
    if not index:
        return False
    for entry in index.get("archives", {}).get("months", []):
        url = str(entry.get("url") or "")
        if not url:
            return False
        doc = read_json_if_exists(output_dir / url.removeprefix("./"))
        if not doc or doc.get("archive_version") != ARCHIVE_VERSION:
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


def build_output_file_diagnostics(output_dir: Path) -> dict:
    paths = sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file()
    )
    files = [
        {
            "path": str(path.relative_to(output_dir)),
            "bytes": path.stat().st_size,
        }
        for path in paths
        if path.exists()
    ]
    archive_files = [
        file
        for file in files
        if str(file["path"]).startswith("archive/")
    ]
    return {
        "file_count": len(files),
        "total_bytes": sum(file["bytes"] for file in files),
        "archive_file_count": len(archive_files),
        "archive_total_bytes": sum(file["bytes"] for file in archive_files),
        "largest_files": sorted(
            files,
            key=lambda file: file["bytes"],
            reverse=True,
        )[:20],
        "files": files,
    }


def build_size_budget_diagnostics(
    output_dir: Path,
    state_path: Path | None = None,
    runtime_ms: int | None = None,
) -> dict:
    output = build_output_file_diagnostics(output_dir)
    state_bytes = state_path.stat().st_size if state_path and state_path.exists() else 0
    largest_public_file = max(
        [file["bytes"] for file in output["files"]],
        default=0,
    )
    checks = [
        size_budget_check(
            "public_total",
            output["total_bytes"],
            SIZE_BUDGETS["public_total"]["warning_bytes"],
            SIZE_BUDGETS["public_total"]["failure_bytes"],
            unit="bytes",
        ),
        size_budget_check(
            "archive_total",
            output["archive_total_bytes"],
            SIZE_BUDGETS["archive_total"]["warning_bytes"],
            SIZE_BUDGETS["archive_total"]["failure_bytes"],
            unit="bytes",
        ),
        size_budget_check(
            "single_public_file",
            largest_public_file,
            SIZE_BUDGETS["single_public_file"]["warning_bytes"],
            SIZE_BUDGETS["single_public_file"]["failure_bytes"],
            unit="bytes",
        ),
        size_budget_check(
            "state_file",
            state_bytes,
            SIZE_BUDGETS["state_file"]["warning_bytes"],
            SIZE_BUDGETS["state_file"]["failure_bytes"],
            unit="bytes",
        ),
    ]
    if runtime_ms is not None:
        checks = [
            *checks,
            size_budget_check(
                "generator_runtime",
                runtime_ms,
                SIZE_BUDGETS["generator_runtime"]["warning_ms"],
                SIZE_BUDGETS["generator_runtime"]["failure_ms"],
                unit="ms",
            ),
        ]
    overall_status = "ok"
    if any(check["status"] == "fail" for check in checks):
        overall_status = "fail"
    elif any(check["status"] == "warn" for check in checks):
        overall_status = "warn"
    return {
        "schema_version": SCHEMA_VERSION,
        "overall_status": overall_status,
        "output": output,
        "state": {
            "path": str(state_path) if state_path else None,
            "bytes": state_bytes,
        },
        "checks": checks,
    }


def size_budget_check(
    name: str,
    value: int,
    warning: int,
    failure: int,
    unit: str,
) -> dict:
    status = "ok"
    if value >= failure:
        status = "fail"
    elif value >= warning:
        status = "warn"
    return {
        "name": name,
        "status": status,
        "value": value,
        "warning": warning,
        "failure": failure,
        "unit": unit,
    }


def assert_size_budget(diagnostics: dict) -> None:
    failures = [
        check
        for check in diagnostics.get("checks", [])
        if check.get("status") == "fail"
    ]
    if failures:
        names = ", ".join(str(check.get("name")) for check in failures)
        raise ValueError(f"feed size budget exceeded: {names}")


def print_feed_health_snapshot(output_dir: Path, state_path: Path) -> None:
    try:
        from scripts.check_feed_health import Thresholds, check_feed_health
    except ModuleNotFoundError:
        return

    report = check_feed_health(
        public_dir=output_dir,
        state_path=state_path,
        base_url=None,
        timeout_seconds=1,
        thresholds=Thresholds(
            max_degraded_sources=100,
            max_backoff_sources=100,
            max_error_sources=50,
            max_public_total_mib=500,
            max_state_mib=50,
            min_event_count=1,
            fail_on_truncated_events=False,
        ),
    )
    print()
    print("\n".join(report.lines))
    for warning in report.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if report.issues:
        raise ValueError("feed health check failed: " + "; ".join(report.issues))


def build_run_diff(previous_state: dict | None, current_state: dict) -> dict:
    previous_items = state_items_by_id(previous_state)
    current_items = state_items_by_id(current_state)

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
        "run_diff_scope": "latest_generator_run",
        "durable_history": False,
        "removed_semantics": (
            "missing_from_current_generator_state_not_official_deletion"
        ),
        "generated_at": current_state["generated_at"],
        "previous_generated_at": (
            previous_state.get("generated_at")
            if previous_state
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


def archive_input_from_state(
    state: dict,
    baseline_source_ids: list[str] | None = None,
) -> dict:
    return {
        "_pnu": {
            "generated_at": state["generated_at"],
            "baseline_source_ids": baseline_source_ids or [],
        },
        "items": list(state_items_by_id(state).values()),
    }


def state_items_by_id(state: dict | None) -> dict[str, dict]:
    if not state:
        return {}
    items: dict[str, dict] = {}
    for source_state in state.get("sources", {}).values():
        for item_id, item in cached_items_by_id(source_state).items():
            items = {**items, item_id: item}
    return items


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


def sanitize_preview_text(value: str | None) -> str | None:
    if value is None:
        return None
    return SENSITIVE_QUERY_PARAM_RE.sub(r"\1[redacted]", value)


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
    current = parse_iso(checked_at)
    backoff_until = source_state.get("backoff_until")
    if backoff_until and parse_iso(backoff_until) > current:
        return "backoff", backoff_until

    if not source_state.get("items"):
        return None, None

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


def source_result_with_duration(
    result: SourceResult,
    started_at: float,
) -> SourceResult:
    return replace(result, duration_ms=duration_ms_since(started_at))


def duration_ms_since(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def positive_int(value: int, name: str) -> int:
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def source_host(source: PublicSource) -> str:
    return urlparse(source.official_url).netloc.lower() or source.id


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
