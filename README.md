# PNU Public Notice Feed

Unofficial public metadata feed for public notices from Pusan National University.

This repository generates and publishes a compact static notice feed surface that normalizes public notice metadata from multiple official PNU notice sources. It is designed for AI agents, developers, and students who need a stable machine-readable index of public notices.

This project is not operated by Pusan National University.

Current indexed source families include university-wide notices, Onestop academic and scholarship notices, dormitory notices by campus, PNU International notices, Career Development Office notices and recruitment listings, PNU Library notices, public campus-service notices, support-center notices, language education notices, project notices, and public PLATO notices. Source registry metadata and source status are published in [`index.json`](https://lofidonut3.github.io/pnu-public-notice-feed/index.json).

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

## Data Boundary

This project is a metadata relay, not a content mirror.

Each event item and latest item includes a title, source, original notice URL, published date, short preview, content access metadata, and attachment metadata. Full notice text and attachment contents stay on the official PNU source pages.

Agents should treat `summary` and `_pnu.snippet` as previews only. Fetch full notice text from `item.url` or `item._pnu.content_access.detail_url`, and fetch attachments from `item._pnu.attachments[].download_url`.

## Endpoint Roles

- `index.json` is the manifest. It combines source registry, source status, archive manifest, same-notice groups, and latest run diagnostics.
- `events.json` is the primary endpoint for AI agents doing cursor-based notice checks. Store a local `latest_event_id` or `seen_at` cursor and process newer events.
- `archive/YYYY-MM.json` is the durable monthly archive for catch-up when a local cursor is older than the `events.json` window.
- `latest.json` is a JSON Feed 1.1 compatible latest-discovery endpoint, currently limited to the latest 150 items globally. It is not the primary cursor endpoint and not a complete archive.
- `rss.xml` is a compatibility endpoint for RSS readers and legacy automation tools.

## Operations

- Source refresh status is published in `index.json.status`.
- Recent durable notice events are published in `events.json` for cursor-based agent checks.
- Agents should store a local `latest_event_id` or `seen_at` cursor, then process newer events from `events.json`. If the cursor is older than the `events.json` window, use `index.json.archives` and monthly archive files.
- Event metadata is included as an `item` snapshot. Monthly archive lookup is available through `archive_file` and `archive_item_id`.
- Check `index.json.same_notice_groups` before sending notifications for multiple matching items from different sources.
- Source polling is rate-limited by `sources.json` and cached in `cache/feed-state.json`.
- Failed sources use cached items when available and report errors in `index.json.status`.
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

## Publishing

The repository uses GitHub Actions:

- `.github/workflows/test.yml` runs tests on push and pull request.
- `.github/workflows/update-feed.yml` refreshes the feed on a schedule, commits generated output when it changes, and deploys `public/` to GitHub Pages.
- Scheduled feed refresh runs every 30 minutes, subject to GitHub Actions scheduling delays.

GitHub Pages should use GitHub Actions as its source.

## License

MIT
