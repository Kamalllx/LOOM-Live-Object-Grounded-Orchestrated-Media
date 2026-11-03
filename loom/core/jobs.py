"""Persisted job queue (spec/02 §6 `jobs`, FR-ING-02, NFR-REL-04).

Jobs survive a gateway restart: on startup `recover()` re-queues anything left `running`, and stage outputs are
content-addressed blobs, so a resumed job skips stages whose output already exists. Submitting a job with the same
`dedupe_key` as a live or completed job returns that job instead of creating a new one.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime
from typing import Any

from loom.core.contracts.ops import Job, JobKind, JobStatus
from loom.core.store import Store, iso_now


class JobNotFound(KeyError):
    pass


class JobStateError(RuntimeError):
    pass


def _new_id() -> str:
    return "job_" + secrets.token_hex(6)


def _row_to_job(r: sqlite3.Row) -> Job:
    return Job(
        id=r["id"],
        kind=r["kind"],
        status=r["status"],
        stage=r["stage"],
        progress=r["progress"],
        error=r["error"],
        payload=json.loads(r["payload"]),
        attempts=r["attempts"],
        dedupe_key=r["dedupe_key"],
        created_at=datetime.fromisoformat(r["created_at"]),
        updated_at=datetime.fromisoformat(r["updated_at"]),
    )


class JobQueue:
    def __init__(self, store: Store) -> None:
        self.store = store

    def submit(self, kind: JobKind, payload: dict[str, Any], dedupe_key: str | None = None) -> tuple[Job, bool]:
        """Queue a job. Returns (job, created); created is False when an existing job was returned."""
        with self.store.tx() as conn:
            if dedupe_key is not None:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE dedupe_key = ? AND status IN ('queued', 'running', 'completed')",
                    (dedupe_key,),
                ).fetchone()
                if row is not None:
                    return _row_to_job(row), False
            now = iso_now()
            job_id = _new_id()
            conn.execute(
                "INSERT INTO jobs (id, kind, status, payload, dedupe_key, created_at, updated_at) "
                "VALUES (?, ?, 'queued', ?, ?, ?, ?)",
                (job_id, kind, json.dumps(payload), dedupe_key, now, now),
            )
        return self.get(job_id), True

    def get(self, job_id: str) -> Job:
        row = self.store.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise JobNotFound(job_id)
        return _row_to_job(row)

    def list_jobs(self, status: JobStatus | None = None) -> list[Job]:
        if status is None:
            rows = self.store.query("SELECT * FROM jobs ORDER BY created_at, rowid")
        else:
            rows = self.store.query("SELECT * FROM jobs WHERE status = ? ORDER BY created_at, rowid", (status,))
        return [_row_to_job(r) for r in rows]

    def claim(self, kinds: tuple[JobKind, ...]) -> Job | None:
        """Atomically move the oldest queued job of the given kinds to `running`."""
        marks = ",".join("?" * len(kinds))
        with self.store.tx() as conn:
            row = conn.execute(
                f"SELECT id FROM jobs WHERE status = 'queued' AND kind IN ({marks}) ORDER BY created_at, rowid LIMIT 1",  # noqa: S608
                kinds,
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?",
                (iso_now(), row["id"]),
            )
        return self.get(row["id"])

    def progress(self, job_id: str, stage: str, progress: float) -> None:
        self._update(job_id, "status = 'running'", stage=stage, progress=max(0.0, min(1.0, progress)))

    def complete(self, job_id: str) -> Job:
        return self._finish(job_id, "completed", None)

    def fail(self, job_id: str, error: str) -> Job:
        return self._finish(job_id, "failed", error)

    def request_cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status == "queued":
            return self._finish(job_id, "canceled", "canceled before start")
        if job.status == "running":
            self.store.execute("UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?", (iso_now(), job_id))
        return self.get(job_id)

    def cancel_requested(self, job_id: str) -> bool:
        row = self.store.query_one("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,))
        if row is None:
            raise JobNotFound(job_id)
        return bool(row["cancel_requested"])

    def recover(self) -> list[str]:
        """On startup: jobs left `running` by a dead process go back to `queued` (resume, NFR-REL-04)."""
        rows = self.store.query("SELECT id, cancel_requested FROM jobs WHERE status = 'running'")
        resumed: list[str] = []
        for r in rows:
            if r["cancel_requested"]:
                self._finish(r["id"], "canceled", "canceled during restart")
            else:
                self.store.execute(
                    "UPDATE jobs SET status = 'queued', updated_at = ? WHERE id = ?", (iso_now(), r["id"])
                )
                resumed.append(r["id"])
        return resumed

    def _update(self, job_id: str, guard: str, **fields: Any) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.store.tx() as conn:
            cur = conn.execute(
                f"UPDATE jobs SET {sets}, updated_at = ? WHERE id = ? AND {guard}",  # noqa: S608 - fixed column names
                (*fields.values(), iso_now(), job_id),
            )
            if cur.rowcount == 0:
                raise JobStateError(f"{job_id}: not in a state that allows this update")

    def _finish(self, job_id: str, status: JobStatus, error: str | None) -> Job:
        progress_sql = ", progress = 1" if status == "completed" else ""
        with self.store.tx() as conn:
            cur = conn.execute(
                f"UPDATE jobs SET status = ?, error = ?{progress_sql}, updated_at = ? "  # noqa: S608
                "WHERE id = ? AND status IN ('queued', 'running')",
                (status, error, iso_now(), job_id),
            )
            if cur.rowcount == 0:
                raise JobStateError(f"{job_id}: already finished")
        return self.get(job_id)
