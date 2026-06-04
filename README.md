# PNU Public Notice Feed

Unofficial public metadata feed for public notices from Pusan National University.

This repository generates and publishes a static JSON feed that normalizes public notice metadata from multiple official PNU notice sources. It is designed for AI agents, developers, and students who need a stable machine-readable index of public notices.

This project is not operated by Pusan National University.

## Endpoints

Published GitHub Pages URL:

```text
https://lofidonut3.github.io/pnu-public-notice-feed/
```

Available endpoints:

- `feed.json`: JSON Feed 1.1 compatible notice metadata feed
- `status.json`: source refresh status and source errors
- `changes.json`: added, updated, and removed item summary since the previous feed
- `sources.json`: public source registry
- `schema/*.schema.json`: JSON Schemas
- `openapi.json`: static endpoint manifest
- `llms.txt`: AI agent usage guide

## Boundary

This project is a metadata relay, not a content mirror.

It provides:

- notice title
- official source
- original notice URL
- published date
- short snippet
- attachment name/type/download URL metadata
- source refresh status

It does not provide:

- user watch requests
- user profiles
- personalized notifications
- LLM triage or summaries
- full notice body mirroring
- attachment content mirroring
- PNU account login
- private or personal data collection

Agents should fetch full notice text from `item.url` or `item._pnu.content_access.detail_url`, and should fetch attachments from `item._pnu.attachments[].download_url`.

## Generate Locally

Requirements:

- Python 3.12+
- Node.js 20+

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

GitHub Pages should use GitHub Actions as its source.

## License

MIT
