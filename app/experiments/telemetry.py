"""experiments / telemetry responsibilities."""
from __future__ import annotations

from app.experiments.datasets import _item_session
from app.identity import question_label
from app.observability import observation
from langfuse import Langfuse
from langfuse import propagate_attributes
from opentelemetry import trace as otel_trace_api
from typing import Any
import queue
import threading
import time


class ExperimentLangfuse(Langfuse):
    """Scope the SDK's entire item tree, including root and judges, to one question.

    The question tag also reaches the item's scores: score charts filter on their trace's tags.

    This adapter targets the pinned Langfuse 4.17 SDK. Its item hook is covered by
    a regression test and the live observation/session acceptance check.
    """
    async def _process_experiment_item(self, item: Any, *args: Any, **kwargs: Any) -> Any:
        session = _item_session(item.dataset_name, item)
        tags = [f"question:{question_label(item.dataset_name, item.id, item.metadata)}"]
        with propagate_attributes(session_id=session, tags=tags, environment="sdk-experiment"):
            return await super()._process_experiment_item(item, *args, **kwargs)


def _client() -> Langfuse:
    return ExperimentLangfuse(environment="sdk-experiment")


def _flush_client(client: Langfuse, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    """Flush SDK queues without shutting down the process-wide shared manager."""
    result: dict[str, Any] = {"completed": False, "error": None}

    def cleanup() -> None:
        resources = getattr(client, "_resources", None)
        if resources is None:
            result["error"] = "Langfuse client has no initialized resources"
            result["completed"] = True
            return
        deadline = time.monotonic() + timeout_seconds
        try:
            provider = getattr(resources, "tracer_provider", None)
            if provider is not None and not isinstance(provider, otel_trace_api.ProxyTracerProvider):
                provider_timeout = max(1000, int(min(timeout_seconds, 10.0) * 1000))
                if not provider.force_flush(timeout_millis=provider_timeout):
                    result["error"] = "Langfuse trace exporter flush timed out"
                    result["completed"] = True
                    return
        except Exception as exc:
            result["error"] = f"Langfuse trace exporter flush failed: {type(exc).__name__}: {exc}"
            result["completed"] = True
            return
        for queue_name in ("_score_ingestion_queue", "_media_upload_queue"):
            queue = getattr(resources, queue_name, None)
            while queue is not None and queue.unfinished_tasks and time.monotonic() < deadline:
                time.sleep(0.05)
            if queue is not None and queue.unfinished_tasks:
                result["error"] = f"Langfuse {queue_name.removeprefix('_').removesuffix('_queue')} queue has {queue.unfinished_tasks} pending task(s)"
                result["completed"] = True
                return
        result["completed"] = True

    thread = threading.Thread(target=cleanup, name="langfuse-bounded-cleanup", daemon=True)
    thread.start()
    thread.join(timeout_seconds + 2)
    if thread.is_alive():
        result["error"] = f"Langfuse flush exceeded {timeout_seconds:g}s"
    return result


def _verify_trace_upload(client: Langfuse, trace_id: str | None, *, attempts: int = 5) -> str | None:
    """Confirm the item task reached Langfuse; exporter flush alone can hide HTTP failures."""
    if not trace_id:
        return "Langfuse experiment item did not return a trace ID"
    last_error = "Langfuse observations API did not return experiment-item-task"
    for attempt in range(attempts):
        try:
            cursor = None
            seen_cursors: set[str] = set()
            while True:
                page = client.api.observations.get_many(trace_id=trace_id, limit=100, cursor=cursor)
                if any(observation.name == "experiment-item-task" for observation in page.data or []):
                    return None
                next_cursor = page.meta.cursor if page.meta else None
                if not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
        except Exception as exc:
            last_error = f"Langfuse observations lookup failed: {type(exc).__name__}: {exc}"
        if attempt + 1 < attempts:
            time.sleep(0.5)
    return f"trace {trace_id}: {last_error}"
