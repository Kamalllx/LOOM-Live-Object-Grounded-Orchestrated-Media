"""Content-addressed blob storage (spec/02 §6, FR-GEN-07, NFR-REL-03).

Blobs live at `<data>/blobs/sha256/ab/cdef...<ext>`; the name *is* the content hash, so a blob can never change
under its reference. Writes are atomic (temp file + rename) and idempotent.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loom.core.contracts.common import canonical_json

_SHA = re.compile(r"^sha256:([0-9a-f]{64})$")
_EXT = re.compile(r"^\.[a-z0-9]{1,8}$")
_CHUNK = 1 << 20


class BlobIntegrityError(RuntimeError):
    """A blob's bytes no longer match its content hash (F10: replaced on disk)."""


@dataclass(frozen=True)
class BlobRef:
    sha256: str  # "sha256:<hex>"
    path: Path
    size: int


def stage_key(*parts: Any) -> str:
    """Cache key for a stage output: sha256 over canonical JSON of (inputs, stage version, model ids, ...)."""
    return "sha256:" + hashlib.sha256(canonical_json(list(parts))).hexdigest()


def _hex(sha: str) -> str:
    m = _SHA.match(sha)
    if not m:
        raise ValueError(f"not a sha256 reference: {sha!r}")
    return m.group(1)


class BlobStore:
    def __init__(self, root: Path) -> None:
        self.root = root / "sha256"
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, sha: str, ext: str = "") -> Path:
        if ext and not _EXT.match(ext):
            raise ValueError(f"bad blob extension {ext!r}")
        h = _hex(sha)
        return self.root / h[:2] / f"{h[2:]}{ext}"

    def find(self, sha: str) -> Path | None:
        h = _hex(sha)
        d = self.root / h[:2]
        if not d.is_dir():
            return None
        for p in d.glob(f"{h[2:]}*"):
            if p.name == h[2:] or _EXT.match(p.name[len(h) - 2 :]):
                return p
        return None

    def exists(self, sha: str) -> bool:
        return self.find(sha) is not None

    def put_bytes(self, data: bytes, ext: str = "") -> BlobRef:
        sha = "sha256:" + hashlib.sha256(data).hexdigest()
        target = self.path_for(sha, ext)
        if not target.exists():
            self._atomic_write(target, lambda fh: fh.write(data))
        return BlobRef(sha, target, len(data))

    def put_file(self, src: Path, ext: str | None = None) -> BlobRef:
        h = hashlib.sha256()
        size = 0
        with src.open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                h.update(chunk)
                size += len(chunk)
        sha = "sha256:" + h.hexdigest()
        target = self.path_for(sha, src.suffix.lower() if ext is None else ext)
        if not target.exists():

            def copy(out: Any) -> None:
                with src.open("rb") as fh:
                    while chunk := fh.read(_CHUNK):
                        out.write(chunk)

            self._atomic_write(target, copy)
        return BlobRef(sha, target, size)

    def read_bytes(self, sha: str, verify: bool = True) -> bytes:
        p = self.find(sha)
        if p is None:
            raise FileNotFoundError(sha)
        data = p.read_bytes()
        if verify and "sha256:" + hashlib.sha256(data).hexdigest() != sha:
            raise BlobIntegrityError(f"{p} does not match {sha}")
        return data

    def verify(self, sha: str) -> bool:
        p = self.find(sha)
        if p is None:
            return False
        h = hashlib.sha256()
        with p.open("rb") as fh:
            while chunk := fh.read(_CHUNK):
                h.update(chunk)
        return "sha256:" + h.hexdigest() == sha

    def _atomic_write(self, target: Path, writer: Any) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                writer(fh)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
