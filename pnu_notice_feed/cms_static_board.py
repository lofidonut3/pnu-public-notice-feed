from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .types import Attachment, Notice, Source

USER_AGENT = "PNUPublicNoticeFeed/0.1 (+https://github.com/pnu-public-notice-feed)"
DETAIL_REVALIDATE_TOP_N = 10
DETAIL_REVALIDATE_TTL_HOURS = 12


@dataclass(frozen=True)
class ListItem:
    notice_id: str
    title: str
    url: str
    published_at: str | None


def fetch_cms_static_board(
    source: Source,
    limit: int,
    seen_notice_ids: set[str] | None = None,
    cached_items: dict[str, dict] | None = None,
    checked_at: str | None = None,
) -> list[Notice]:
    html_text = fetch_text(source.entry_url)
    list_items = parse_cms_list(html_text, source.entry_url)[:limit]
    notices: list[Notice] = []
    seen_notice_ids = seen_notice_ids or set()
    cached_items = cached_items or {}
    checked_at = checked_at or datetime.now(ZoneInfo("Asia/Seoul")).isoformat(
        timespec="seconds"
    )

    for index, item in enumerate(list_items):
        notice_id = f"{source.id}:{item.notice_id}"
        cached_item = cached_items.get(notice_id)
        if not should_fetch_cms_detail(
            item,
            notice_id,
            cached_item=cached_item,
            checked_at=checked_at,
            item_index=index,
        ):
            continue
        if not cached_items and notice_id in seen_notice_ids:
            continue

        detail_html = fetch_text(item.url)
        detail = parse_cms_detail(detail_html, item.url)
        title = detail.title or item.title
        snippet = detail.snippet
        attachments = detail.attachments
        content_hash = _content_hash(title, item.published_at, snippet, attachments)
        notices.append(
            Notice(
                source_id=source.id,
                source_name=source.name,
                notice_id=notice_id,
                title=title,
                url=item.url,
                published_at=item.published_at,
                snippet=snippet,
                attachments=attachments,
                tags=source.tags,
                content_hash=content_hash,
                detail_checked_at=checked_at,
            )
        )

    return notices


def should_fetch_cms_detail(
    item: ListItem,
    notice_id: str,
    cached_item: dict | None,
    checked_at: str,
    item_index: int,
    revalidate_top_n: int = DETAIL_REVALIDATE_TOP_N,
    revalidate_ttl_hours: int = DETAIL_REVALIDATE_TTL_HOURS,
) -> bool:
    if cached_item is None:
        return True

    pnu = cached_item.get("_pnu", {})
    if cached_item.get("title") != item.title:
        return True
    if pnu.get("published_at") != item.published_at:
        return True

    if item_index >= revalidate_top_n:
        return False

    detail_checked_at = pnu.get("detail_checked_at")
    if not detail_checked_at:
        return True

    try:
        return parse_iso(checked_at) - parse_iso(detail_checked_at) >= timedelta(
            hours=revalidate_ttl_hours
        )
    except ValueError:
        return True


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(encoding, errors="replace")


def parse_cms_list(html_text: str, base_url: str) -> list[ListItem]:
    parser = CmsListParser(base_url)
    parser.feed(html_text)
    return parser.items


def parse_cms_detail(html_text: str, base_url: str) -> "CmsDetail":
    parser = CmsDetailParser(base_url)
    parser.feed(html_text)
    return parser.detail()


class CmsListParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.items: list[ListItem] = []
        self._in_row = False
        self._cell: str | None = None
        self._row: dict[str, str] = {}
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        class_name = attr.get("class", "")
        if tag == "tr":
            self._in_row = True
            self._row = {}
            return

        if not self._in_row:
            return

        if tag == "td":
            self._cell = _first_known_class(class_name, {"subject", "date"})
            self._text_parts = []
            return

        if tag == "a" and self._cell == "subject":
            href = attr.get("href")
            if href:
                url = urljoin(self.base_url, html.unescape(href))
                self._row = {**self._row, "url": url}
                notice_id = _notice_id_from_url(url)
                if notice_id:
                    self._row = {**self._row, "notice_id": notice_id}

        if tag == "img" and self._cell == "subject":
            title = _title_from_attachment_alt(attr.get("alt") or "")
            if title:
                self._row = {**self._row, "full_title": title}

    def handle_data(self, data: str) -> None:
        if self._in_row and self._cell:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._in_row:
            return

        if tag == "td" and self._cell:
            text = normalize_text("".join(self._text_parts))
            if self._cell == "subject" and text:
                self._row = {**self._row, "title": text}
            if self._cell == "date" and text:
                self._row = {**self._row, "published_at": text}
            self._cell = None
            self._text_parts = []
            return

        if tag == "tr":
            notice_id = self._row.get("notice_id")
            title = self._row.get("full_title") or self._row.get("title")
            url = self._row.get("url")
            if notice_id and title and url:
                self.items.append(
                    ListItem(
                        notice_id=notice_id,
                        title=title,
                        url=url,
                        published_at=self._row.get("published_at"),
                    )
                )
            self._in_row = False
            self._cell = None
            self._row = {}
            self._text_parts = []


@dataclass(frozen=True)
class CmsDetail:
    title: str | None
    snippet: str | None
    attachments: list[Attachment]


class CmsDetailParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._class_stack: list[str] = []
        self._capture_title = False
        self._capture_content = False
        self._capture_attachment = False
        self._current_attachment_url: str | None = None
        self._title_parts: list[str] = []
        self._content_parts: list[str] = []
        self._attachment_parts: list[str] = []
        self.attachments: list[Attachment] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        class_name = attr.get("class", "")
        element_id = attr.get("id", "")
        self._class_stack.append(class_name)

        if tag == "h4" and "vtitle" in class_name:
            self._capture_title = True

        if tag == "div" and element_id == "boardContents":
            self._capture_content = True

        if tag == "a" and self._inside_class("board-view-filelist"):
            href = attr.get("href")
            if href:
                self._capture_attachment = True
                self._current_attachment_url = urljoin(self.base_url, html.unescape(href))
                self._attachment_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_parts.append(data)
        if self._capture_content:
            self._content_parts.append(data)
        if self._capture_attachment:
            self._attachment_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_attachment:
            name = normalize_text("".join(self._attachment_parts))
            if self._current_attachment_url and name:
                self.attachments.append(
                    Attachment(
                        name=name,
                        url=self._current_attachment_url,
                        type=_extension_from_name(name),
                    )
                )
            self._capture_attachment = False
            self._current_attachment_url = None
            self._attachment_parts = []

        if tag == "div" and self._capture_content:
            self._capture_content = False

        if tag == "h4" and self._capture_title:
            self._capture_title = False

        if self._class_stack:
            self._class_stack.pop()

    def detail(self) -> CmsDetail:
        title = normalize_text("".join(self._title_parts)) or None
        content = normalize_text("".join(self._content_parts))
        snippet = content[:500] if content else None
        return CmsDetail(title=title, snippet=snippet, attachments=self.attachments)

    def _inside_class(self, target: str) -> bool:
        return any(target in class_name for class_name in self._class_stack)


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _first_known_class(class_name: str, known: set[str]) -> str | None:
    for part in class_name.split():
        if part in known:
            return part
    return None


def _notice_id_from_url(url: str) -> str | None:
    query = parse_qs(urlparse(url).query)
    values = query.get("board_seq")
    return values[0] if values else None


def _title_from_attachment_alt(alt: str) -> str | None:
    match = re.match(r"^'(.+)'의 첨부파일$", html.unescape(alt).strip())
    return match.group(1) if match else None


def _extension_from_name(name: str) -> str | None:
    match = re.search(r"\.([A-Za-z0-9]+)(?:\s|\(|$)", name)
    return match.group(1).lower() if match else None


def _content_hash(
    title: str,
    published_at: str | None,
    snippet: str | None,
    attachments: list[Attachment],
) -> str:
    payload = "\n".join(
        [
            title,
            published_at or "",
            snippet or "",
            *[f"{attachment.name}\t{attachment.url}" for attachment in attachments],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
