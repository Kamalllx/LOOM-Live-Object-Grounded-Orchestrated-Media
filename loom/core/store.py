"""SQLite store (spec/02 §6): one file, WAL mode, one writer, ordered migrations.

The connection is shared across threads behind a lock; async callers use `asyncio.to_thread` around short
transactions. Migrations live in `loom/core/migrations/NNNN_name.sql` and are applied once each, in order.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utcnow().isoformat()


class MigrationError(RuntimeError):
    pass


def discover_migrations(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for p in sorted(directory.glob("*.sql")):
        m = _MIGRATION_NAME.match(p.name)
        if not m:
            raise MigrationError(f"bad migration file name {p.name!r} (expected NNNN_name.sql)")
        found.append((int(m.group(1)), p))
    versions = [v for v, _ in found]
    if versions != list(range(1, len(versions) + 1)):
        raise MigrationError(f"migration numbers must be contiguous from 0001, got {versions}")
    return found


class Store:
    def __init__(self, path: Path | str, migrations_dir: Path = MIGRATIONS_DIR) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 30000")
        if str(path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        self.migrations_dir = migrations_dir

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def schema_version(self) -> int:
        v = self._conn.execute("PRAGMA user_version").fetchone()[0]
        return int(v)

    def migrate(self) -> list[int]:
        """Apply pending migrations; returns the versions applied. Idempotent."""
        applied: list[int] = []
        with self._lock:
            current = self.schema_version
            for version, path in discover_migrations(self.migrations_dir):
                if version <= current:
                    continue
                sql = path.read_text(encoding="utf-8")
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for statement in _split_sql(sql):
                        self._conn.execute(statement)
                    self._conn.execute(f"PRAGMA user_version = {version}")
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise
                applied.append(version)
        return applied

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """A write transaction (BEGIN IMMEDIATE ... COMMIT, rollback on error)."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def execute(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
        """Run one write statement in its own transaction; returns lastrowid."""
        with self.tx() as conn:
            cur = conn.execute(sql, params)
            return int(cur.lastrowid or 0)

    def query(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self._conn.execute(sql, params).fetchone()
            return row

    def tables(self) -> list[str]:
        rows = self.query("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        return sorted(r["name"] for r in rows)


def _split_sql(sql: str) -> list[str]:
    """Split a migration file into complete statements (SQLite's own tokenizer handles comments and literals)."""
    statements: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            statements.append(buf.strip())
            buf = ""
    if buf.strip() and not all(ln.strip().startswith("--") or not ln.strip() for ln in buf.splitlines()):
        raise MigrationError(f"incomplete SQL statement at end of migration: {buf.strip()[:80]!r}")
    return statements
