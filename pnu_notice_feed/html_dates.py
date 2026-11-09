"""Read publication cells without confusing dates in titles with publication dates."""
from datetime import date
import html
import re


def publication_date(row: str) -> str | None:
    cells = re.findall(r"<(?:td|time)\b([^>]*)>(.*?)</(?:td|time)>", row, re.I | re.S)
    preferred = [body for attrs, body in cells if re.search(r"(?:td-date|Rdate|regDate|writeDate|datetime)", attrs, re.I)]
    # Older themes have no classes. Only accept a date-only cell in that case.
    fallback = [body for _attrs, body in cells if not re.search(r"<a\b", body, re.I)]
    for body in preferred + fallback:
        text = html.unescape(re.sub(r"<[^>]+>", " ", body)).strip()
        match = re.fullmatch(r"\s*(20\d{2})[./-](\d{1,2})[./-](\d{1,2})\.?\s*(?:\d{1,2}:\d{2}(?::\d{2})?)?\s*", text)
        if match:
            try:
                return date(*(int(part) for part in match.groups())).isoformat()
            except ValueError:
                continue
    return None


def detail_publication_date(page: str) -> str | None:
    # Both official K2Web templates were observed on 2026-11-09: span/li and dt/dd.
    patterns = [
        r'<span[^>]*>\s*작성일\s*</span>\s*(20\d{2}[./-]\d{1,2}[./-]\d{1,2})',
        r'<dt[^>]*>\s*작성일\s*</dt>\s*<dd[^>]*>\s*(20\d{2}[./-]\d{1,2}[./-]\d{1,2})',
    ]
    for pattern in patterns:
        match = re.search(pattern, page, re.I | re.S)
        if match:
            return publication_date(f'<td>{match.group(1)}</td>')
    return None
