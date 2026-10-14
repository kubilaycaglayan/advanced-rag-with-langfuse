"""FastAPI entry points for interactive RAG and queued Langfuse experiments."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from langfuse import Langfuse
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient

try:
    from .experiment_store import get_execution, initialize
    from .experiments import start_worker, submit, submit_retry
    from .indexer import build_index, index_identity, validate_index
    from .observability import observation, update as update_observation
    from .pipeline import run_pipeline
    from .resolved_config import ResolvedPipelineConfig, resolve_pipeline_model_identities
except ImportError:
    from experiment_store import get_execution, initialize
    from experiments import start_worker, submit, submit_retry
    from indexer import build_index, index_identity, validate_index
    from observability import observation, update as update_observation
    from pipeline import run_pipeline
    from resolved_config import ResolvedPipelineConfig, resolve_pipeline_model_identities

app = FastAPI(title="Millennium RAG Experiment Runner", version="0.2.0")


def _custom_payload(incoming: dict[str, Any]) -> dict[str, Any]:
    custom = incoming.get("customPayload", incoming.get("custom_payload", incoming.get("payload", {})))
    if isinstance(custom, str):
        try:
            custom = json.loads(custom)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="custom payload must be valid JSON") from exc
    if not isinstance(custom, dict):
        raise HTTPException(status_code=400, detail="custom payload must be an object")
    return dict(custom)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    candidate_count: int = Field(default=30, ge=5, le=100)
    top_k: int = Field(default=10, ge=1, le=10)
    mode: str = Field(default="baseline", pattern="^(baseline|hyde|query_expansion|hyde_query_expansion)$")
    passage_chars: int | None = Field(default=None, ge=1)
    collection: str | None = None


class IndexRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)
    explicit_rebuild: bool = False


@app.on_event("startup")
def startup() -> None:
    initialize()
    start_worker()


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=5).get_collections()
        return {"status": "ok", "qdrant": "ok", "corpus_dir": os.getenv("CORPUS_DIR", "corpus")}
    except Exception as exc:
        return {"status": "degraded", "qdrant": str(exc)}


@app.post("/index")
def index(request: IndexRequest) -> dict[str, Any]:
    try:
        config = resolve_pipeline_model_identities(ResolvedPipelineConfig.from_mapping(request.config))
        return build_index(config, explicit_rebuild=request.explicit_rebuild)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/ask")
def ask(request: AskRequest) -> dict[str, Any]:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be blank")
    try:
        values = {"retrieval_mode": request.mode, "candidate_count": request.candidate_count,
                  "top_k": min(request.top_k, request.candidate_count)}
        if request.passage_chars is not None:
            values["passage_chars"] = request.passage_chars
        config = resolve_pipeline_model_identities(ResolvedPipelineConfig.from_mapping(values))
        collection = request.collection
        if collection is None:
            collection = index_identity(config)[0]
        validate_index(collection, config)
        with observation("rag ask", as_type="span", input={"question": request.question}) as obs:
            result = run_pipeline(request.question, config, collection=collection)
            update_observation(obs, output={"answer": result.get("answer"), "citations": result.get("citations")})
            return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _verify_signature(raw_body: bytes, signature: str | None) -> None:
    secret = os.getenv("LANGFUSE_WEBHOOK_SECRET")
    if not secret:
        return
    if not signature:
        raise HTTPException(status_code=401, detail="missing x-langfuse-signature")
    try:
        timestamp_pair, signature_pair = signature.split(",", 1)
        timestamp = timestamp_pair.split("=", 1)[1]
        supplied = signature_pair.split("=", 1)[1]
        if abs(time.time() - int(timestamp)) > 300:
            raise ValueError("signature timestamp is outside the 5 minute validity window")
    except (ValueError, IndexError) as exc:
        raise HTTPException(status_code=401, detail="malformed x-langfuse-signature") from exc
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()
    try:
        valid = hmac.compare_digest(bytes.fromhex(expected), bytes.fromhex(supplied))
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(status_code=401, detail="invalid x-langfuse-signature")


@app.post("/experiments/run", status_code=202)
async def trigger_experiment(request: Request,
        x_experiment_trigger_token: str | None = Header(default=None, alias="X-Experiment-Trigger-Token"),
        x_langfuse_signature: str | None = Header(default=None, alias="x-langfuse-signature"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
    expected_token = os.getenv("EXPERIMENT_TRIGGER_TOKEN")
    if not expected_token or not x_experiment_trigger_token or not hmac.compare_digest(expected_token, x_experiment_trigger_token):
        raise HTTPException(status_code=401, detail="invalid experiment trigger token")
    raw_body = await request.body()
    _verify_signature(raw_body, x_langfuse_signature)
    try:
        incoming = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="request body must be JSON") from exc
    if not isinstance(incoming, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    custom = _custom_payload(incoming)
    dataset_name = incoming.get("datasetName", incoming.get("dataset_name"))
    dataset_id = incoming.get("datasetId", incoming.get("dataset_id"))
    dataset_name = dataset_name or custom.pop("dataset_name", None)
    dataset_id = dataset_id or custom.pop("dataset_id", None)
    allowed = {"variant_label", "config", "dataset_version", "item_ids", "prompt_label"}
    unknown = set(custom) - allowed
    if unknown:
        raise HTTPException(status_code=400, detail=f"unsupported trigger fields: {', '.join(sorted(unknown))}")
    if not dataset_name:
        dataset_name = os.getenv("DATASET_NAME", "QA.csv")
    if "prompt_label" in custom and (not isinstance(custom["prompt_label"], str) or not custom["prompt_label"].strip()):
        raise HTTPException(status_code=400, detail="prompt_label must be a non-empty string")
    try:
        config = ResolvedPipelineConfig.from_mapping(custom.get("config"))
        custom["config"] = config.manifest()
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item_ids = custom.get("item_ids")
    if item_ids is not None and (not isinstance(item_ids, list) or not all(isinstance(value, str) for value in item_ids)):
        raise HTTPException(status_code=400, detail="item_ids must be an array of strings")
    try:
        # Langfuse's tracer/score queues are process-wide singletons keyed by
        # credentials. Do not shut this client down here: the queued worker uses
        # the same resource manager to export the experiment's traces and scores.
        client = Langfuse()
        dataset = client.get_dataset(dataset_name)
        if dataset_id and dataset.id != dataset_id:
            raise ValueError("trigger dataset_id does not match dataset_name")
        projects = getattr(client.api.projects.get(), "data", []) or []
        configured_project = next((project for project in projects
                                   if project.name == "millenium" and project.id == dataset.project_id), None)
        if configured_project is None:
            raise ValueError("dataset does not belong to configured Langfuse project 'millenium'")
        requested_project_id = incoming.get("projectId", incoming.get("project_id"))
        if requested_project_id and requested_project_id not in {dataset.project_id, configured_project.name}:
            raise ValueError("trigger projectId does not match dataset project")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Langfuse dataset access validation failed: {exc}") from exc
    payload = {"dataset_name": dataset_name, "dataset_id": dataset_id, **custom}
    row, created = submit(payload, idempotency_key=idempotency_key)
    return {"execution_id": row["execution_id"], "status": row["status"],
            "status_url": f"/experiments/{row['execution_id']}", "created": created}


@app.get("/experiments/{execution_id}")
def experiment_status(execution_id: str) -> dict[str, Any]:
    row = get_execution(execution_id)
    if row is None:
        raise HTTPException(status_code=404, detail="execution not found")
    result = json.loads(row["result_json"]) if row.get("result_json") else None
    payload = json.loads(row["payload_json"])
    return {"execution_id": execution_id, "status": row["status"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "started_at": row["started_at"], "finished_at": row["finished_at"],
            "dataset_name": payload.get("dataset_name"), "dataset_version": result.get("dataset_version") if result else payload.get("dataset_version"),
            "dataset_item_count": result.get("dataset_item_count") if result else None,
            "completed_item_count": result.get("completed_item_count") if result else None,
            "failed_item_count": result.get("failed_item_count") if result else None,
            "evaluation_failure_count": result.get("evaluation_failure_count") if result else None,
            "telemetry_failure_count": result.get("telemetry_failure_count") if result else None,
            "pipeline_id": result.get("pipeline_id") if result else None,
            "evaluator_id": result.get("evaluator_id") if result else None,
            "experiment_id": result.get("experiment_id") if result else None,
            "dataset_run_url": result.get("dataset_run_url") if result else None,
            "error": row.get("error"), "result": result}


@app.post("/experiments/{execution_id}/retry", status_code=202)
def retry_experiment(execution_id: str,
        x_experiment_trigger_token: str | None = Header(default=None, alias="X-Experiment-Trigger-Token"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
    expected_token = os.getenv("EXPERIMENT_TRIGGER_TOKEN")
    if not expected_token or not x_experiment_trigger_token or not hmac.compare_digest(expected_token, x_experiment_trigger_token):
        raise HTTPException(status_code=401, detail="invalid experiment trigger token")
    try:
        row, created = submit_retry(execution_id, idempotency_key=idempotency_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="execution not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"execution_id": row["execution_id"], "retry_of_execution_id": execution_id,
            "status": row["status"], "status_url": f"/experiments/{row['execution_id']}", "created": created}
