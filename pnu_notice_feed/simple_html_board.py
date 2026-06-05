from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from .types import Notice, Source

USER_AGENT = "PNUPublicNoticeFeed/0.1 (+https://github.com/pnu-public-notice-feed)"


@dataclass(frozen=True)
class HtmlListNotice:
    notice_id: str
    title: str
    url: str
    published_at: str | None


def fetch_simple_html_board(source: Source, limit: int) -> list[Notice]:
    html_text = fetch_text(source.entry_url)
    return _to_notices(source, parse_simple_html_list(html_text, source.entry_url)[:limit])


def fetch_plato_ubboard(source: Source, limit: int) -> list[Notice]:
    html_text = fetch_text(source.entry_url)
    return _to_notices(source, parse_plato_ubboard_list(html_text, source.entry_url)[:limit])


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(encoding, errors="replace")


def parse_simple_html_list(html_text: str, base_url: str) -> list[HtmlListNotice]:
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html_text, flags=re.I | re.S)
    notices: list[HtmlListNotice] = []
    seen: set[str] = set()
    for row in rows:
        link = re.search(
            r"<a\b[^>]*href=[\"']([^\"']*/boardview/(\d+)/(\d+)[^\"']*)[\"'][^>]*>(.*?)</a>",
            row,
            flags=re.I | re.S,
        )
        if not link:
            continue
        notice_id = f"{link.group(2)}-{link.group(3)}"
        title = normalize_text(link.group(4))
        if not title or notice_id in seen:
            continue
        seen.add(notice_id)
        notices.append(
            HtmlListNotice(
                notice_id=notice_id,
                title=title,
                url=urljoin(base_url, html.unescape(link.group(1))),
                published_at=_date_from_text(row),
            )
        )
    return notices


def parse_plato_ubboard_list(html_text: str, base_url: str) -> list[HtmlListNotice]:
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html_text, flags=re.I | re.S)
    notices: list[HtmlListNotice] = []
    seen: set[str] = set()
    for row in rows:
        link = re.search(
            r"<a\b[^>]*href=[\"']([^\"']*/mod/ubboard/article\.php\?[^\"']*bwid=(\d+)[^\"']*)[\"'][^>]*>(.*?)</a>",
            row,
            flags=re.I | re.S,
        )
        if not link:
            continue
        notice_id = link.group(2)
        title = normalize_text(link.group(3))
        if not title or notice_id in seen:
            continue
        seen.add(notice_id)
        notices.append(
            HtmlListNotice(
                notice_id=notice_id,
                title=title,
                url=urljoin(base_url, html.unescape(link.group(1))),
                published_at=_date_from_text(row),
            )
        )
    return notices


def normalize_text(value: str) -> str:
    without_icons = re.sub(r"<img\b[^>]*>", " ", value, flags=re.I | re.S)
    without_tags = re.sub(r"<[^>]+>", " ", without_icons)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _date_from_text(value: str) -> str | None:
    match = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", value)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"


def _to_notices(source: Source, items: list[HtmlListNotice]) -> list[Notice]:
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
            content_hash=_content_hash(item),
        )
        for item in items
    ]


def _content_hash(item: HtmlListNotice) -> str:
    parsed = urlparse(item.url)
    query = parse_qs(parsed.query)
    stable_url = parsed._replace(query="").geturl()
    stable_parts = [item.title, item.published_at or "", stable_url]
    for key in ("bwid", "id"):
        if query.get(key):
            stable_parts.append(f"{key}={query[key][0]}")
    return hashlib.sha256("\n".join(stable_parts).encode("utf-8")).hexdigest()
