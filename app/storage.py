"""storage responsibilities."""
from __future__ import annotations

from app.corpus_config import corpus_data_dir
from datetime import datetime
from datetime import timezone
from pathlib import Path
import sqlite3
import threading


_local = threading.local()


def db_path() -> Path:
    path = corpus_data_dir() / "experiments.sqlite3"
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

