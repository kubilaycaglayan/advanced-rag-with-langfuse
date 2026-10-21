"""FastAPI entry points for interactive RAG and queued Langfuse experiments."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import asyncio
import contextvars
import errno
import fcntl
import queue
import threading
from pathlib import Path
from typing import Any, BinaryIO

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask
from langfuse import Langfuse, get_client
from pydantic import BaseModel, Field, IPvAnyAddress
from qdrant_client import QdrantClient

try:
    from . import answer_cache
    from .corpus_config import corpus_config, corpus_data_dir, langfuse_project, langfuse_dataset_name
    from .corpus_profiles import langfuse_enabled
    from .agent import AgentSettings, run_agent
    from .evaluator_specs import CORRECTNESS_SPECS
    from .experiment_store import get_execution, initialize
    from .frontend_rate_limit import reserve_request
    from .experiments import start_worker, submit, submit_retry
    from .indexer import build_index, index_identity, validate_index
    from .intermediate_cache import scope_for as intermediate_cache_scope, use_cache as use_intermediate_cache
    from .observability import observation, record_cache_lookup, trace_scope, update as update_observation
    from .prompt_assets import load_prompt_bundle, prompt_manifests
    from .pipeline import run_pipeline
    from .pipeline_setup import current_pipeline_setup
    from .pipeline_catalog import load_catalog
    from .pipeline_resolver import resolve
    from .pipeline_runner import run as run_resolved_pipeline
    from .resolved_config import ResolvedPipelineConfig, resolve_pipeline_model_identities
except ImportError:
    import answer_cache
    from corpus_config import corpus_config, corpus_data_dir, langfuse_project, langfuse_dataset_name
    from corpus_profiles import langfuse_enabled
    from agent import AgentSettings, run_agent
    from evaluator_specs import CORRECTNESS_SPECS
    from experiment_store import get_execution, initialize
    from frontend_rate_limit import reserve_request
    from experiments import start_worker, submit, submit_retry
    from indexer import build_index, index_identity, validate_index
    from intermediate_cache import scope_for as intermediate_cache_scope, use_cache as use_intermediate_cache
    from observability import observation, record_cache_lookup, trace_scope, update as update_observation
    from prompt_assets import load_prompt_bundle, prompt_manifests
    from pipeline import run_pipeline
    from pipeline_setup import current_pipeline_setup
    from pipeline_catalog import load_catalog
    from pipeline_resolver import resolve
    from pipeline_runner import run as run_resolved_pipeline
    from resolved_config import ResolvedPipelineConfig, resolve_pipeline_model_identities

app = FastAPI(title=f"{corpus_config().title} RAG Experiment Runner", version="0.2.0")
logger = logging.getLogger(__name__)


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
    pipeline: str | None = None
    settings: Any = None
    candidate_count: int | None = Field(default=None, ge=5, le=100)
    top_k: int | None = Field(default=None, ge=1, le=30)
    mode: str | None = Field(default=None, pattern="^(baseline|hyde|query_expansion|hyde_query_expansion|full)$")
    engine: str | None = Field(default=None, pattern="^(agent|fixed)$")
    passage_chars: int | None = Field(default=None, ge=1)
    collection: str | None = None
    prompt_label: str | None = None
    session_id: str | None = Field(default=None, min_length=1, max_length=200)
    user_id: str | None = Field(default=None, min_length=1, max_length=200)
    source: str = Field(default="api", pattern="^(api|frontend)$")
    client_ip: IPvAnyAddress | None = None
    production: bool = False
    cache_mode: str = Field(default="use", pattern="^(use|bypass|refresh)$")
    cache_layers: list[str] | None = None


class IndexRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)
    pipeline: str | None = None
    settings: Any = None
    explicit_rebuild: bool = False


class CacheFeedbackRequest(BaseModel):
    trace_id: str = Field(pattern="^[0-9a-f]{32}$")
    owner_id: str = Field(min_length=1, max_length=200)
    helpful: bool


@app.on_event("startup")
def startup() -> None:
    load_catalog()
    initialize()
    start_worker()


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        QdrantClient(url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"), timeout=5).get_collections()
        return {"status": "ok", "qdrant": "ok", "corpus_id": corpus_config().id,
                "corpus_dir": str(corpus_config().books)}
    except Exception as exc:
        return {"status": "degraded", "qdrant": str(exc)}


@app.api_route("/langfuse-ollama/v1/{path:path}", methods=["GET", "POST"])
async def langfuse_ollama_proxy(path: str, request: Request) -> Response:
    """OpenAI-compatible Ollama gateway for Langfuse's local judge calls.

    Qwen3 can spend a short evaluator token budget in its reasoning channel.
    Langfuse's structured judge calls need the final tool output, so ask Ollama
    for no reasoning unless the caller explicitly provides a setting.
    """
    proxy_token = os.getenv("LANGFUSE_OLLAMA_PROXY_TOKEN", "")
    supplied = request.headers.get("authorization", "")
    if not proxy_token or not supplied.startswith("Bearer ") or not hmac.compare_digest(supplied[7:], proxy_token):
        raise HTTPException(status_code=401, detail="invalid local model gateway token")
    if path not in {"models", "chat/completions", "embeddings"}:
        raise HTTPException(status_code=404, detail="unsupported Ollama API path")
    if (path == "models" and request.method != "GET") or (path != "models" and request.method != "POST"):
        raise HTTPException(status_code=405, detail="method not allowed")

    body = await request.body()
    if path == "chat/completions":
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                payload.setdefault("reasoning_effort", "none")
                response_schema = payload.get("response_format", {})
                if isinstance(response_schema, dict) and response_schema.get("type") == "json_schema":
                    schema = response_schema.get("json_schema", {}).get("schema")
                    if schema:
                        # Ollama constrains JSON syntax but numeric bounds also need
                        # to be visible to the model, including Langfuse's model probe.
                        payload["messages"] = [
                            {"role": "system", "content": "Return JSON matching this schema exactly. Respect numeric minimum/maximum and required fields: " + json.dumps(schema)},
                            *payload.get("messages", []),
                        ]
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                response_format = payload.get("response_format")
                response_format_type = response_format.get("type") if isinstance(response_format, dict) else response_format
                logger.info("Local judge request model=%s response_format=%s tools=%d reasoning_effort=%s max_tokens=%s",
                            payload.get("model"), response_format_type,
                            len(payload.get("tools") or []), payload.get("reasoning_effort"), payload.get("max_tokens"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
    base_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    headers = {"Accept": request.headers.get("accept", "application/json")}
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    upstream = await asyncio.to_thread(
        requests.request,
        request.method,
        f"{base_url}/v1/{path}",
        params=request.query_params,
        headers=headers,
        data=body or None,
        timeout=(10, 300),
        stream=True,
    )
    response_headers = {}
    if upstream.headers.get("content-type"):
        response_headers["Content-Type"] = upstream.headers["content-type"]
    if "text/event-stream" in upstream.headers.get("content-type", ""):
        return StreamingResponse(upstream.iter_content(chunk_size=None), status_code=upstream.status_code,
                                 headers=response_headers, background=BackgroundTask(upstream.close))
    content = await asyncio.to_thread(lambda: upstream.content)
    if path == "chat/completions":
        try:
            result = json.loads(content)
            choice = (result.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            logger.info("Local judge response status=%d finish=%s tool_calls=%d content_chars=%d",
                        upstream.status_code, choice.get("finish_reason"), len(message.get("tool_calls") or []),
                        len(message.get("content") or ""))
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, AttributeError):
            logger.info("Local judge response status=%d non_json_body_chars=%d", upstream.status_code, len(content))
    upstream.close()
    return Response(content=content, status_code=upstream.status_code, headers=response_headers)


@app.post("/index")
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


def _prepare_ask(request: AskRequest) -> dict[str, Any]:
    """Check the rate limit and resolve the configuration, index and prompts for one question."""
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be blank")
    if (os.getenv("FRONTEND_RATE_LIMIT_ENABLED") == "true" and request.production and request.source == "frontend"
            and request.client_ip and not request.client_ip.is_loopback):
        retry_after = reserve_request(str(request.client_ip))
        if retry_after is not None:
            raise HTTPException(status_code=429, detail="Question limit reached. Please try again later.",
                                headers={"Retry-After": str(retry_after)})
    try:
        if "settings" in request.model_fields_set and not isinstance(request.settings, dict):
            raise ValueError("settings must be an object")
        answer_cache.normalize_layers(request.cache_layers)
        values = dict(request.settings or {})
        for legacy, key in (("mode", "retrieval_mode"), ("candidate_count", "candidate_count"),
                            ("top_k", "top_k"), ("passage_chars", "passage_chars")):
            value = getattr(request, legacy)
            if value is not None:
                if key in values:
                    raise ValueError(f"{legacy} and settings.{key} cannot both be present")
                values[key] = value
        resolved = resolve(request.pipeline, values, engine=request.engine,
                           prompt_label=request.prompt_label, collection=request.collection)
        collection = resolved.index["collection"]
        validate_index(collection, resolved.config)
        if resolved.engine == "fixed" and langfuse_enabled() and resolved.corpus_id == "millennium":
            try:
                bundle = (load_prompt_bundle(Langfuse(), versions=resolved.prompts) if resolved.status != "draft"
                          else load_prompt_bundle(Langfuse(), label=request.prompt_label))
            except Exception:
                logger.warning("Langfuse prompts are unavailable; using the selected corpus profile prompts", exc_info=True)
                bundle = {}
        else:
            bundle = {}
        prompts = prompt_manifests(bundle)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"config": resolved.config, "collection": collection, "bundle": bundle, "prompts": prompts,
            "pipeline_id": resolved.pipeline_id, "resolved": resolved}


def _answer_cache_identity(question: str, prepared: dict[str, Any]) -> dict[str, Any]:
    resolved = prepared["resolved"]
    return answer_cache.identity(
        project_id=langfuse_project(), corpus_id=resolved.corpus_id,
        pipeline_version=resolved.version, pipeline_fingerprint=resolved.fingerprint,
        pipeline_id=resolved.pipeline_id, corpus_checksum=resolved.corpus_checksum,
        profile_id=resolved.profile_id, profile_identity=resolved.profile_identity,
        prompt_identity=resolved.prompt_identity, collection=prepared["collection"],
        question=question, config=resolved.config.manifest(),
        agent_settings=(resolved.agent_settings.__dict__ if resolved.agent_settings else None))


def _run_ask(request: AskRequest, prepared: dict[str, Any], *, on_trace=None, on_token=None, on_status=None) -> dict[str, Any]:
    """Answer one question inside its Langfuse trace (the same trace whether or not the answer is streamed)."""
    pipeline_id, prompts = prepared["pipeline_id"], prepared["prompts"]
    session_id = request.session_id or "interactive-" + hashlib.sha256(" ".join(request.question.casefold().split()).encode()).hexdigest()[:24]
    environment = "interactive-ui" if request.source == "frontend" else "default"
    cache_layers = answer_cache.normalize_layers(request.cache_layers)
    cache_enabled = ("answer" in cache_layers and request.cache_mode != "bypass"
                     and langfuse_enabled())
    cache_scope = _answer_cache_identity(request.question, prepared) if cache_enabled else None
    cache_started = time.perf_counter()
    cached_result, cache_status, cache_source_trace_id = None, "bypassed", None
    if cache_enabled and request.cache_mode == "use":
        cached_result, cache_status, cache_source_trace_id = answer_cache.lookup(cache_scope)
    elif cache_enabled:
        cache_status = "refreshed"
    cache_lookup_seconds = time.perf_counter() - cache_started
    trace_metadata = {"pipeline_id": pipeline_id, "pipeline_version": prepared["resolved"].version,
                      "pipeline_derived": prepared["resolved"].derived,
                      "collection": prepared["collection"], "source": request.source,
                      "answer_cache_status": "hit" if cached_result is not None else cache_status}
    if cache_source_trace_id:
        trace_metadata["answer_cache_source_trace_id"] = cache_source_trace_id
    trace_metadata.update({key: prepared["resolved"].version_fields[key]
                           for key in ("corpus_id", "corpus_checksum", "profile_id", "profile_identity", "prompt_identity")
                           if key in prepared["resolved"].version_fields})
    agent_settings = prepared["resolved"].agent_settings
    if agent_settings:
        trace_metadata.update({"agent_provider": agent_settings.provider,
                               "agent_model": agent_settings.model,
                               "agent_automatic_scene_search": agent_settings.initial_scene_probe,
                               "agent_scene_candidate_count": agent_settings.scene_candidate_count,
                               "agent_premise_early_stop": agent_settings.premise_early_stop})
    trace_metadata.update({f"prompt_{name}": f"{asset['id']}@{asset['version']}:{asset['label']}"
                           for name, asset in prompts.items()})
    root_metadata = {"clientIp": str(request.client_ip)} if request.source == "frontend" and request.client_ip else None
    with trace_scope(session_id=session_id, user_id=request.user_id, environment=environment, metadata=trace_metadata,
                     tags=[f"pipeline:{pipeline_id}"]), observation("rag ask", as_type="span",
                                                                               input={"question": request.question},
                                                                               metadata=root_metadata) as obs:
        try:
            trace_id = get_client().get_current_trace_id() if langfuse_enabled() else None
        except Exception:
            trace_id = None
        if cached_result is not None and trace_id is None:
            cached_result = None
            cache_status = "unavailable"
        record_cache_lookup("answer", "hit" if cached_result is not None else cache_status,
                            cache_lookup_seconds, cache_source_trace_id,
                            input={"question": request.question},
                            output=({"answer": cached_result.get("answer"),
                                     "citations": cached_result.get("citations")}
                                    if cached_result is not None else None))
        if on_trace:
            on_trace(trace_id)
        if cached_result is not None:
            result = dict(cached_result)
            result.update({"question": request.question, "trace_id": trace_id, "session_id": session_id,
                           "pipeline_id": pipeline_id, "answer_cache_status": "hit", "cache_hit": True,
                           "cache_source_trace_id": cache_source_trace_id,
                           "cache_latency_seconds": round(cache_lookup_seconds, 4),
                           "latency_seconds": round(cache_lookup_seconds, 4),
                           "timings": {"answer_cache_lookup_seconds": round(cache_lookup_seconds, 4)}})
            answer_cache.mark_served(trace_id=trace_id, scope=cache_scope,
                                     owner_id=request.user_id, source_trace_id=cache_source_trace_id)
            if on_status:
                on_status("answering")
            if on_token:
                on_token(result.get("answer", ""))
            update_observation(obs, output={"answer": result.get("answer"), "citations": result.get("citations"),
                                            "answer_cache_status": "hit",
                                            "answer_cache_source_trace_id": cache_source_trace_id})
            return result
        layer_scope = intermediate_cache_scope(prepared["resolved"], prepared["collection"], langfuse_project())
        with use_intermediate_cache(request.cache_mode, cache_layers, layer_scope):
            result = run_resolved_pipeline(request.question, prepared["resolved"], prepared["collection"],
                                           prepared["bundle"], on_token=on_token, on_status=on_status)
        result["prompts"] = prompts
        result["session_id"] = session_id
        result["trace_id"] = trace_id
        result["pipeline_id"] = pipeline_id
        result["answer_cache_status"] = cache_status
        if cache_enabled and cache_status in {"miss", "refreshed"}:
            held = answer_cache.stage_candidate(cache_scope, result, trace_id=trace_id, owner_id=request.user_id)
            result["cache_candidate_held"] = held
            if trace_id and request.user_id and not held:
                result["answer_cache_status"] = "unavailable"
        update_observation(obs, output={"answer": result.get("answer"), "citations": result.get("citations"),
                                        "answer_cache_status": result.get("answer_cache_status")})
        return result


@app.post("/ask")
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


@app.post("/cache/feedback")
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


@app.post("/ask/stream")
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
    allowed = {"variant_label", "pipeline", "settings", "config", "dataset_version", "item_ids", "prompt_label",
               "correctness_evaluator", "cache_mode", "cache_layers"}
    unknown = set(custom) - allowed
    if unknown:
        raise HTTPException(status_code=400, detail=f"unsupported trigger fields: {', '.join(sorted(unknown))}")
    if not dataset_name:
        dataset_name = langfuse_dataset_name(os.getenv("DATASET_NAME"))
    else:
        dataset_name = langfuse_dataset_name(str(dataset_name))
    if "prompt_label" in custom and (not isinstance(custom["prompt_label"], str) or not custom["prompt_label"].strip()):
        raise HTTPException(status_code=400, detail="prompt_label must be a non-empty string")
    if "variant_label" in custom and (not isinstance(custom["variant_label"], str) or not custom["variant_label"].strip()):
        raise HTTPException(status_code=400, detail="variant_label must be a non-empty string")
    if "correctness_evaluator" in custom and custom["correctness_evaluator"] not in CORRECTNESS_SPECS:
        raise HTTPException(status_code=400, detail=f"correctness_evaluator must be one of {', '.join(sorted(CORRECTNESS_SPECS))}")
    if custom.get("cache_mode", "bypass") not in {"use", "bypass", "refresh"}:
        raise HTTPException(status_code=400, detail="cache_mode must be use, bypass, or refresh")
    try:
        answer_cache.normalize_layers(custom.get("cache_layers"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        if "config" in custom and "settings" in custom:
            raise ValueError("config and settings cannot both be present")
        settings = custom.pop("config", custom.get("settings", {}))
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")
        resolved = resolve(custom.get("pipeline"), settings, prompt_label=custom.get("prompt_label"))
        custom["pipeline"] = resolved.version
        custom["settings"] = resolved.overrides
        custom.setdefault("variant_label", resolved.version)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item_ids = custom.get("item_ids")
    if item_ids is not None and (not isinstance(item_ids, list) or not all(isinstance(value, str) for value in item_ids)):
        raise HTTPException(status_code=400, detail="item_ids must be an array of strings")
    try:
        if not langfuse_enabled():
            raise HTTPException(status_code=503, detail="Langfuse dataset experiments are disabled by configuration")
        # Langfuse's tracer/score queues are process-wide singletons keyed by
        # credentials. Do not shut this client down here: the queued worker uses
        # the same resource manager to export the experiment's traces and scores.
        client = Langfuse()
        dataset = client.get_dataset(dataset_name)
        if dataset_id and dataset.id != dataset_id:
            raise ValueError("trigger dataset_id does not match dataset_name")
        projects = getattr(client.api.projects.get(), "data", []) or []
        configured_project = next((project for project in projects
                                   if project.name == langfuse_project() and project.id == dataset.project_id), None)
        if configured_project is None:
            raise ValueError(f"dataset does not belong to configured Langfuse project {langfuse_project()!r}")
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
            "pipeline_version": (result.get("pipeline_version") or payload.get("pipeline")) if result else payload.get("pipeline"),
            "pipeline_derived": (result["pipeline_derived"] if "pipeline_derived" in result else bool(payload.get("settings")))
                                 if result else bool(payload.get("settings")),
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
