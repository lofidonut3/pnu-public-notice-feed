from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    adapter: str
    entry_url: str
    tags: list[str] = field(default_factory=list)
    menu_cd: str | None = None
    board_id: str | None = None
    cate_type_seq: str | None = None
    bbs_type_seq: str | None = None
    mainbbs_tab_index: str | None = None


@dataclass(frozen=True)
class Attachment:
    name: str
    url: str
    type: str | None = None


@dataclass(frozen=True)
class Notice:
    source_id: str
    source_name: str
    notice_id: str
    title: str
    url: str
    published_at: str | None
    snippet: str | None
    attachments: list[Attachment]
    tags: list[str]
    content_hash: str
    detail_checked_at: str | None = None
