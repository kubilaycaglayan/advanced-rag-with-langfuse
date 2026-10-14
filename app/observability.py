"""Fail-open Langfuse observation contexts for interactive and judge calls."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
import logging
from typing import Any, Iterator

logger = logging.getLogger(__name__)
_client_context: ContextVar[Any | None] = ContextVar("millennium_langfuse_client", default=None)


@contextmanager
def use_client(client: Any) -> Iterator[None]:
    token = _client_context.set(client)
    try:
        yield
    finally:
        _client_context.reset(token)


@contextmanager
def observation(name: str, *, as_type: str = "span", input: Any = None,
                model: str | None = None, metadata: dict[str, Any] | None = None) -> Iterator[Any | None]:
    try:
        client = _client_context.get()
        if client is None:
            from langfuse import get_client
            client = get_client()
        context = client.start_as_current_observation(as_type=as_type, name=name,
                                                      input=input, model=model, metadata=metadata)
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
