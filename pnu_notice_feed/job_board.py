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
class JobListNotice:
    notice_id: str
    title: str
    url: str
    published_at: str | None
    snippet: str | None = None


def fetch_job_notice_board(source: Source, limit: int) -> list[Notice]:
    html_text = fetch_text(source.entry_url)
    return _to_notices(source, parse_job_notice_list(html_text, source.entry_url)[:limit])


def fetch_job_recruit_board(source: Source, limit: int) -> list[Notice]:
    html_text = fetch_text(source.entry_url)
    return _to_notices(source, parse_job_recruit_list(html_text, source.entry_url)[:limit])


def fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        encoding = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(encoding, errors="replace")


def parse_job_notice_list(html_text: str, base_url: str) -> list[JobListNotice]:
    rows = _rows(html_text)
    notices: list[JobListNotice] = []
    for row in rows:
        notice = _notice_from_job_notice_row(row, base_url)
        if notice:
            notices.append(notice)
    return notices


def parse_job_recruit_list(html_text: str, base_url: str) -> list[JobListNotice]:
    rows = _rows(html_text)
    notices: list[JobListNotice] = []
    for row in rows:
        notice = _notice_from_job_recruit_row(row, base_url)
        if notice:
            notices.append(notice)
    return notices


def _rows(html_text: str) -> list[str]:
    return re.findall(r"<li\b[^>]*class=[\"'][^\"']*\btbody\b[^\"']*[\"'][^>]*>(.*?)</li>", html_text, flags=re.I | re.S)


def _notice_from_job_notice_row(row: str, base_url: str) -> JobListNotice | None:
    link = re.search(r"<a\b[^>]*href=[\"']([^\"']*/view/(\d+)[^\"']*)[\"'][^>]*>(.*?)</a>", row, flags=re.I | re.S)
    if not link:
        return None
    title = normalize_text(link.group(3))
    if not title:
        return None
    date_match = re.search(r"<time\b[^>]*datetime=[\"'](20\d{2}-\d{2}-\d{2})", row, flags=re.I)
    return JobListNotice(
        notice_id=link.group(2),
        title=title,
        url=urljoin(base_url, html.unescape(link.group(1))),
        published_at=date_match.group(1) if date_match else _date_from_text(row),
    )


def _notice_from_job_recruit_row(row: str, base_url: str) -> JobListNotice | None:
    link = re.search(r"<a\b[^>]*href=[\"']([^\"']*/view/(\d+)[^\"']*)[\"'][^>]*>(.*?)</a>", row, flags=re.I | re.S)
    if not link:
        return None
    title = normalize_text(link.group(3))
    if not title:
        return None
    company = _class_text(row, "co")
    recruit_type = _class_text(row, "recruit_type")
    deadline = _class_text(row, "end_date")
    snippet_parts = []
    if company:
        snippet_parts.append(f"회사: {company}")
    if recruit_type:
        snippet_parts.append(f"유형: {recruit_type}")
    if deadline:
        snippet_parts.append(f"마감: {deadline}")
    return JobListNotice(
        notice_id=link.group(2),
        title=title,
        url=urljoin(base_url, html.unescape(link.group(1))),
        published_at=None,
        snippet=" / ".join(snippet_parts) if snippet_parts else None,
    )


def normalize_text(value: str) -> str:
    without_icons = re.sub(r"<i\b[^>]*>.*?</i>", " ", value, flags=re.I | re.S)
    without_breaks = re.sub(r"<br\s*/?>", " ", without_icons, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", without_breaks))).strip()


def _class_text(row: str, class_name: str) -> str | None:
    match = re.search(
        rf"<[^>]+class=[\"'][^\"']*\b{re.escape(class_name)}\b[^\"']*[\"'][^>]*>(.*?)</[^>]+>",
        row,
        flags=re.I | re.S,
    )
    if not match:
        return None
    text = normalize_text(match.group(1))
    return text or None


def _date_from_text(value: str) -> str | None:
    match = re.search(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})", value)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"


def _to_notices(source: Source, items: list[JobListNotice]) -> list[Notice]:
    return [
        Notice(
            source_id=source.id,
            source_name=source.name,
            notice_id=f"{source.id}:{item.notice_id}",
            title=item.title,
            url=item.url,
            published_at=item.published_at,
            snippet=item.snippet,
            attachments=[],
            tags=source.tags,
            content_hash=_content_hash(item),
        )
        for item in items
    ]


def _content_hash(item: JobListNotice) -> str:
    payload = f"{item.title}\n{item.published_at or ''}\n{item.snippet or ''}\n{item.url}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
