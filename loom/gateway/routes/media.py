"""`/media/...` — static media with HTTP range requests (video seeking), confined to `<data>/media`."""

from __future__ import annotations

import mimetypes
import re
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response, StreamingResponse

from loom.gateway.state import GatewayState, get_state

mimetypes.add_type("image/webp", ".webp")  # Windows' registry often lacks it (board snapshots are WebP)

router = APIRouter()

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")
_CHUNK = 1 << 16


def _resolve(root: Path, rel: str) -> Path:
    root = root.resolve()
    target = (root / rel).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(404, "not found")
    return target


def _iter_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    with path.open("rb") as fh:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            chunk = fh.read(min(_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.api_route("/media/{rel:path}", methods=["GET", "HEAD"])
async def media(
    rel: str,
    state: GatewayState = Depends(get_state),
    range_header: str | None = Header(None, alias="Range"),
) -> Response:
    path = _resolve(state.media_dir, rel)
    size = path.stat().st_size
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    base = {"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"}

    if range_header is None:
        return StreamingResponse(
            _iter_file(path, 0, size), media_type=ctype, headers={**base, "Content-Length": str(size)}
        )
    m = _RANGE.match(range_header.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        raise HTTPException(416, "unsupported range", headers={"Content-Range": f"bytes */{size}"})
    if m.group(1) == "":  # suffix range: last N bytes
        n = int(m.group(2))
        start, end = max(0, size - n), size - 1
    else:
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
    end = min(end, size - 1)
    if start >= size or start > end:
        raise HTTPException(416, "range not satisfiable", headers={"Content-Range": f"bytes */{size}"})
    length = end - start + 1
    return StreamingResponse(
        _iter_file(path, start, length),
        status_code=206,
        media_type=ctype,
        headers={**base, "Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(length)},
    )
