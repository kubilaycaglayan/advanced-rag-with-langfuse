"""api / indexing responsibilities."""
from __future__ import annotations

from fastapi import APIRouter
from app.api.schemas import IndexRequest
from app.indexing.passages import build_index
from app.pipelines.config import ResolvedPipelineConfig
from app.pipelines.config import resolve_pipeline_model_identities
from app.pipelines.resolver import resolve
from fastapi import HTTPException
from typing import Any

router = APIRouter()


@router.post("/index")
def index(request: IndexRequest) -> dict[str, Any]:
    try:
        if request.pipeline is None:
            config = resolve_pipeline_model_identities(ResolvedPipelineConfig.from_mapping(request.config))
            return build_index(config, explicit_rebuild=request.explicit_rebuild)
        if "config" in request.model_fields_set and "settings" in request.model_fields_set:
            raise ValueError("config and settings cannot both be present")
        if "settings" in request.model_fields_set and not isinstance(request.settings, dict):
            raise ValueError("settings must be an object")
        resolved = resolve(request.pipeline, request.settings if request.settings is not None else request.config)
        result = build_index(resolved.config, explicit_rebuild=request.explicit_rebuild)
        if result["collection"] != resolved.index["collection"]:
            raise ValueError(f"{resolved.version}: built collection differs from pinned collection")
        return {**result, "pipeline_version": resolved.version}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
