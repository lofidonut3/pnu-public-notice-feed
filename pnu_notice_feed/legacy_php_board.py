from __future__ import annotations

import hashlib
import html
import re
import ssl
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from .types import Notice, Source

USER_AGENT = "PNUPublicNoticeFeed/0.1 (+https://github.com/pnu-public-notice-feed)"
LEGACY_TLS_HOST_ALLOWLIST = {"me.pusan.ac.kr"}


@dataclass(frozen=True)
class LegacyPhpListNotice:
    notice_id: str
    title: str
    url: str
    published_at: str | None


def fetch_legacy_php_board(source: Source, limit: int) -> list[Notice]:
    html_text = fetch_text(source.entry_url)
    items = parse_legacy_php_list(html_text, source.entry_url)[:limit]
    return [
        Notice(
            source_id=source.id,
            source_name=source.name,
            notice_id=f"{source.id}:{item.notice_id}",
            title=item.title,
            url=item.url,
            published_at=item.published_at,
            snippet=None,
            attachments=[],
            tags=source.tags,
            content_hash=_content_hash(item.title, item.published_at, item.url),
        )
        for item in items
    ]


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    context = legacy_ssl_context(url)
    with urlopen(request, timeout=20, context=context) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(encoding, errors="replace")


def legacy_ssl_context(url: str) -> ssl.SSLContext | None:
    host = urlparse(url).hostname or ""
    if host not in LEGACY_TLS_HOST_ALLOWLIST:
        return None
    return ssl._create_unverified_context()


def parse_legacy_php_list(html_text: str, base_url: str) -> list[LegacyPhpListNotice]:
    db = _hidden_value(html_text, "db")
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html_text, flags=re.I | re.S)
    notices: list[LegacyPhpListNotice] = []
    seen: set[str] = set()

    for row in rows:
        match = re.search(
            r"<a\b[^>]*href=[\"']javascript:goDetail\((\d+)\)[\"'][^>]*>(.*?)</a>",
            row,
            flags=re.I | re.S,
        )
        if not match:
            continue

        notice_id = match.group(1)
        if notice_id in seen:
            continue

        title = _title_from_link(match.group(2))
        if not title:
            continue

        seen.add(notice_id)
        notices.append(
            LegacyPhpListNotice(
                notice_id=notice_id,
                title=title,
                url=_detail_url(base_url, notice_id, db),
                published_at=_date_from_row(row),
            )
        )

    return notices


def _hidden_value(html_text: str, name: str) -> str | None:
    match = re.search(
        rf"<input\b[^>]*name=[\"']{re.escape(name)}[\"'][^>]*value=[\"']([^\"']*)[\"']",
        html_text,
        flags=re.I,
    )
    if not match:
        return None
    return html.unescape(match.group(1)).strip() or None


def _title_from_link(link_html: str) -> str:
    value = re.split(
        r"<span\b[^>]*class=[\"'][^\"']*mobile-info[^\"']*[\"'][^>]*>",
        link_html,
        maxsplit=1,
        flags=re.I | re.S,
    )[0]
    value = re.sub(
        r"<span\b[^>]*class=[\"'][^\"']*type[^\"']*[\"'][^>]*>.*?</span>",
        " ",
        value,
        flags=re.I | re.S,
    )
    return normalize_text(value)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _detail_url(base_url: str, notice_id: str, db: str | None) -> str:
    query = {
        "seq": notice_id,
        "page": "1",
        "perPage": "10",
        "page_mode": "view",
    }
    if db:
        query = {"db": db, **query}
    return urljoin(base_url, "?" + urlencode(query))


def _date_from_row(row: str) -> str | None:
    match = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", row)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"


def _content_hash(title: str, published_at: str | None, url: str) -> str:
    return hashlib.sha256(f"{title}\n{published_at or ''}\n{url}".encode("utf-8")).hexdigest()
