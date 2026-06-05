from __future__ import annotations

import hashlib
import json
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .types import Attachment, Notice, Source

USER_AGENT = "PNUPublicNoticeFeed/0.1 (+https://github.com/pnu-public-notice-feed)"
LIBRARY_BASE_URL = "https://lib.pusan.ac.kr"
PYXIS_BASE_URL = f"{LIBRARY_BASE_URL}/pyxis-api/1"


def fetch_library_pyxis_board(source: Source, limit: int) -> list[Notice]:
    board_id = source.board_id or "2"
    url = f"{PYXIS_BASE_URL}/bulletin-boards/{board_id}/bulletins?offset=0&max={limit}&sort=dateCreated&order=desc"
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    rows = _rows_from_pyxis_payload(payload, limit)
    return [_to_notice(source, row) for row in rows]


def notices_from_pyxis_payload(payload: dict, entry_url: str, limit: int) -> list[Notice]:
    rows = _rows_from_pyxis_payload(payload, limit)
    source = Source(
        id="",
        name="",
        adapter="library-pyxis-board",
        entry_url=entry_url,
    )
    return [_to_notice(source, row) for row in rows]


def _rows_from_pyxis_payload(payload: dict, limit: int) -> list[dict]:
    rows = payload.get("data", {}).get("list", [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows[:limit] if isinstance(row, dict) and row.get("id")]


def _to_notice(source: Source, row: dict) -> Notice:
    notice_id = str(row["id"])
    title = str(row.get("title") or "").strip()
    published_at = _date(row.get("dateCreated"))
    attachments = [_attachment(item) for item in row.get("attachments", []) if item.get("logicalName")]
    return Notice(
        source_id=source.id,
        source_name=source.name,
        notice_id=f"{source.id}:{notice_id}" if source.id else notice_id,
        title=title,
        url=urljoin(source.entry_url.rstrip("/") + "/", notice_id),
        published_at=published_at,
        snippet=None,
        attachments=attachments,
        tags=source.tags,
        content_hash=_content_hash(title, published_at, attachments),
    )


def _attachment(item: dict) -> Attachment:
    name = str(item.get("logicalName") or "").strip()
    url = urljoin(LIBRARY_BASE_URL, str(item.get("originalImageUrl") or ""))
    return Attachment(
        name=name,
        url=url,
        type=_extension(name) or _type_from_media(str(item.get("fileType") or "")),
    )


def _date(value: object) -> str | None:
    if not value:
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else None


def _extension(name: str) -> str | None:
    if "." not in name:
        return None
    return name.rsplit(".", 1)[-1].lower()


def _type_from_media(media_type: str) -> str | None:
    if "hwp" in media_type:
        return "hwp"
    if "/" in media_type:
        return media_type.rsplit("/", 1)[-1].lower()
    return None


def _content_hash(title: str, published_at: str | None, attachments: list[Attachment]) -> str:
    payload = "\n".join([title, published_at or "", *[f"{item.name}\t{item.url}" for item in attachments]])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
