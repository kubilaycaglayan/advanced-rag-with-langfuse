"""experiments / store responsibilities."""
from __future__ import annotations

from app.identity import canonical_json
from app.storage import connect
from app.storage import now
from typing import Any


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
