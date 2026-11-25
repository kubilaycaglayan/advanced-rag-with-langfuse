"""api / access responsibilities."""
from __future__ import annotations

from app.corpus_config import corpus_data_dir
from app.corpus_config import langfuse_project
from app.corpus_profiles import langfuse_enabled
from app.corpus_profiles import langfuse_tracing_required
from fastapi import HTTPException
from langfuse import get_client
from typing import BinaryIO
import errno
import fcntl



def _require_langfuse_project_access() -> None:
    if not langfuse_tracing_required():
        return
    if not langfuse_enabled():
        raise HTTPException(status_code=503, detail="Langfuse tracing is required for this corpus but is not configured")
    try:
        projects = getattr(get_client().api.projects.get(), "data", []) or []
        matches = [project for project in projects if project.name == langfuse_project()]
        if len(matches) != 1:
            raise HTTPException(status_code=503, detail=f"Langfuse credentials must access project {langfuse_project()!r}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Langfuse project access could not be verified") from exc



def _reserve_ask_slot() -> BinaryIO:
    """Allow one interactive question across workers sharing the data directory."""
    path = corpus_data_dir() / "interactive-ask.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    slot = path.open("a+b")
    try:
        fcntl.flock(slot.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        slot.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            raise HTTPException(status_code=429, detail="A question is already in progress. Please try again later.") from exc
        raise
    return slot

