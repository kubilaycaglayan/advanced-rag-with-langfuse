"""api / application responsibilities."""
from __future__ import annotations

from app.corpus_config import corpus_config
from app.storage import initialize
from app.experiments.queue import start_worker
from app.pipelines.catalog import load_catalog
from fastapi import FastAPI
from app.api.questions import router as questions_router
from app.api.indexing import router as indexing_router
from app.api.feedback import router as feedback_router
from app.api.proxy import router as proxy_router
from app.api.experiments import router as experiments_router
from app.api.health import router as health_router



app = FastAPI(title=f"{corpus_config().title} RAG Experiment Runner", version="0.2.0")



@app.on_event("startup")
def startup() -> None:
    load_catalog()
    initialize()
    start_worker()




app.include_router(questions_router)
app.include_router(indexing_router)
app.include_router(feedback_router)
app.include_router(proxy_router)
app.include_router(experiments_router)
app.include_router(health_router)
