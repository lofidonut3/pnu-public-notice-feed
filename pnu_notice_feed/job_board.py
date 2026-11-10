from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .types import Notice, Source
from .html_dates import publication_date

USER_AGENT = "PNUPublicNoticeFeed/0.1 (+https://github.com/pnu-public-notice-feed)"
CAREER_HOME = "https://job.pusan.ac.kr/"
HOME_RECRUIT_BOARDS = {
    "pnu-job-recruit-recommendation": ("Recommendation_intro", "recommend"),
    "pnu-job-recruit-internship": ("Intern", "intern"),
}


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


def fetch_job_recruit_board(
    source: Source, limit: int, *, cached_items: dict[str, dict] | None = None
) -> list[Notice]:
    html_text = fetch_text(source.entry_url)
    if source.id in HOME_RECRUIT_BOARDS and source.entry_url.rstrip("/") == CAREER_HOME.rstrip("/"):
        board, calendar = HOME_RECRUIT_BOARDS[source.id]
        items = parse_job_home_recruit_list(html_text, source.entry_url, board)[:limit]
        notices = _to_notices(source, items)
        return resolve_job_home_details(notices, calendar, cached_items or {})
    return _to_notices(source, parse_job_recruit_list(html_text, source.entry_url)[:limit])


def resolve_job_home_details(
    notices: list[Notice], calendar: str, cached_items: dict[str, dict]
) -> list[Notice]:
    if not notices:
        return notices
    calendar_path = f"/ko/community/calendar/{calendar}"
    calendar_url = urljoin(CAREER_HOME, calendar_path)
    wanted = {(notice.notice_id.rsplit(":", 1)[1], notice.title) for notice in notices}
    calendar_links = JobCalendarLinks(calendar_path, wanted)
    # One calendar page and at most its official next-month link per poll.
    for _ in range(2):
        try:
            page = fetch_text(calendar_url, timeout=10)
        except OSError:
            break
        calendar_links.next_url = None
        calendar_links.feed(page)
        if wanted <= calendar_links.details.keys() or not calendar_links.next_url:
            break
        calendar_url = calendar_links.next_url

    resolved = []
    for notice in notices:
        upstream_id = notice.notice_id.rsplit(":", 1)[1]
        detail_url = calendar_links.details.get((upstream_id, notice.title))
        if not detail_url:
            cached = cached_items.get(notice.notice_id, {})
            access = cached.get("_pnu", {}).get("content_access", {})
            cached_url = cached.get("url", "")
            if (
                cached.get("title") == notice.title
                and access.get("original_detail_url") == notice.url
                and calendar_links.is_detail_url(cached_url, upstream_id)
            ):
                detail_url = cached_url
        if detail_url:
            # The content hash is based on the homepage record. This replaces
            # its locator without classifying the notice itself as updated.
            resolved.append(replace(notice, url=detail_url, detail_access={"original_detail_url": notice.url}))
        else:
            resolved.append(replace(notice, detail_access={
                "detail_url": None,
                "availability": "detail_unverified",
                "fallback_url": CAREER_HOME,
            }))
    return resolved


class JobCalendarLinks(HTMLParser):
    def __init__(self, calendar_path: str, wanted: set[tuple[str, str]]) -> None:
        super().__init__()
        self.calendar_path = calendar_path
        self.wanted = wanted
        self.details: dict[tuple[str, str], str] = {}
        self.next_url: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_by_name = dict(attrs)
        if tag == "button" and attrs_by_name.get("data-action") == "apply":
            upstream_id = attrs_by_name.get("data-ridx") or ""
            key = upstream_id, normalize_text(attrs_by_name.get("data-title") or "")
            path = attrs_by_name.get("data-url")
            if key in self.wanted and path == f"{self.calendar_path}/view/{upstream_id}":
                self.details[key] = urljoin(CAREER_HOME, path)
        elif tag == "a" and "next" in (attrs_by_name.get("class") or "").split():
            path = attrs_by_name.get("href") or ""
            if re.fullmatch(rf"{re.escape(self.calendar_path)}/list/\d{{4}}/\d{{2}}", path):
                self.next_url = urljoin(CAREER_HOME, path)

    def is_detail_url(self, url: str, upstream_id: str) -> bool:
        return url == urljoin(CAREER_HOME, f"{self.calendar_path}/view/{upstream_id}")


def parse_job_home_recruit_list(html_text: str, base_url: str, board: str) -> list[JobListNotice]:
    """Public homepage cards remain available when the old list routes return 404."""
    notices = []
    seen = set()
    pattern = rf'<a\b[^>]*href=["\']([^"\']*/ko/recruit/{re.escape(board)}/view/(\d+)[^"\']*)["\'][^>]*>(.*?)</a>'
    for link in re.finditer(pattern, html_text, re.I | re.S):
        notice_id = link.group(2)
        if notice_id in seen:
            continue
        body = link.group(3)
        title = _class_text(body, "sub") or normalize_text(body)
        if not title:
            continue
        seen.add(notice_id)
        notices.append(JobListNotice(notice_id, title, urljoin(base_url, html.unescape(link.group(1))), None))
    return notices


def fetch_text(url: str, *, timeout: int = 20) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
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
    return publication_date(value)


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
