#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urljoin
from urllib.request import Request, urlopen


DEFAULT_PUBLIC_DIR = Path("public")
DEFAULT_STATE_PATH = Path("cache/feed-state.json")
DEFAULT_TIMEOUT_SECONDS = 20
BYTES_PER_MIB = 1024 * 1024


@dataclass(frozen=True)
class LoadedJson:
    name: str
    data: dict[str, Any]
    byte_count: int


@dataclass(frozen=True)
class SizeSummary:
    public_total_bytes: int | None
    archive_total_bytes: int | None
    state_bytes: int | None
    index_bytes: int
    events_bytes: int
    latest_bytes: int


@dataclass(frozen=True)
class Thresholds:
    max_degraded_sources: int
    max_backoff_sources: int
    max_error_sources: int
    max_critical_degraded_sources: int
    max_public_total_mib: float | None
    max_state_mib: float | None
    min_event_count: int
    fail_on_truncated_events: bool


@dataclass(frozen=True)
class HealthReport:
    lines: list[str]
    warnings: list[str]
    issues: list[str]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    thresholds = Thresholds(
        max_degraded_sources=args.max_degraded_sources,
        max_backoff_sources=args.max_backoff_sources,
        max_error_sources=args.max_error_sources,
        max_critical_degraded_sources=args.max_critical_degraded_sources,
        max_public_total_mib=args.max_public_total_mib,
        max_state_mib=args.max_state_mib,
        min_event_count=args.min_event_count,
        fail_on_truncated_events=args.fail_on_truncated_events,
    )
    try:
        report = check_feed_health(
            public_dir=args.public_dir,
            state_path=args.state_path,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
            thresholds=thresholds,
        )
    except Exception as error:  # noqa: BLE001 - CLI should report any health load failure.
        print(f"feed health check failed to run: {error}", file=sys.stderr)
        return 2

    print("\n".join(report.lines))
    for warning in report.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for issue in report.issues:
        print(f"ERROR: {issue}", file=sys.stderr)
    return 1 if report.issues else 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check PNU Public Notice Feed health from local public files or a deployed base URL.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--public-dir",
        type=Path,
        default=DEFAULT_PUBLIC_DIR,
        help="Local public output directory to inspect.",
    )
    source.add_argument(
        "--base-url",
        help="Published feed base URL to inspect, for example https://example.github.io/feed/.",
    )
    parser.add_argument(
        "--state-path",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="Local generator state file for size reporting.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout when --base-url is used.",
    )
    parser.add_argument(
        "--max-degraded-sources",
        type=int,
        default=100,
        help="Fail when degraded source count exceeds this value.",
    )
    parser.add_argument(
        "--max-backoff-sources",
        type=int,
        default=100,
        help="Fail when backoff source count exceeds this value.",
    )
    parser.add_argument(
        "--max-error-sources",
        type=int,
        default=50,
        help="Fail when error source count exceeds this value.",
    )
    parser.add_argument(
        "--max-critical-degraded-sources",
        type=int,
        default=0,
        help="Fail when degraded critical source count exceeds this value.",
    )
    parser.add_argument(
        "--max-public-total-mib",
        type=float,
        default=500,
        help="Fail when local public/ output exceeds this size. Ignored with --base-url.",
    )
    parser.add_argument(
        "--max-state-mib",
        type=float,
        default=50,
        help="Fail when local state file exceeds this size. Ignored with --base-url.",
    )
    parser.add_argument(
        "--min-event-count",
        type=int,
        default=1,
        help="Fail when events.json has fewer events than this.",
    )
    parser.add_argument(
        "--fail-on-truncated-events",
        action="store_true",
        help="Fail if events.json is truncated. By default this is only a warning.",
    )
    return parser.parse_args(argv)


def check_feed_health(
    public_dir: Path,
    state_path: Path,
    base_url: str | None,
    timeout_seconds: int,
    thresholds: Thresholds,
) -> HealthReport:
    index = load_json("index.json", public_dir, base_url, timeout_seconds)
    events = load_json("events.json", public_dir, base_url, timeout_seconds)
    latest = load_json("latest.json", public_dir, base_url, timeout_seconds)
    sizes = build_size_summary(
        public_dir=public_dir,
        state_path=state_path,
        base_url=base_url,
        index=index,
        events=events,
        latest=latest,
    )
    return build_report(index.data, events.data, latest.data, sizes, thresholds)


