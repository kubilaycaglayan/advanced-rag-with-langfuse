"""experiments / execution responsibilities."""
from __future__ import annotations

from app.answering.cache_identity import answer_cache_identity
from app.cache import answers as answer_cache
from app.cache.intermediate import scope_for as intermediate_cache_scope
from app.cache.intermediate import use_cache as use_intermediate_cache
from app.corpus_config import corpus_config
from app.corpus_config import corpus_data_dir
from app.corpus_config import langfuse_project
from app.evaluation.judges import citation_support
from app.evaluation.judges import correctness
from app.evaluation.judges import is_explicit_abstention
from app.evaluation.specs import CORRECTNESS_SPECS
from app.evaluation.specs import DEFAULT_CORRECTNESS
from app.evaluation.specs import evaluator_manifest
from app.experiments.datasets import _dataset_for
from app.experiments.datasets import _item_question
from app.experiments.datasets import _item_session
from app.experiments.metadata import _fingerprints
from app.experiments.metadata import _jsonable
from app.experiments.metadata import pack_experiment_metadata
from app.experiments.store import get_execution
from app.experiments.store import update_execution
from app.experiments.telemetry import _client
from app.experiments.telemetry import _flush_client
from app.experiments.telemetry import _verify_trace_upload
from app.identity import dataset_snapshot
from app.indexing.passages import build_index
from app.observability import observation
from app.observability import pack_scope_attributes
from app.observability import record_cache_lookup
from app.observability import use_client
from app.pipelines.resolver import resolve
from app.answering.execution import execute_question as run_resolved_pipeline
from app.prompt_assets import ManagedJudgePrompt
from app.prompt_assets import load_managed_evaluators
from functools import partial
from langfuse import Langfuse
from langfuse import propagate_attributes
from typing import Any
import json
import re
import threading
import time


_active_lock = threading.Lock()


