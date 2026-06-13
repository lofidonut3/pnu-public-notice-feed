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
- Failed sources use cached items when available and report errors in `index.json.status`.
- `index.json.status.overall_status` can be `partial` when some sources are in error/backoff. `partial` means the feed is usable but some source freshness is degraded; inspect the relevant source's `last_success_at`, `last_error_at`, `backoff_until`, and `error_count` before relying on that source.
- `status.skipped_reason: poll_interval` is normal rate limiting, not a source failure. Use `degraded_source_count`, `backoff_source_count`, `error_source_count`, `status_counts`, and `skipped_reason_counts` to distinguish normal skips from freshness risk.
- Long-term notice metadata is retained in monthly `archive/` files.
- Archive files retain metadata only. Full notice text and attachment contents stay on official source URLs.
- Schema changes are tracked with `_pnu.schema_version` and `_pnu.feed_version`.

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

## Publishing

The repository uses GitHub Actions:

- `.github/workflows/test.yml` runs tests on push and pull request.
- `.github/workflows/update-feed.yml` refreshes the feed on a schedule, checks feed health, commits generated output when it changes, and deploys `public/` to GitHub Pages.
- Scheduled feed refresh runs every 30 minutes, subject to GitHub Actions scheduling delays.
- External watchdogs can trigger the same refresh workflow with a `repository_dispatch` event of type `update-feed`. This is the fallback path when GitHub scheduled workflows are delayed or skipped.
- Feed health fails when a critical source is degraded, when too many sources are degraded, or when the current generator state contains items that are missing from the durable archive.
- The production workflow keeps up to 80 notices per source and retries critical source fetches once before publishing degraded status.

GitHub Pages should use GitHub Actions as its source.

## License

MIT
