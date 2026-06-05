from __future__ import annotations

import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from .types import Attachment, Notice, Source


def fetch_websquare_js_board(source: Source, limit: int) -> list[Notice]:
    if not source.menu_cd:
        raise ValueError(f"missing menu_cd for source: {source.id}")

    parsed = urlparse(source.entry_url)
    site_path = parsed.path.strip("/").split("/", 1)[0]
    if not site_path:
        raise ValueError(f"cannot infer site path for source: {source.id}")

    script = Path(__file__).resolve().parents[1] / "scripts" / "fetch_websquare_board.mjs"
    result = subprocess.run(
        [
            "node",
            str(script),
            "--base-url",
            f"{parsed.scheme}://{parsed.netloc}",
            "--site-path",
            site_path,
            "--menu-cd",
            source.menu_cd,
            "--limit",
            str(limit),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or "websquare helper failed"
        raise RuntimeError(error)

    payload = json.loads(result.stdout)
    notices: list[Notice] = []
    for item in payload.get("notices", []):
        notice_id = str(item["notice_id"])
        notices.append(
            Notice(
                source_id=source.id,
                source_name=source.name,
                notice_id=f"{source.id}:{notice_id}",
                title=str(item["title"]),
                url=str(item["url"]),
                published_at=item.get("published_at"),
                snippet=item.get("snippet"),
                attachments=[
                    Attachment(
                        name=str(attachment["name"]),
                        url=str(attachment["url"]),
                        type=attachment.get("type"),
                    )
                    for attachment in item.get("attachments", [])
                ],
                tags=source.tags,
                content_hash=str(item["content_hash"]),
            )
        )
    return notices
