"""experiments / queue responsibilities."""
from __future__ import annotations

from app.experiments.execution import execute_execution
from app.experiments.store import enqueue
from app.experiments.store import get_execution
from app.experiments.store import mark_interrupted
from app.experiments.store import pending_jobs
from app.storage import initialize
from typing import Any
import json
import queue
import threading
import uuid



_jobs: queue.Queue[str] = queue.Queue()



_worker: threading.Thread | None = None



def submit(payload: dict[str, Any], *, idempotency_key: str | None = None) -> tuple[dict[str, Any], bool]:
    execution_id = str(uuid.uuid4())
    row, created = enqueue(execution_id, payload, idempotency_key)
    if created:
        _jobs.put(execution_id)
    return row, created



def submit_retry(execution_id: str, *, idempotency_key: str | None = None) -> tuple[dict[str, Any], bool]:
    """Queue a deliberate, linked retry of a failed or partial execution."""
    source = get_execution(execution_id)
    if source is None:
        raise KeyError(execution_id)
    if source["status"] not in {"failed", "partial"}:
        raise ValueError(f"only failed or partial executions can be retried (status={source['status']})")
    payload = json.loads(source["payload_json"])
    if "pipeline" not in payload:
        raise ValueError("pre-migration executions cannot be retried")
    payload["retry_of_execution_id"] = execution_id
    return submit(payload, idempotency_key=idempotency_key)



def _worker_loop() -> None:
    while True:
        execution_id = _jobs.get()
        try:
            execute_execution(execution_id)
        finally:
            _jobs.task_done()



def start_worker() -> None:
    global _worker
    initialize()
    mark_interrupted()
    for row in pending_jobs():
        _jobs.put(row["execution_id"])
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_worker_loop, name="experiment-worker", daemon=True)
        _worker.start()