def load_json(
    name: str,
    public_dir: Path,
    base_url: str | None,
    timeout_seconds: int,
) -> LoadedJson:
    if base_url:
        url = urljoin(base_url.rstrip("/") + "/", name)
        request = Request(
            url,
            headers={"User-Agent": "pnu-public-notice-feed-health-check/0.1"},
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
        return LoadedJson(name=name, data=json.loads(raw.decode("utf-8")), byte_count=len(raw))

    path = public_dir / name
    raw = path.read_bytes()
    return LoadedJson(name=name, data=json.loads(raw.decode("utf-8")), byte_count=len(raw))


def build_size_summary(
    public_dir: Path,
    state_path: Path,
    base_url: str | None,
    index: LoadedJson,
    events: LoadedJson,
    latest: LoadedJson,
) -> SizeSummary:
    if base_url:
        return SizeSummary(
            public_total_bytes=None,
            archive_total_bytes=None,
            state_bytes=None,
            index_bytes=index.byte_count,
            events_bytes=events.byte_count,
            latest_bytes=latest.byte_count,
        )

    public_total = sum(path.stat().st_size for path in public_dir.rglob("*") if path.is_file())
    archive_dir = public_dir / "archive"
    archive_total = (
        sum(path.stat().st_size for path in archive_dir.glob("*.json") if path.is_file())
        if archive_dir.exists()
        else 0
    )
    return SizeSummary(
        public_total_bytes=public_total,
        archive_total_bytes=archive_total,
        state_bytes=state_path.stat().st_size if state_path.exists() else None,
        index_bytes=index.byte_count,
        events_bytes=events.byte_count,
        latest_bytes=latest.byte_count,
    )


def build_report(
    index: dict[str, Any],
    events: dict[str, Any],
    latest: dict[str, Any],
    sizes: SizeSummary,
    thresholds: Thresholds,
) -> HealthReport:
    warnings: list[str] = []
    issues: list[str] = []
    status = dict_value(index, "status")
    event_stream = dict_value(index, "event_stream")
    latest_index = dict_value(index, "latest")
    latest_pnu = dict_value(latest, "_pnu")

    overall_status = string_value(status, "overall_status")
    source_count = int_value(status, "source_count")
    sources = list_value(status, "sources")
    degraded_count = int_value(
        status,
        "degraded_source_count",
        int_value(status, "failed_source_count"),
    )
    critical_degraded_count = int_value(status, "critical_degraded_source_count")
    backoff_count = int_value(status, "backoff_source_count")
    error_count = int_value(status, "error_source_count")
    poll_skip_count = int_value(status, "poll_interval_skipped_source_count")
    event_count = int_value(events, "event_count")
    total_event_count = int_value(events, "total_event_count")
    event_limit = int_value(events, "event_limit")
    is_truncated = bool(events.get("is_truncated"))
    latest_count = int_value(latest_pnu, "item_count")
    latest_total_count = int_value(latest_pnu, "total_item_count")
    same_notice_group_count = int_value(index, "same_notice_group_count")

    if overall_status not in {"ok", "partial"}:
        issues = [*issues, f"unexpected overall_status: {overall_status}"]
    if source_count != len(sources):
        issues = [*issues, f"source_count {source_count} does not match sources length {len(sources)}"]
    if degraded_count > thresholds.max_degraded_sources:
        issues = [
            *issues,
            f"degraded_source_count {degraded_count} exceeds {thresholds.max_degraded_sources}",
        ]
    if backoff_count > thresholds.max_backoff_sources:
        issues = [*issues, f"backoff_source_count {backoff_count} exceeds {thresholds.max_backoff_sources}"]
    if error_count > thresholds.max_error_sources:
        issues = [*issues, f"error_source_count {error_count} exceeds {thresholds.max_error_sources}"]
    if critical_degraded_count > thresholds.max_critical_degraded_sources:
        issues = [
            *issues,
            (
                "critical_degraded_source_count "
                f"{critical_degraded_count} exceeds "
                f"{thresholds.max_critical_degraded_sources}"
            ),
        ]
    if event_count < thresholds.min_event_count:
        issues = [*issues, f"event_count {event_count} is below {thresholds.min_event_count}"]
    if event_count != len(list_value(events, "events")):
        issues = [*issues, "events.event_count does not match events array length"]
    if event_count != int_value(event_stream, "event_count"):
        issues = [*issues, "index.event_stream.event_count does not match events.json"]
    if latest_count != len(list_value(latest, "items")):
        issues = [*issues, "latest item_count does not match latest.items length"]
    if latest_count != int_value(latest_index, "item_count"):
        issues = [*issues, "index.latest.item_count does not match latest.json"]
    if is_truncated:
        message = "events.json is truncated; consumers with older cursors need archive catch-up"
        if thresholds.fail_on_truncated_events:
            issues = [*issues, message]
        else:
            warnings = [*warnings, message]
    if sizes.public_total_bytes is not None and thresholds.max_public_total_mib is not None:
        public_limit = int(thresholds.max_public_total_mib * BYTES_PER_MIB)
        if sizes.public_total_bytes > public_limit:
            issues = [*issues, f"public output size {mib(sizes.public_total_bytes)} exceeds {thresholds.max_public_total_mib:.2f} MiB"]
    if sizes.state_bytes is not None and thresholds.max_state_mib is not None:
        state_limit = int(thresholds.max_state_mib * BYTES_PER_MIB)
        if sizes.state_bytes > state_limit:
            issues = [*issues, f"state size {mib(sizes.state_bytes)} exceeds {thresholds.max_state_mib:.2f} MiB"]
    diagnostics = dict_value(index, "diagnostics")
    archive_coverage = dict_value(diagnostics, "archive_coverage") or dict_value(
        dict_value(diagnostics, "run"),
        "archive_coverage",
    )
    missing_archive_count = int_value(archive_coverage, "missing_current_state_item_count")
    if missing_archive_count > 0:
        issues = [
            *issues,
            f"archive coverage missing {missing_archive_count} current state items",
        ]

    degraded_sources = [
        source
        for source in sources
        if source.get("status") == "error" or source.get("skipped_reason") == "backoff"
    ]
    lines = [
        "PNU Public Notice Feed health snapshot",
        f"generated_at: {index.get('generated_at')}",
        f"overall_status: {overall_status}",
        (
            "sources: "
            f"{source_count} "
            f"(ok {int_value(status, 'ok_source_count')}, "
            f"skipped {int_value(status, 'skipped_source_count')}, "
            f"poll_interval {poll_skip_count}, "
            f"backoff {backoff_count}, "
            f"error {error_count}, "
            f"degraded {degraded_count}, "
            f"critical_degraded {critical_degraded_count})"
        ),
        (
            "events: "
            f"{event_count}/{total_event_count} "
            f"(limit {event_limit}, truncated {str(is_truncated).lower()})"
        ),
        f"latest: {latest_count}/{latest_total_count}",
        f"same_notice_groups: {same_notice_group_count}",
        "sizes:",
        f"  index.json: {mib(sizes.index_bytes)}",
        f"  events.json: {mib(sizes.events_bytes)}",
        f"  latest.json: {mib(sizes.latest_bytes)}",
    ]
    if sizes.public_total_bytes is not None:
        lines = [*lines, f"  public_total: {mib(sizes.public_total_bytes)}"]
    if sizes.archive_total_bytes is not None:
        lines = [*lines, f"  archive_total: {mib(sizes.archive_total_bytes)}"]
    if sizes.state_bytes is not None:
        lines = [*lines, f"  state: {mib(sizes.state_bytes)}"]
    if archive_coverage:
        lines = [
            *lines,
            (
                "archive_coverage: "
                f"{'ok' if archive_coverage.get('ok') else 'fail'} "
                f"(state {int_value(archive_coverage, 'state_item_count')}, "
                f"archive {int_value(archive_coverage, 'archive_item_count')}, "
                f"missing {missing_archive_count})"
            ),
        ]
    if degraded_sources:
        lines = [
            *lines,
            "degraded_sources:",
            *[format_degraded_source(source) for source in degraded_sources],
        ]
    else:
        lines = [*lines, "degraded_sources: none"]
    lines = [*lines, f"result: {'fail' if issues else 'ok'}"]
    return HealthReport(lines=lines, warnings=warnings, issues=issues)


def dict_value(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def list_value(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    return value if isinstance(value, list) else []


def int_value(data: dict[str, Any], key: str, default: int = 0) -> int:
    value = data.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def string_value(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return str(value) if value is not None else ""


def format_degraded_source(source: Any) -> str:
    if not isinstance(source, dict):
        return "- <invalid source entry>"
    return (
        f"- {source.get('id')} "
        f"status={source.get('status')} "
        f"skipped_reason={source.get('skipped_reason')} "
        f"error_count={source.get('error_count')} "
        f"last_success_at={source.get('last_success_at')} "
        f"backoff_until={source.get('backoff_until')} "
        f"error_type={source.get('error_type')}"
    )


def mib(byte_count: int | None) -> str:
    if byte_count is None:
        return "n/a"
    return f"{byte_count / BYTES_PER_MIB:.2f} MiB"


if __name__ == "__main__":
    raise SystemExit(main())
