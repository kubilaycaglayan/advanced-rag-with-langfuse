"""Fail-open, identity-scoped Redis caches for reusable pipeline intermediates."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import logging
import time
from typing import Any, Callable, Iterator
from urllib.parse import quote

try:
    from .answer_cache import _redis_client
    from .identity import canonical_json
    from .observability import observation, update
except ImportError:
    from answer_cache import _redis_client
    from identity import canonical_json
    from observability import observation, update

logger = logging.getLogger(__name__)
ROOT = "pipeline-cache:v1"
ENTRY_SECONDS = 30 * 24 * 60 * 60


class CacheContext:
    def __init__(self, mode: str, layers: tuple[str, ...], scope: dict[str, Any]):
        self.mode = mode
        self.layers = frozenset(layers)
        self.scope = scope


_context: ContextVar[CacheContext | None] = ContextVar("pipeline_cache_context", default=None)


@contextmanager
def use_cache(mode: str, layers: tuple[str, ...], scope: dict[str, Any]) -> Iterator[None]:
    token = _context.set(CacheContext(mode, layers, scope))
    try:
        yield
    finally:
        _context.reset(token)


def scope_for(resolved: Any, collection: str, project_id: str) -> dict[str, Any]:
    """The stable parent identity shared by all intermediate cache layers."""
    return {
        "project_id": project_id,
        "corpus_id": resolved.corpus_id,
        "corpus_checksum": resolved.corpus_checksum,
        "pipeline_version": resolved.version,
        "pipeline_fingerprint": resolved.fingerprint,
        "pipeline_id": resolved.pipeline_id,
        "profile_id": resolved.profile_id,
        "profile_identity": resolved.profile_identity,
        "prompt_identity": resolved.prompt_identity,
        "collection": collection,
        "config": resolved.config.manifest(),
        "agent_settings": resolved.agent_settings.__dict__ if resolved.agent_settings else None,
    }


def _redis_key(context: CacheContext, layer: str, key: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json({"scope": context.scope, "layer": layer, "key": key}).encode()).hexdigest()
    scope = context.scope
    return (f"{ROOT}:project/{quote(str(scope['project_id']), safe='')}:"
            f"corpus/{quote(str(scope['corpus_id']), safe='')}:"
            f"pipeline/{quote(str(scope['pipeline_version']), safe='')}:"
            f"{layer}/{digest}")


def cache_value(layer: str, operation: str, key: dict[str, Any], *, input: Any,
                compute: Callable[[], Any], trace_output: Callable[[Any], Any] | None = None) -> Any:
    """Read or compute a JSON value, and trace its cost/result without affecting the caller on Redis errors."""
    context = _context.get()
    selected = context is not None and layer in context.layers
    mode = context.mode if context else "bypass"
    cache_key = _redis_key(context, layer, {"operation": operation, **key}) if selected else None
    lookup_seconds = 0.0
    compute_seconds = 0.0
    saved_seconds = None
    write_status = "skipped"
    status = "bypassed" if not selected or mode == "bypass" else "miss"
    client = None
    trace_input = input
    if layer == "tool_read" and isinstance(input, dict) and isinstance(key.get("question"), str):
        trace_input = {**input, "question": key["question"]}

    # Start the span before Redis/model/index work so its Langfuse duration measures
    # the actual operation. Status and precise component timings are attached after.
    with observation(f"cache: {layer}", as_type="span", input=trace_input,
                     metadata={"cache_layer": layer, "cache_operation": operation,
                               "cache_status": "pending"}) as span:
        try:
            if selected and mode == "use":
                started = time.perf_counter()
                try:
                    client = _redis_client()
                    encoded = client.get(cache_key)
                    lookup_seconds = time.perf_counter() - started
                    if encoded is not None:
                        record = json.loads(encoded)
                        if isinstance(record, dict) and "value" in record:
                            saved_seconds = record.get("compute_seconds")
                            value = record["value"]
                            output = trace_output(value) if trace_output else value
                            update(span, name=f"cache hit: {layer}", output=output, metadata={
                                "cache_layer": layer, "cache_operation": operation, "cache_status": "hit",
                                "cache_lookup_seconds": round(max(0.0, lookup_seconds), 6),
                                "cache_compute_seconds": 0.0,
                                "cache_saved_seconds": round(max(0.0, float(saved_seconds or 0.0)), 6),
                                "cache_write_status": "not_needed",
                            })
                            return value
                    status = "miss"
                except Exception as exc:
                    lookup_seconds = time.perf_counter() - started
                    status = "unavailable"
                    logger.warning("Intermediate %s cache lookup failed: %s", layer, exc)

            started_compute = time.perf_counter()
            value = compute()
            compute_seconds = time.perf_counter() - started_compute

            if selected and mode in {"use", "refresh"} and status != "unavailable":
                try:
                    if client is None:
                        client = _redis_client()
                    client.set(cache_key, canonical_json({"value": value, "compute_seconds": compute_seconds}),
                               ex=ENTRY_SECONDS)
                    write_status = "stored"
                    if mode == "refresh":
                        status = "refreshed"
                except Exception as exc:
                    write_status = "unavailable"
                    status = "unavailable"
                    logger.warning("Intermediate %s cache write failed: %s", layer, exc)
            elif selected and mode == "refresh":
                status = "unavailable" if status == "unavailable" else "refreshed"

            output = trace_output(value) if trace_output else value
            update(span, name=f"cache {status}: {layer}", output=output, metadata={
                "cache_layer": layer, "cache_operation": operation, "cache_status": status,
                "cache_lookup_seconds": round(max(0.0, lookup_seconds), 6),
                "cache_compute_seconds": round(max(0.0, compute_seconds), 6),
                "cache_saved_seconds": saved_seconds,
                "cache_write_status": write_status,
            })
            return value
        except BaseException as exc:
            update(span, name=f"cache error: {layer}", level="ERROR", status_message=str(exc), metadata={
                "cache_layer": layer, "cache_operation": operation, "cache_status": "error",
                "cache_lookup_seconds": round(max(0.0, lookup_seconds), 6),
                "cache_compute_seconds": round(max(0.0, compute_seconds), 6),
            })
            raise
