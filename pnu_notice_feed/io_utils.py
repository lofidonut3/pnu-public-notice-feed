"""Atomic UTF-8/LF writes keep published bytes equal to manifest checksums."""
import os
from pathlib import Path
import tempfile


def write_utf8_if_changed(path: Path, content: str) -> None:
    data=content.replace('\r\n','\n').encode('utf-8')
    if path.exists() and path.read_bytes()==data:
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.'+path.name+'.',suffix='.tmp',delete=False) as output:
            temp=Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temp.replace(path)
    finally:
        if temp and temp.exists():temp.unlink()
