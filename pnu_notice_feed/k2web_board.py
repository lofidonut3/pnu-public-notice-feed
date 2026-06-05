from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .types import Notice, Source

USER_AGENT = "PNUPublicNoticeFeed/0.1 (+https://github.com/pnu-public-notice-feed)"


@dataclass(frozen=True)
class K2WebListNotice:
    notice_id: str
    title: str
    url: str
    published_at: str | None


def fetch_k2web_board(source: Source, limit: int) -> list[Notice]:
    html_text = fetch_text(source.entry_url)
    items = parse_k2web_list(html_text, source.entry_url)[:limit]
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
    with urlopen(request, timeout=20) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(encoding, errors="replace")


def parse_k2web_list(html_text: str, base_url: str) -> list[K2WebListNotice]:
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html_text, flags=re.I | re.S)
    seen: set[str] = set()
    notices: list[K2WebListNotice] = []
    for row in rows:
        link = re.search(
            r"<a\b[^>]*href=[\"']([^\"']*/bbs/[^\"']*/(\d+)/artclView\.do[^\"']*)[\"'][^>]*>(.*?)</a>",
            row,
            flags=re.I | re.S,
        )
        if not link:
            continue
        notice_id = link.group(2)
        if notice_id in seen:
            continue
        title = normalize_text(link.group(3))
        if not title:
            continue
        seen.add(notice_id)
        notices.append(
            K2WebListNotice(
                notice_id=notice_id,
                title=title,
                url=urljoin(base_url, html.unescape(link.group(1))),
                published_at=_date_from_row(row),
            )
        )
    return notices


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _date_from_row(row: str) -> str | None:
    match = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", row)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"


def _content_hash(title: str, published_at: str | None, url: str) -> str:
    return hashlib.sha256(f"{title}\n{published_at or ''}\n{url}".encode("utf-8")).hexdigest()

