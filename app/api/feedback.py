"""api / feedback responsibilities."""
from __future__ import annotations

from fastapi import APIRouter
from app.api.logging import logger
from app.api.schemas import CacheFeedbackRequest
from app.cache import answers as answer_cache
from fastapi import HTTPException
from typing import Any

router = APIRouter()



@router.post("/cache/feedback")
def cache_feedback(request: CacheFeedbackRequest) -> dict[str, Any]:
    try:
        status = answer_cache.record_feedback(trace_id=request.trace_id, owner_id=request.owner_id,
                                              helpful=request.helpful)
        return {"saved": True, "cache_status": status}
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("Answer cache feedback update failed: %s", exc)
        return {"saved": True, "cache_status": "unavailable"}

