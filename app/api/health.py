"""api / health responsibilities."""
from __future__ import annotations

from fastapi import APIRouter
from app.corpus_config import corpus_config
from qdrant_client import QdrantClient
from typing import Any
import os

router = APIRouter()



@router.get("/health")
def health() -> dict[str, Any]:
    try:
        QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=5).get_collections()
        return {"status": "ok", "qdrant": "ok", "corpus_id": corpus_config().id,
                "corpus_dir": str(corpus_config().books)}
    except Exception as exc:
        return {"status": "degraded", "qdrant": str(exc)}