def _cached_output_with_timing(payload: dict[str, Any], source_trace_id: str | None,
                               lookup_seconds: float) -> dict[str, Any]:
    elapsed = round(lookup_seconds, 4)
    output = dict(payload)
    output.update({"answer_cache_status": "hit", "cache_hit": True,
                   "cache_source_trace_id": source_trace_id,
                   "cache_latency_seconds": elapsed, "latency_seconds": elapsed,
                   "timings": {"answer_cache_lookup_seconds": elapsed}})
    return output


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def execute_execution(execution_id: str) -> dict[str, Any]:
    row = get_execution(execution_id)
    if row is None:
        raise KeyError(execution_id)
    payload = json.loads(row["payload_json"])
    execution_dir = corpus_data_dir() / "executions" / execution_id
    execution_dir.mkdir(parents=True, exist_ok=True)
    (execution_dir / "request.json").write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    update_execution(execution_id, status="running", started=True)
    client: Langfuse | None = None
    client_cleanup_attempted = False
    try:
        # Experiments always compute answers, but refresh reusable intermediate
        # results and correctness-approved answers by default. Explicit bypass
        # remains available for fully isolated runs.
        cache_mode = payload.get("cache_mode", "refresh")
        if cache_mode not in {"use", "bypass", "refresh"}:
            raise ValueError("cache_mode must be use, bypass, or refresh")
        cache_layers = answer_cache.normalize_layers(payload.get("cache_layers"))
        cache_enabled = cache_mode != "bypass" and "answer" in cache_layers
        resolved = resolve(payload.get("pipeline"), payload.get("settings"))
        config = resolved.config
        client = _client()
        dataset, version = _dataset_for(payload, client)
        correctness_name = payload.get("correctness_evaluator") or DEFAULT_CORRECTNESS
        if correctness_name not in CORRECTNESS_SPECS:
            raise ValueError(f"correctness_evaluator must be one of {sorted(CORRECTNESS_SPECS)}")
        managed_evaluators = load_managed_evaluators()
        all_items = list(dataset.items)
        snapshot = dataset_snapshot([{"id": item.id, "input": item.input, "expected_output": item.expected_output, "metadata": item.metadata} for item in all_items],
                                    dataset_id=dataset.id, dataset_name=dataset.name, version=version)
        requested_ids = payload.get("item_ids")
        if requested_ids:
            missing = sorted(set(requested_ids) - {item.id for item in all_items})
            if missing:
                raise ValueError(f"item_ids are not present in pinned dataset version: {missing}")
            items = [item for item in all_items if item.id in set(requested_ids)]
        else:
            items = all_items
        if not items:
            raise ValueError("dataset snapshot contains no selected items")

        index = build_index(config)
        collection = index["collection"]
        if collection != resolved.index["collection"]:
            raise ValueError(f"{resolved.version}: built collection differs from pinned collection")
        pipeline_manifest, evaluator_manifest, corpus_checksum = _fingerprints(config, managed_evaluators, correctness_name, resolved)
        # Include the selected frozen snapshot and exact corpus content in each execution manifest.
        variant = re.sub(r"[^A-Za-z0-9._-]+", "-", payload.get("variant_label", resolved.version)).strip("-")[:50] or "run"
        run_name = f"{variant}-{execution_id}"
        corpus_title = corpus_config().title
        (corpus_data_dir() / "executions" / execution_id).mkdir(parents=True, exist_ok=True)
        manifest = {"execution_id": execution_id, "variant_label": variant, "dataset_snapshot": snapshot,
                    "pipeline": pipeline_manifest, "evaluator": evaluator_manifest,
                    "prompts": {},
                    "index": index, "config": config.manifest(), "run_name": run_name,
                    "selected_item_ids": [item.id for item in items],
                    "answer_cache": {"mode": cache_mode, "layers": list(cache_layers)},
                    "retry_of_execution_id": payload.get("retry_of_execution_id")}
        manifest_path = execution_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")

        cache_scopes: dict[str, dict[str, Any]] = {}
        cache_statuses: dict[str, str] = {}

        def task(*, item: Any, **kwargs: Any) -> dict[str, Any]:
            question = _item_question(item)
            session = _item_session(dataset.name, item)
            cache_scope = answer_cache_identity(str(question), resolved, collection) if cache_enabled else None
            if cache_scope is not None:
                cache_scopes[item.id] = cache_scope
            cached_output, cache_status, cache_source = None, "bypassed", None
            if cache_scope is not None and cache_mode == "use":
                cache_lookup_started = time.perf_counter()
                cached_output, cache_status, cache_source = answer_cache.lookup(cache_scope)
                cache_lookup_seconds = time.perf_counter() - cache_lookup_started
            elif cache_scope is not None:
                cache_status = "refreshed"
                cache_lookup_seconds = 0.0
            else:
                cache_lookup_seconds = 0.0
            cache_statuses[item.id] = "hit" if cached_output is not None else cache_status
            try:
                with use_client(client):
                    trace_metadata = {"execution_id": execution_id, "dataset_id": dataset.id,
                            "dataset_version": version.isoformat(), "dataset_item_id": item.id,
                            "pipeline_id": pipeline_manifest["pipeline_id"],
                            "pipeline_version": resolved.version, "pipeline_derived": resolved.derived,
                            "evaluator_id": evaluator_manifest["evaluator_id"], "experiment_run": run_name,
                            "answer_cache_status": cache_statuses[item.id]}
                    if cache_source:
                        trace_metadata["answer_cache_source_trace_id"] = cache_source
                    if resolved.agent_settings:
                        trace_metadata["agent_provider"] = resolved.agent_settings.provider
                        trace_metadata["agent_model"] = resolved.agent_settings.model
                        trace_metadata["agent_reasoning_effort"] = resolved.agent_settings.reasoning_effort
                        trace_metadata["agent_think"] = resolved.agent_settings.think
                        trace_metadata["agent_context_length"] = resolved.agent_settings.context_length
                        trace_metadata["agent_automatic_scene_search"] = resolved.agent_settings.initial_scene_probe
                        trace_metadata["agent_scene_candidate_count"] = resolved.agent_settings.scene_candidate_count
                        trace_metadata["agent_premise_early_stop"] = resolved.agent_settings.premise_early_stop
                    trace_metadata.update({f"managed_eval_{name}": f"{asset['id']}@{asset['version']}"
                                           for name, asset in managed_evaluators.items()})
                    scope_attributes = pack_scope_attributes({
                        "session_id": session,
                        "metadata": trace_metadata,
                        "tags": [f"pipeline:{resolved.pipeline_id}"],
                    })
                    with propagate_attributes(**scope_attributes):
                        # Langfuse limits propagated metadata values to 200 characters.
                        # Observation metadata has no such propagation limit; a JSON
                        # string also stays a single OpenTelemetry attribute.
                        with observation("experiment configuration", metadata={"extended_json": packed_experiment_metadata}):
                            pass
                        record_cache_lookup("answer", cache_statuses[item.id],
                                            cache_lookup_seconds, cache_source,
                                            input={"question": question}, output=cached_output)
                        if cached_output is not None:
                            return _cached_output_with_timing(cached_output, cache_source,
                                                              cache_lookup_seconds)
                        layer_scope = intermediate_cache_scope(resolved, collection, langfuse_project())
                        with use_intermediate_cache(cache_mode, cache_layers, layer_scope):
                            output = run_resolved_pipeline(str(question), resolved, collection)
                        output["answer_cache_status"] = cache_status
                        return output
            except Exception as exc:
                return {"error": f"{type(exc).__name__}: {exc}", "answer": "", "citations": [],
                        "candidates": [], "reranked": [], "evidence": ""}

        experiment_metadata = {"execution_id": execution_id, "pipeline_id": pipeline_manifest["pipeline_id"],
                      "pipeline_version": resolved.version, "pipeline_derived": resolved.derived,
                      "evaluator_id": evaluator_manifest["evaluator_id"], "dataset_version": version.isoformat(),
                      "variant_label": variant, "snapshot_sha256": snapshot["sha256"],
                      "correctness_evaluator": correctness_name,
                      "answer_cache_mode": cache_mode, "answer_cache_layers": list(cache_layers)}
        if resolved.agent_settings:
            experiment_metadata["agent_provider"] = resolved.agent_settings.provider
            experiment_metadata["agent_model"] = resolved.agent_settings.model
            experiment_metadata["agent_reasoning_effort"] = resolved.agent_settings.reasoning_effort
            experiment_metadata["agent_think"] = resolved.agent_settings.think
            experiment_metadata["agent_context_length"] = resolved.agent_settings.context_length
            experiment_metadata["agent_automatic_scene_search"] = resolved.agent_settings.initial_scene_probe
            experiment_metadata["agent_scene_candidate_count"] = resolved.agent_settings.scene_candidate_count
            experiment_metadata["agent_premise_early_stop"] = resolved.agent_settings.premise_early_stop
            experiment_metadata["agent_endpoint"] = ("responses" if resolved.agent_settings.provider == "openai"
                                                      and resolved.agent_settings.reasoning_effort != "none"
                                                      else "chat_completions" if resolved.agent_settings.provider == "openai"
                                                      else "ollama")
        experiment_metadata.update({f"config_{key}": value if isinstance(value, str) else json.dumps(value, sort_keys=True)
                                    for key, value in config.manifest().items() if key != "prompt_hashes"})
        experiment_metadata.update({f"managed_eval_{name}": f"{asset['id']}@{asset['version']}"
                                    for name, asset in managed_evaluators.items()})
        experiment_metadata, packed_experiment_metadata = pack_experiment_metadata(experiment_metadata)
        # The SDK runner flushes internally before returning. Keep that flush in
        # the app's bounded cleanup phase so a stuck SDK queue cannot strand the
        # durable worker before it writes the local result artifact.
        sdk_flush = client.flush
        client.flush = lambda: None  # type: ignore[method-assign]
        try:
            result = client.run_experiment(name=f"{corpus_title} RAG: {variant}", run_name=run_name,
                description=f"Execution {execution_id}; pipeline {pipeline_manifest['pipeline_id']}; dataset version {version.isoformat()}",
                data=items, task=task,
                evaluators=[partial(correctness, evaluator_id=evaluator_manifest["evaluator_id"], langfuse_client=client,
                                    spec=CORRECTNESS_SPECS[correctness_name],
                                    managed_prompt=ManagedJudgePrompt(managed_evaluators[correctness_name]),
                                    evaluator_version=managed_evaluators[correctness_name]["version"],
                                    managed_evaluator_id=managed_evaluators[correctness_name]["id"]),
                            partial(citation_support, evaluator_id=evaluator_manifest["evaluator_id"], langfuse_client=client,
                                    managed_prompt=ManagedJudgePrompt(managed_evaluators["citation_support_v1"]),
                                    evaluator_version=managed_evaluators["citation_support_v1"]["version"],
                                    managed_evaluator_id=managed_evaluators["citation_support_v1"]["id"])],
                max_concurrency=1,
                metadata=experiment_metadata, _dataset_version=version)
        finally:
            client.flush = sdk_flush  # type: ignore[method-assign]
        item_results = []
        errors = 0
        score_values: dict[str, list[float]] = {correctness_name: [], "citation_support_v1": []}
        for item_result in result.item_results:
            out = item_result.output
            failed = not isinstance(out, dict) or bool(out.get("error"))
            errors += int(failed)
            scores = []
            correctness_score = None
            for score in item_result.evaluations:
                score_data = _jsonable(score)
                scores.append(score_data)
                name = _get(score, "name")
                value = _get(score, "value")
                if name == correctness_name and isinstance(value, (float, int)) and not isinstance(value, bool):
                    correctness_score = float(value)
                if name in score_values and isinstance(value, (float, int)) and not isinstance(value, bool):
                    score_values[name].append(float(value))
            cache_write = False
            scope = cache_scopes.get(item_result.item.id)
            if (cache_enabled and scope is not None and isinstance(out, dict)
                    and correctness_score is not None and correctness_score >= 0.90):
                cache_write = answer_cache.store_approved(
                    scope, out, trace_id=item_result.trace_id, approval_source="correctness",
                    correctness_score=correctness_score)
            if isinstance(out, dict):
                out["answer_cache_status"] = cache_statuses.get(item_result.item.id, "bypassed")
                out["answer_cache_approved"] = cache_write
            previous_cache_status = cache_statuses.get(item_result.item.id, "bypassed")
            cache_statuses[item_result.item.id] = (
                "approved" if cache_write and previous_cache_status != "hit" else previous_cache_status
            )
            item_results.append({"item_id": item_result.item.id, "session_id": _item_session(dataset.name, item_result.item),
                                 "trace_id": item_result.trace_id, "output": _jsonable(out), "evaluations": scores,
                                 "failed": failed, "answer_cache_status": cache_statuses[item_result.item.id],
                                 "correctness_score": correctness_score})
        means = {name: (sum(values) / len(values) if values else None) for name, values in score_values.items()}
        summaries = {name: {"mean": means[name], "valid_count": len(values)} for name, values in score_values.items()}
        agent_usage_rows = [row["output"].get("agent_usage") for row in item_results
                            if isinstance(row.get("output"), dict)
                            and isinstance(row["output"].get("agent_usage"), dict)]
        agent_usage = {
            "provider": resolved.agent_settings.provider if resolved.agent_settings else None,
            "model": resolved.agent_settings.model if resolved.agent_settings else None,
            "reasoning_effort": resolved.agent_settings.reasoning_effort if resolved.agent_settings else None,
            "endpoint": ("responses" if resolved.agent_settings and resolved.agent_settings.provider == "openai"
                         and resolved.agent_settings.reasoning_effort != "none"
                         else "chat_completions" if resolved.agent_settings and resolved.agent_settings.provider == "openai"
                         else "ollama" if resolved.agent_settings else None),
            "question_count": len(agent_usage_rows),
            "calls": sum(int(usage.get("calls") or 0) for usage in agent_usage_rows),
            "prompt_tokens": sum(int(usage.get("prompt_tokens") or 0) for usage in agent_usage_rows),
            "completion_tokens": sum(int(usage.get("completion_tokens") or 0) for usage in agent_usage_rows),
            "total_tokens": sum(int(usage.get("total_tokens") or 0) for usage in agent_usage_rows),
            "cached_prompt_tokens": sum(int(usage.get("cached_prompt_tokens") or 0) for usage in agent_usage_rows),
            "reasoning_tokens": sum(int(usage.get("reasoning_tokens") or 0) for usage in agent_usage_rows),
            "estimated_cost_usd": round(sum(float(usage.get("estimated_cost_usd") or 0)
                                             for usage in agent_usage_rows), 10),
        }
        codex_scores = [score for row in item_results for score in row["evaluations"]
                        if score.get("name") == "answer_correctness_codex_v1"
                        and isinstance((score.get("metadata") or {}).get("codex_usage"), dict)]
        codex_usage = {key: sum(score["metadata"]["codex_usage"].get(key, 0) for score in codex_scores)
                       for key in ("input_tokens", "cached_input_tokens", "output_tokens")}
        codex_usage["question_count"] = len(codex_scores)
        codex_usage["estimated_per_100_questions"] = {
            key: round(value * 100 / len(codex_scores)) if codex_scores else None
            for key, value in codex_usage.items() if key != "question_count"}
        telemetry_failures = []
        if not result.dataset_run_id:
            telemetry_failures.append("Langfuse did not return a dataset run ID")
        if not result.dataset_run_url:
            telemetry_failures.append("Langfuse did not return a dataset run URL")
        cleanup = _flush_client(client)
        client_cleanup_attempted = True
        if cleanup.get("error"):
            telemetry_failures.append(cleanup["error"])
        for item_result in item_results:
            trace_error = _verify_trace_upload(client, item_result["trace_id"])
            if trace_error:
                telemetry_failures.append(f"item {item_result['item_id']}: {trace_error}")
        payload_result = {"execution_id": execution_id, "status": "partial" if errors or len(item_results) != len(items) else "completed",
                          "retry_of_execution_id": payload.get("retry_of_execution_id"),
                          "dataset_id": dataset.id, "dataset_version": version.isoformat(), "dataset_snapshot_sha256": snapshot["sha256"],
                          "dataset_item_count": len(items), "completed_item_count": len(item_results), "failed_item_count": errors,
                          "evaluation_failure_count": sum(1 for row in item_results for score in row["evaluations"] if str(score.get("name", "")).endswith("_error")),
                          "scores": summaries, "codex_usage": codex_usage, "agent_usage": agent_usage,
                          "abstention_count": sum(1 for row in item_results
                              if isinstance(row["output"], dict) and is_explicit_abstention(str(row["output"].get("answer", "")))),
                          "telemetry_failure_count": len(telemetry_failures), "telemetry_errors": telemetry_failures,
                          "pipeline_id": pipeline_manifest["pipeline_id"], "pipeline_version": resolved.version,
                          "pipeline_derived": resolved.derived, "evaluator_id": evaluator_manifest["evaluator_id"],
                          "managed_evaluators": managed_evaluators, "prompts": {},
                          "experiment_id": result.experiment_id, "dataset_run_id": result.dataset_run_id,
                          "dataset_run_url": result.dataset_run_url, "item_results": item_results}
        artifact_path = execution_dir / "results.json"
        artifact_path.write_text(json.dumps(payload_result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        if (payload_result["evaluation_failure_count"] or payload_result["telemetry_failure_count"]) and payload_result["status"] == "completed":
            payload_result["status"] = "partial"
            artifact_path.write_text(json.dumps(payload_result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        update_execution(execution_id, status=payload_result["status"], result=payload_result, finished=True)
        return payload_result
    except Exception as exc:
        if client is not None and not client_cleanup_attempted:
            _flush_client(client)
            client_cleanup_attempted = True
        failure = {"execution_id": execution_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        if "resolved" in locals():
            failure.update(resolved.version_fields)
        (execution_dir / "results.json").write_text(json.dumps(failure, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        update_execution(execution_id, status="failed", result=failure, error=failure["error"], finished=True)
        return failure
    finally:
        if client is not None and not client_cleanup_attempted:
            _flush_client(client)
