"""Fail-open Langfuse observation contexts for interactive and judge calls."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import logging
import os
from typing import Any, Iterator

logger = logging.getLogger(__name__)
_client_context: ContextVar[Any | None] = ContextVar("corpus_langfuse_client", default=None)


def pack_scope_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Keep useful Alienist trace identity fields within OTel attribute limits.

    Langfuse propagates each metadata entry as a separate OpenTelemetry
    attribute. The full Alienist run metadata belongs on the experiment and
    execution manifest; nested spans only need the compact join keys and model
    selection. Millennium keeps its existing metadata shape unchanged.
    """
    if os.getenv("CORPUS_ID", "millennium") != "thealienist":
        return attributes
    packed = dict(attributes)
    metadata = packed.get("metadata")
    if isinstance(metadata, dict):
        trace_keys = {
            "execution_id", "dataset_id", "dataset_version", "dataset_item_id",
            "pipeline_id", "pipeline_version", "pipeline_derived", "evaluator_id",
            "experiment_run", "answer_cache_status", "agent_provider", "agent_model",
            "agent_reasoning_effort", "agent_think", "agent_context_length",
        }
        packed["metadata"] = {key: value for key, value in metadata.items() if key in trace_keys}
    return packed


@contextmanager
def use_client(client: Any) -> Iterator[None]:
    token = _client_context.set(client)
    try:
        yield
    finally:
        _client_context.reset(token)


@contextmanager
def trace_scope(**attributes: Any) -> Iterator[None]:
    """Attach Langfuse trace attributes when configured; otherwise keep the request local."""
    try:
        try:
            from .corpus_profiles import langfuse_enabled
        except ImportError:
            from corpus_profiles import langfuse_enabled
        if not langfuse_enabled():
            yield
            return
        from langfuse import propagate_attributes
        scope = propagate_attributes(**pack_scope_attributes(attributes))
    except Exception:
        yield
        return
    body_failed = False
    try:
        with scope:
            try:
                yield
            except BaseException:
                body_failed = True
                raise
    except Exception:
        if body_failed:
            raise
        logger.debug("Langfuse trace scope failed", exc_info=True)


@contextmanager
def observation(name: str, *, as_type: str = "span", input: Any = None,
                model: str | None = None, prompt: Any = None, metadata: dict[str, Any] | None = None) -> Iterator[Any | None]:
    try:
        try:
            from .corpus_profiles import langfuse_enabled
        except ImportError:
            from corpus_profiles import langfuse_enabled
        if not langfuse_enabled():
            context = nullcontext(None)
        else:
            client = _client_context.get()
            if client is None:
                from langfuse import get_client
                client = get_client()
            context = client.start_as_current_observation(as_type=as_type, name=name,
                                                          input=input, model=model, metadata=metadata, prompt=prompt)
    except Exception:
        context = nullcontext(None)
    body_failed = False
    try:
        with context as obs:
            try:
                yield obs
            except BaseException:
                body_failed = True
                raise
    except Exception:
        if body_failed:
            raise
        # Observability setup or flush issues must not change interactive answers.


def update(observation: Any | None, **fields: Any) -> None:
    if observation is None:
        return
    try:
        observation.update(**fields)
    except Exception:
        logger.debug("Langfuse observation update failed", exc_info=True)


def record_cache_lookup(layer: str, status: str, duration_seconds: float,
                        source_trace_id: str | None = None, *, input: Any = None,
                        output: Any = None, compute_seconds: float | None = None,
                        saved_seconds: float | None = None, operation: str | None = None,
                        write_status: str | None = None) -> None:
    """Record a cache layer result as a named, searchable Langfuse span."""
    details: dict[str, Any] = {
        "cache_layer": layer,
        "cache_status": status,
        "cache_lookup_seconds": round(max(0.0, duration_seconds), 6),
    }
    if source_trace_id:
        details["cache_source_trace_id"] = source_trace_id
    if compute_seconds is not None:
        details["cache_compute_seconds"] = round(max(0.0, compute_seconds), 6)
    if saved_seconds is not None:
        details["cache_saved_seconds"] = round(max(0.0, float(saved_seconds)), 6)
    if operation is not None:
        details["cache_operation"] = operation
    if write_status is not None:
        details["cache_write_status"] = write_status
    with observation(f"cache {status}: {layer}", as_type="span",
                     input=input if input is not None else {"cache_layer": layer},
                     metadata=details) as obs:
        update(obs, output=output if output is not None else details)
