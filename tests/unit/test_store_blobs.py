from __future__ import annotations

from pathlib import Path

import pytest

from loom.core.blobs import BlobIntegrityError, BlobStore, stage_key
from loom.core.store import MigrationError, Store, discover_migrations

SPEC_TABLES = {
    "videos",
    "artifacts",
    "jobs",
    "events",
    "learners",
    "mastery",
    "sessions",
    "session_events",
    "quiz_attempts",
    "explainers",
    "safety_reviews",
    "agents",
    "cut_cache",
    "llm_cache",
}


def test_migrations_create_every_spec_table(store: Store) -> None:
    assert set(store.tables()) >= SPEC_TABLES
    assert store.schema_version == len(discover_migrations())


def test_migrate_is_idempotent_and_survives_reopen(tmp_path: Path) -> None:
    s = Store(tmp_path / "x.db")
    assert s.migrate() == [v for v, _ in discover_migrations()]
    assert s.migrate() == []
    s.execute("INSERT INTO events (channel, kind, payload, ts) VALUES ('system', 'error', '{}', 'now')")
    s.close()
    s2 = Store(tmp_path / "x.db")
    assert s2.migrate() == []
    assert s2.query_one("SELECT COUNT(*) AS n FROM events")["n"] == 1  # type: ignore[index]
    assert s2.query_one("PRAGMA journal_mode")[0] == "wal"  # type: ignore[index]
    s2.close()


def test_tx_rolls_back_on_error(store: Store) -> None:
    def write_then_fail() -> None:
        with store.tx() as conn:
            conn.execute("INSERT INTO events (channel, kind, payload, ts) VALUES ('system', 'error', '{}', 'now')")
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        write_then_fail()
    assert store.query_one("SELECT COUNT(*) AS n FROM events")["n"] == 0  # type: ignore[index]


def test_safety_review_status_is_constrained(store: Store) -> None:
    with pytest.raises(Exception, match="CHECK"):
        store.execute(
            "INSERT INTO safety_reviews (video_id, object_id, status, updated_at) VALUES ('v', 'o_001', 'none', 'x')"
        )


def test_bad_migration_names(tmp_path: Path) -> None:
    (tmp_path / "0001_init.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0003_gap.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="contiguous"):
        discover_migrations(tmp_path)
    (tmp_path / "3_bad.sql").write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(MigrationError, match="bad migration file name"):
        discover_migrations(tmp_path)


def test_blobs_are_content_addressed_and_idempotent(tmp_path: Path) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    a = blobs.put_bytes(b"hello", ".txt")
    b = blobs.put_bytes(b"hello", ".txt")
    assert a == b
    assert a.sha256 == "sha256:2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert a.path.parent.name == "2c" and a.path.name.endswith(".txt")
    assert blobs.find(a.sha256) == a.path
    assert blobs.read_bytes(a.sha256) == b"hello"
    assert blobs.put_bytes(b"world").sha256 != a.sha256


def test_put_file_and_tamper_detection(tmp_path: Path) -> None:
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00" * 300_000)
    blobs = BlobStore(tmp_path / "blobs")
    ref = blobs.put_file(src)
    assert ref.size == 300_000 and ref.path.suffix == ".mp4"
    assert blobs.verify(ref.sha256)
    ref.path.write_bytes(b"replaced on disk")  # F10: a verified clip replaced on disk
    assert not blobs.verify(ref.sha256)
    with pytest.raises(BlobIntegrityError):
        blobs.read_bytes(ref.sha256)


def test_stage_key_is_deterministic_and_input_sensitive() -> None:
    k1 = stage_key({"video": "sha256:aa", "b": 1}, "asr@2", {"asr": "large-v3-turbo"})
    k2 = stage_key({"b": 1, "video": "sha256:aa"}, "asr@2", {"asr": "large-v3-turbo"})
    assert k1 == k2
    assert stage_key({"video": "sha256:aa", "b": 1}, "asr@3", {"asr": "large-v3-turbo"}) != k1


def test_bad_refs(tmp_path: Path) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    with pytest.raises(ValueError, match="sha256"):
        blobs.path_for("md5:abc")
    with pytest.raises(ValueError, match="extension"):
        blobs.path_for("sha256:" + "0" * 64, "../x")
    assert blobs.find("sha256:" + "0" * 64) is None
