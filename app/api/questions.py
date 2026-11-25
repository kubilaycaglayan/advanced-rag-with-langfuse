"""api / questions responsibilities."""
from __future__ import annotations

from app.answering.interactive import _run_ask
from app.api.access import _require_langfuse_project_access
from app.api.access import _reserve_ask_slot
from fastapi import APIRouter
from app.api.schemas import AskRequest
from app.cache import answers as answer_cache
from app.frontend_rate_limit import reserve_request
from app.indexing.passages import validate_index
from app.pipelines.resolver import resolve
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from typing import Any
import contextvars
import json
import os
import queue
import threading

router = APIRouter()


def _prepare_ask(request: AskRequest) -> dict[str, Any]:
    """Check the rate limit and resolve the configuration and index for one question."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be blank")
    if (os.getenv("FRONTEND_RATE_LIMIT_ENABLED") == "true" and request.production and request.source == "frontend"
            and request.client_ip and not request.client_ip.is_loopback):
        retry_after = reserve_request(str(request.client_ip))
        if retry_after is not None:
            raise HTTPException(status_code=429, detail="Question limit reached. Please try again later.",
                                headers={"Retry-After": str(retry_after)})
    try:
        _require_langfuse_project_access()
        if "settings" in request.model_fields_set and not isinstance(request.settings, dict):
            raise ValueError("settings must be an object")
        answer_cache.normalize_layers(request.cache_layers)
        values = dict(request.settings or {})
        for legacy, key in (("mode", "retrieval_mode"), ("passage_chars", "passage_chars")):
            value = getattr(request, legacy)
            if value is not None:
                if key in values:
                    raise ValueError(f"{legacy} and settings.{key} cannot both be present")
                values[key] = value
        resolved = resolve(request.pipeline, values, engine=request.engine,
                           collection=request.collection)
        collection = resolved.index["collection"]
        validate_index(collection, resolved.config)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"config": resolved.config, "collection": collection,
            "pipeline_id": resolved.pipeline_id, "resolved": resolved}


@router.post("/ask")
def ask(request: AskRequest) -> dict[str, Any]:
    slot = _reserve_ask_slot()
    try:
        prepared = _prepare_ask(request)
        return _run_ask(request, prepared)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        slot.close()


@router.post("/ask/stream")
def ask_stream(request: AskRequest) -> StreamingResponse:
    """/ask as newline-delimited JSON events: trace, status, token (the answer as it is written), then done or error.

    The pipeline runs in its own thread, in a copy of this request's context, so its Langfuse trace is the one /ask
    records; it finishes and records its trace even if the client goes away.
    """
    slot = _reserve_ask_slot()
    try:
        prepared = _prepare_ask(request)
    except BaseException:
        slot.close()
        raise
    events: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            result = _run_ask(request, prepared, on_trace=lambda trace_id: events.put({"type": "trace", "trace_id": trace_id}),
                              on_token=lambda text: events.put({"type": "token", "text": text}),
                              on_status=lambda status: events.put({"type": "status", "status": status}))
            events.put({"type": "done", "result": result})
        except Exception as exc:
            events.put({"type": "error", "status": 400 if isinstance(exc, ValueError) else 502, "detail": str(exc)})
        finally:
            slot.close()
            events.put(None)

    try:
        threading.Thread(target=contextvars.copy_context().run, args=(work,), daemon=True).start()
    except BaseException:
        slot.close()
        raise

    def lines():
        while (event := events.get()) is not None:
            yield json.dumps(event, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

