"""Durable SQLite queue, execution state and fingerprinted index manifests."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .identity import canonical_json
except ImportError:
    from identity import canonical_json

_local = threading.local()


def db_path() -> Path:
    path = Path(os.getenv("EXPERIMENT_DATA_DIR", "./data")) / "experiments.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(db_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def initialize() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS executions (
          execution_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE, status TEXT NOT NULL,
          payload_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          started_at TEXT, finished_at TEXT, result_json TEXT, error TEXT
        );
        CREATE INDEX IF NOT EXISTS executions_status ON executions(status, created_at);
        CREATE TABLE IF NOT EXISTS index_manifests (
          collection_name TEXT NOT NULL, fingerprint TEXT NOT NULL, config_json TEXT NOT NULL,
          corpus_json TEXT NOT NULL, splitter_fingerprint TEXT NOT NULL,
          embedding_identity TEXT NOT NULL, vector_settings_json TEXT NOT NULL,
          expected_point_count INTEGER NOT NULL DEFAULT 0, actual_point_count INTEGER NOT NULL DEFAULT 0,
          state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY(collection_name, fingerprint)
        );
        """)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue(execution_id: str, payload: dict[str, Any], key: str | None) -> tuple[dict[str, Any], bool]:
    stamp = now()
    with connect() as db:
        if key:
            existing = db.execute("SELECT * FROM executions WHERE idempotency_key=?", (key,)).fetchone()
            if existing:
                return dict(existing), False
        db.execute("INSERT INTO executions(execution_id,idempotency_key,status,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                   (execution_id, key, "queued", canonical_json(payload), stamp, stamp))
        row = db.execute("SELECT * FROM executions WHERE execution_id=?", (execution_id,)).fetchone()
        return dict(row), True


def pending_jobs() -> list[dict[str, Any]]:
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM executions WHERE status='queued' ORDER BY created_at")]


def get_execution(execution_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM executions WHERE execution_id=?", (execution_id,)).fetchone()
        return dict(row) if row else None


def update_execution(execution_id: str, *, status: str, result: Any = None, error: str | None = None,
                     started: bool = False, finished: bool = False) -> None:
    stamp = now()
    fields = ["status=?", "updated_at=?", "error=?"]
    values: list[Any] = [status, stamp, error]
    if result is not None:
        fields.append("result_json=?")
        values.append(canonical_json(result))
    if started:
        fields.append("started_at=?")
        values.append(stamp)
    if finished:
        fields.append("finished_at=?")
        values.append(stamp)
    values.append(execution_id)
    with connect() as db:
        db.execute(f"UPDATE executions SET {', '.join(fields)} WHERE execution_id=?", values)


def mark_interrupted() -> int:
    stamp = now()
    with connect() as db:
        cursor = db.execute("UPDATE executions SET status='failed',error='worker stopped while execution was active',updated_at=?,finished_at=? WHERE status='running'", (stamp, stamp))
        return cursor.rowcount


def save_index_manifest(*, collection: str, fingerprint: str, config: dict[str, Any], corpus: dict[str, Any],
                        splitter_fingerprint: str, embedding_identity: str, vector_settings: dict[str, Any],
                        expected: int, actual: int, state: str) -> None:
    stamp = now()
    with connect() as db:
        db.execute("""INSERT INTO index_manifests VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(collection_name,fingerprint) DO UPDATE SET config_json=excluded.config_json,
        corpus_json=excluded.corpus_json,splitter_fingerprint=excluded.splitter_fingerprint,
        embedding_identity=excluded.embedding_identity,vector_settings_json=excluded.vector_settings_json,
        expected_point_count=excluded.expected_point_count,actual_point_count=excluded.actual_point_count,
        state=excluded.state,updated_at=excluded.updated_at""",
        (collection, fingerprint, canonical_json(config), canonical_json(corpus), splitter_fingerprint,
         embedding_identity, canonical_json(vector_settings), expected, actual, state, stamp, stamp))


def get_ready_manifest(collection: str, fingerprint: str | None = None) -> dict[str, Any] | None:
    with connect() as db:
        if fingerprint:
            row = db.execute("SELECT * FROM index_manifests WHERE collection_name=? AND fingerprint=? AND state='ready'", (collection, fingerprint)).fetchone()
        else:
            row = db.execute("SELECT * FROM index_manifests WHERE collection_name=? AND state='ready' ORDER BY updated_at DESC LIMIT 1", (collection,)).fetchone()
        return dict(row) if row else None


def get_index_manifest(collection: str, fingerprint: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM index_manifests WHERE collection_name=? AND fingerprint=?", (collection, fingerprint)).fetchone()
        return dict(row) if row else None
