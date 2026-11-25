"""indexing / manifests responsibilities."""
from __future__ import annotations

from app.identity import canonical_json
from app.storage import connect
from app.storage import now
from typing import Any


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
