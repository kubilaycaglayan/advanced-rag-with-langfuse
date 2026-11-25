"""answering / interactive responsibilities."""
from __future__ import annotations

from app.answering.cache_identity import answer_cache_identity

from app.api.schemas import AskRequest
from app.cache import answers as answer_cache
from app.cache.intermediate import scope_for as intermediate_cache_scope
from app.cache.intermediate import use_cache as use_intermediate_cache
from app.corpus_config import langfuse_project
from app.corpus_profiles import langfuse_enabled
from app.corpus_profiles import langfuse_tracing_required
from app.observability import observation
from app.observability import record_cache_lookup
from app.observability import trace_scope
from app.observability import update as update_observation
from app.answering.execution import execute_question as run_resolved_pipeline
from fastapi import HTTPException
from langfuse import get_client
from typing import Any
import hashlib
import time


def _run_ask(request: AskRequest, prepared: dict[str, Any], *, on_trace=None, on_token=None, on_status=None) -> dict[str, Any]:
    """Answer one question inside its Langfuse trace (the same trace whether or not the answer is streamed)."""
    pipeline_id = prepared["pipeline_id"]
    question_key = hashlib.sha256(" ".join(request.question.casefold().split()).encode()).hexdigest()[:24]
    session_id = ("question-" + question_key if langfuse_tracing_required()
                  else request.session_id or "interactive-" + question_key)
    environment = "interactive-ui" if request.source == "frontend" else "default"
    cache_layers = answer_cache.normalize_layers(request.cache_layers)
    cache_enabled = ("answer" in cache_layers and request.cache_mode != "bypass"
                     and langfuse_enabled())
    cache_scope = answer_cache_identity(request.question, prepared["resolved"], prepared["collection"]) if cache_enabled else None
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
    root_metadata = {"clientIp": str(request.client_ip)} if request.source == "frontend" and request.client_ip else None
    with trace_scope(session_id=session_id, user_id=request.user_id, environment=environment, metadata=trace_metadata,
                     tags=[f"pipeline:{pipeline_id}"]), observation("rag ask", as_type="span",
                                                                               input={"question": request.question},
                                                                               metadata=root_metadata) as obs:
        try:
            trace_id = get_client().get_current_trace_id() if langfuse_enabled() else None
        except Exception:
            trace_id = None
        if langfuse_tracing_required() and trace_id is None:
            raise HTTPException(status_code=503, detail="Langfuse could not start a trace for this question")
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
            result = run_resolved_pipeline(request.question, prepared["resolved"], prepared["collection"], on_token=on_token, on_status=on_status)
        result["prompts"] = {}
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

