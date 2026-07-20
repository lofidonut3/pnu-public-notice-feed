from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .types import Notice, Source

USER_AGENT = "PNUPublicNoticeFeed/0.1 (+https://github.com/pnu-public-notice-feed)"
DEFAULT_MAX_CATCHUP_PAGES = 50


@dataclass(frozen=True)
class K2WebListNotice:
    notice_id: str
    title: str
    url: str
    published_at: str | None
    is_pinned: bool = False


def fetch_k2web_board(
    source: Source,
    limit: int,
    known_notice_ids: set[str] | None = None,
    known_notice_dates: dict[str, str | None] | None = None,
    max_catchup_pages: int = DEFAULT_MAX_CATCHUP_PAGES,
) -> list[Notice]:
    html_text = fetch_text(source.entry_url)
    items = parse_k2web_list(html_text, source.entry_url)
    known_ids = {
        notice_id.rsplit(":", 1)[-1]
        for notice_id in (known_notice_ids or set())
    }
    known_dates = {
        notice_id.rsplit(":", 1)[-1]: published_at
        for notice_id, published_at in (known_notice_dates or {}).items()
    }
    if known_ids and not _contains_known_boundary(items, known_ids):
        pinned_ids = {item.notice_id for item in items if item.is_pinned}
        known_dates_available = [
            published_at
            for notice_id, published_at in known_dates.items()
            if notice_id in known_ids and published_at
        ]
        # Some boards fill early pages with site-wide pinned notices. In that
        # case, use the newest cached date to find recent local rows without
        # publishing the board's entire history as newly observed notices.
        if known_ids.issubset(pinned_ids) and known_dates_available:
            items = _fetch_recent_after_pinned_baseline(
                html_text,
                source.entry_url,
                first_page_items=items,
                cutoff_date=max(known_dates_available),
                max_pages=max_catchup_pages,
            )
        else:
            items = _fetch_until_known_boundary(
                html_text,
                source.entry_url,
                first_page_items=items,
                known_ids=known_ids,
                max_pages=max_catchup_pages,
            )
    items = _deduplicate_items(items)
    if not known_ids:
        items = items[:limit]
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


def fetch_text(url: str, form: dict[str, str] | None = None) -> str:
    data = urlencode(form).encode("utf-8") if form else None
    request = Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(encoding, errors="replace")


def _fetch_until_known_boundary(
    first_page_html: str,
    base_url: str,
    *,
    first_page_items: list[K2WebListNotice],
    known_ids: set[str],
    max_pages: int,
) -> list[K2WebListNotice]:
    action_url, layout = parse_k2web_pagination(first_page_html, base_url)
    if not action_url:
        raise RuntimeError("K2Web catch-up boundary is missing and pagination is unavailable")

    collected = list(first_page_items)
    for page in range(2, max(2, max_pages + 1)):
        form = {"page": str(page)}
        if layout:
            form["layout"] = layout
        page_html = fetch_text(action_url, form=form)
        page_items = parse_k2web_list(page_html, action_url)
        if not page_items:
            raise RuntimeError(f"K2Web catch-up page {page} returned no notice rows")
        collected.extend(page_items)
        if _contains_known_boundary(page_items, known_ids):
            return collected

    raise RuntimeError(
        f"K2Web catch-up boundary was not found within {max_pages} pages"
    )


def _fetch_recent_after_pinned_baseline(
    first_page_html: str,
    base_url: str,
    *,
    first_page_items: list[K2WebListNotice],
    cutoff_date: str,
    max_pages: int,
) -> list[K2WebListNotice]:
    action_url, layout = parse_k2web_pagination(first_page_html, base_url)
    total_pages = parse_k2web_total_pages(first_page_html)
    if not action_url or total_pages == 1:
        return list(first_page_items)

    collected = list(first_page_items)
    final_page = min(total_pages or max_pages, max_pages)
    for page in range(2, max(2, final_page + 1)):
        form = {"page": str(page)}
        if layout:
            form["layout"] = layout
        page_html = fetch_text(action_url, form=form)
        page_items = parse_k2web_list(page_html, action_url)
        if not page_items:
            raise RuntimeError(f"K2Web catch-up page {page} returned no notice rows")

        non_pinned = [item for item in page_items if not item.is_pinned]
        collected.extend(
            item
            for item in non_pinned
            if item.published_at is None or item.published_at >= cutoff_date
        )
        if any(
            item.published_at is not None and item.published_at < cutoff_date
            for item in non_pinned
        ):
            return collected

    if total_pages is not None and total_pages <= max_pages:
        return collected
    raise RuntimeError(
        f"K2Web pinned-baseline catch-up did not reach a date boundary within {max_pages} pages"
    )


def parse_k2web_pagination(html_text: str, base_url: str) -> tuple[str | None, str | None]:
    form = re.search(
        r"<form\b[^>]*\baction=[\"']([^\"']*artclList\.do[^\"']*)[\"'][^>]*>",
        html_text,
        flags=re.I | re.S,
    )
    if not form:
        return None, None
    layout = re.search(
        r"<input\b[^>]*\bname=[\"']layout[\"'][^>]*\bvalue=[\"']([^\"']*)[\"'][^>]*>",
        html_text,
        flags=re.I | re.S,
    )
    return urljoin(base_url, html.unescape(form.group(1))), (
        html.unescape(layout.group(1)) if layout else None
    )


def parse_k2web_total_pages(html_text: str) -> int | None:
    match = re.search(
        r'class=["\'][^"\']*\b_totPage\b[^"\']*["\'][^>]*>\s*(\d+)',
        html_text,
        flags=re.I,
    )
    return int(match.group(1)) if match else None


def _contains_known_boundary(
    items: list[K2WebListNotice],
    known_ids: set[str],
) -> bool:
    return any(item.notice_id in known_ids and not item.is_pinned for item in items)


def _deduplicate_items(items: list[K2WebListNotice]) -> list[K2WebListNotice]:
    seen: set[str] = set()
    result: list[K2WebListNotice] = []
    for item in items:
        if item.notice_id in seen:
            continue
        seen.add(item.notice_id)
        result.append(item)
    return result


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
                is_pinned=_is_pinned_row(row),
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


def _is_pinned_row(row: str) -> bool:
    if re.search(r"notice-title|artclNotice|icon-notice", row, re.I):
        return True
    first_cell = re.search(r"<td\b[^>]*>(.*?)</td>", row, flags=re.I | re.S)
    if not first_cell:
        return False
    cell_text = html.unescape(re.sub(r"<[^>]+>", " ", first_cell.group(1)))
    return bool(re.search(r"(?:^|\s)(?:공지|notice)(?:\s|$)", cell_text, re.I))


def _content_hash(title: str, published_at: str | None, url: str) -> str:
    return hashlib.sha256(f"{title}\n{published_at or ''}\n{url}".encode("utf-8")).hexdigest()
