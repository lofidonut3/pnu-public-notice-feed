# PNU Public Notice Feed

Unofficial AI-friendly JSON/RSS metadata feed for public notices from Pusan National University (PNU, 부산대학교, 부산대).

This repository generates and publishes a compact static notice feed surface that normalizes 부산대학교 공지사항 metadata from multiple official public PNU notice sources. It is designed for AI agents, developers, and students who need a stable machine-readable index of public university notices.

This project is not operated by Pusan National University.

Current indexed source families include university-wide notices, Onestop academic and scholarship notices, college/department/major academic-unit notices, dormitory notices by campus, PNU International notices, Career Development Office notices and recruitment listings, PNU Library notices, public campus-service notices, support-center notices, language education notices, project notices, and public PLATO notices. Source registry metadata and source status are published in [`index.json`](https://lofidonut3.github.io/pnu-public-notice-feed/index.json).

## Endpoints

Published GitHub Pages URL:

```text
https://lofidonut3.github.io/pnu-public-notice-feed/
```

Available endpoints:

- [`index.json`](https://lofidonut3.github.io/pnu-public-notice-feed/index.json): manifest with endpoint URLs, sources, source status, archive manifest, same-notice groups, and diagnostics
- [`events.json`](https://lofidonut3.github.io/pnu-public-notice-feed/events.json): primary recent event stream for cursor-based agent checks
- [`latest.json`](https://lofidonut3.github.io/pnu-public-notice-feed/latest.json): JSON Feed 1.1 compatible latest-discovery notice metadata, currently limited to the latest 150 items globally
- [`rss.xml`](https://lofidonut3.github.io/pnu-public-notice-feed/rss.xml): RSS 2.0 compatibility feed for feed readers and automation tools
- `archive/YYYY-MM.json`: monthly durable archive containing notice metadata and observed events
- [`schema/*.schema.json`](https://lofidonut3.github.io/pnu-public-notice-feed/schema/index.schema.json): JSON Schemas
- [`openapi.json`](https://lofidonut3.github.io/pnu-public-notice-feed/openapi.json): static endpoint manifest
- [`llms.txt`](https://lofidonut3.github.io/pnu-public-notice-feed/llms.txt): AI agent usage guide
- [`robots.txt`](https://lofidonut3.github.io/pnu-public-notice-feed/robots.txt) and [`sitemap.xml`](https://lofidonut3.github.io/pnu-public-notice-feed/sitemap.xml): crawler discovery hints

## Data Boundary

This project is a metadata relay, not a content mirror.

Each latest item and archive item includes a title, source, original notice URL, published date, short preview, content access metadata, and attachment metadata. `events.json` is a compact cursor stream for detecting and routing recent notice events. Full notice text and attachment contents stay on the official PNU source pages.

Agents should treat `summary` and `_pnu.snippet` as previews only. Fetch full notice text from `item.url` or `item._pnu.content_access.detail_url`, and fetch attachments from `item._pnu.attachments[].download_url`.

## Endpoint Roles

- `index.json` is the manifest. It combines source registry, source status, archive manifest, same-notice groups, and latest run diagnostics.
- `events.json` is the primary compact cursor endpoint for notice checks. Store a local `latest_event_id` or `seen_at` cursor and process newer events. Event records include routing fields and same-notice duplicate fields for notification dedupe.
- `archive/YYYY-MM.json` is the durable monthly archive for catch-up when a local cursor is older than the `events.json` window.
- `latest.json` is a JSON Feed 1.1 compatible latest-discovery endpoint, currently limited to the latest 150 items globally. It is not the primary cursor endpoint and not a complete archive.
- `rss.xml` is a compatibility endpoint for RSS readers and legacy automation tools.

No project-specific client library is required. Any HTTP/JSON client can read `events.json`, keep its own cursor, and fetch archive files when detailed metadata is needed.

For AI agents reading this repository directly, start with [`llms.txt`](./llms.txt), then use the published [`events.json`](https://lofidonut3.github.io/pnu-public-notice-feed/events.json) cursor stream and [`index.json`](https://lofidonut3.github.io/pnu-public-notice-feed/index.json) manifest.

## Example Consumer

For a concrete optional reference CLI/helper that keeps a local cursor, enriches events from archive metadata, and collapses same-notice duplicate groups, see [`pnu-notice-agent-tools`](https://github.com/lofidonut3/pnu-notice-agent-tools).

## Operations

- Source refresh status is published in `index.json.status`.
- Recent durable notice events are published in `events.json` for cursor-based agent checks.
- Agents should store a local `latest_event_id` or `seen_at` cursor, then process newer events from `events.json`. If the cursor is older than the `events.json` window, use `index.json.archives` and monthly archive files.
- Events include routing metadata, duplicate metadata, topic hints, and monthly archive lookup fields. Full item metadata is available through `archive_file` and `archive_item_id`.
- Use event `same_notice_group_id`, `canonical_item_id`, `is_canonical`, and `same_notice_source_ids` before sending notifications for multiple matching items from different sources. `index.json.same_notice_groups` provides the full same-notice manifest and fallback lookup.
- Source polling is rate-limited by `sources.json` and cached in `cache/feed-state.json`.
- K2Web sources recover after an outage by paging from the newest list until a previously known non-pinned notice ID is found. A missing boundary fails that source closed and preserves its last known-good items.
- Failed sources use cached items when available and report errors in `index.json.status`.
- `index.json.status.overall_status` can be `partial` when some sources are in error/backoff. `partial` means the feed is usable but some source freshness is degraded; inspect the relevant source's `last_success_at`, `last_error_at`, `backoff_until`, and `error_count` before relying on that source.
- K2Web boards whose first pages contain only site-wide pinned notices use the newest cached publication date as their catch-up boundary. This prevents repeated deep pagination and avoids publishing old board history as new events.
- `status.skipped_reason: poll_interval` is normal rate limiting, not a source failure. Use `degraded_source_count`, `backoff_source_count`, `error_source_count`, `status_counts`, and `skipped_reason_counts` to distinguish normal skips from freshness risk.
- Long-term notice metadata is retained in monthly `archive/` files.
- Archive files retain metadata only. Full notice text and attachment contents stay on official source URLs.
- Schema changes are tracked with `_pnu.schema_version` and `_pnu.feed_version`.
- Source importance, freshness budgets, and suspension reasons are explicit in `sources.json` and published source status. `status: disabled` means historical metadata is retained while that source is not polled or included in the latest-discovery feed. It must not be interpreted as a fresh successful source.
- Successful real polls refresh published health timestamps even when no notices change. Ordinary poll-interval skips retain the previous successful observation, so a quiet board is distinguishable from a stalled collector.
- Publication dates come from publication-date cells, never dates embedded in titles. Verified historical corrections retain canonical notice IDs, event IDs, and first observation times; notices move to the correct publication month and event archive references follow them.
- The library's November 9, 2026 site migration changed upstream identifiers. Unique title/date matches and recorded upstream aliases preserve existing canonical IDs while official URLs change. Ambiguous or removed legacy records explicitly publish `content_access.availability`; do not fetch them as if they were available articles. A `replacement_url` is a current related record, not a promise that the original historical body is unchanged.
- Selected scholarship, international and department boards check body fingerprints for the three newest visible notices at most once every 12 hours. Only the fingerprint is retained. Other K2Web records detect list metadata changes; this does not promise detection of every body/attachment change. Initial body fingerprints form a quiet baseline rather than a false update event.

## Generate Locally

Requirements:

- Python 3.12+
- Node.js 24+

Generate the feed:

```bash
python3 -m pnu_notice_feed.generator --pretty
```

Use a custom published base URL:

```bash
python3 -m pnu_notice_feed.generator --pretty --public-base-url "https://example.com/pnu-public-notice-feed"
```

## Test

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
```

Check the generated feed health snapshot:

```bash
python3 scripts/check_feed_health.py --public-dir public --state-path cache/feed-state.json
```

The health CLI fails when the feed is older than 120 minutes, an active source exceeds its configured freshness budget, or a selected detail fingerprint check fails. A disabled source is reported as historical, with its reason. To inspect stored schemas, exact archive checksums and event references independently of the generator:

```bash
python3 scripts/verify_feed.py
```

Metadata repair is dry-run by default. The versioned evidence file contains only official metadata and provenance URLs:

```bash
python3 scripts/repair_feed_metadata.py --corrections verification/metadata-corrections-2026-11-09.json
# After reviewing the summary and retaining a snapshot:
python3 scripts/repair_feed_metadata.py --corrections verification/metadata-corrections-2026-11-09.json --apply
python3 -m pnu_notice_feed.generator --pretty --limit 80 --rebuild-outputs
```

Use `--force-source SOURCE_ID` for a bounded recovery of one registered source. `--force-refresh` explicitly bypasses polling/backoff once for all enabled sources.

## Publishing

The repository uses GitHub Actions:

- `.github/workflows/test.yml` runs tests on push and pull request.
- `.github/workflows/update-feed.yml` collects without a deployment environment, runs regressions and structural verification, commits generated output, and uploads an immutable artifact. Collection has its own concurrency group and a 15-minute runtime limit.
- `.github/workflows/deploy-feed.yml` consumes the successful collection artifact in a separate workflow. Only deployment uses the `github-pages` environment, so deployment protection waits cannot hold the collection lock. Deployed freshness is checked before the separate notification job runs.
- `.github/workflows/check-feed-health.yml` checks the deployed feed independently of collection/deployment concurrency. It can request one collection wake-up, avoids duplicating an active run, and stops automatic wake-ups after three failed collection runs. A wake-up is not reported as a verified recovery.
- Collection is scheduled at minutes 7 and 37; monitoring at 17 and 47. GitHub scheduling remains best effort and does not guarantee a 30-minute delivery SLA. An external monitor may use the same health CLI and dispatch hook.
- External watchdogs can trigger the same refresh workflow with a `repository_dispatch` event of type `update-feed`. This is the fallback path when GitHub scheduled workflows are delayed or skipped.
- After a successful deployment containing added or updated notices, the workflow can emit a `pnu-feed-updated` repository dispatch to the watch-runtime repository. The target defaults to `lofidonut3/pnu-notice-agent-tools`; set the optional repository variable `WATCH_DISPATCH_REPOSITORY` only to override it. Configure `WATCH_DISPATCH_TOKEN` as a secret permitted to create a dispatch in the target repository.
- The outbound dispatch is only a wake hint. Consumers must replay `events.json` from their own durable cursor, and should retain a periodic fallback scan so a missed or duplicated dispatch cannot lose an event.
- Notification authentication failures are reported by the notification job and do not undo a successful deployment. Permanent HTTP 4xx authentication/configuration errors fail immediately rather than retrying the same invalid credential.
- Feed freshness health reports failure when a critical source is degraded, when too many sources are degraded, or when the current generator state contains items that are missing from the durable archive. This report is non-blocking for publication; structural generation errors and size-budget violations remain blocking.
- The production workflow keeps up to 80 notices per source and retries critical source fetches once before publishing degraded status.
- Noncritical sources keep a single attempt unless their registry explicitly opts into a bounded retry. Glocal and museum boards allow two attempts because transient template responses were observed. Permanent HTTP 4xx errors fail immediately. Active noncritical freshness budgets allow three polling cycles, with a minimum of two hours; critical sources use two hours.

GitHub Pages should use GitHub Actions as its source.

## License

MIT
