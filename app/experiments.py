"""Pinned hosted-dataset experiment execution and durable single-worker queue."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import threading
import time
import uuid
from functools import partial
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langfuse import Langfuse, propagate_attributes
from opentelemetry import trace as otel_trace_api

try:
    from . import answer_cache
    from .corpus_config import corpus_config, corpus_data_dir, corpus_id, langfuse_project, langfuse_dataset_name
    from .corpus_profiles import profile_identity, prompt_identity
    from .evaluation import citation_support, correctness, is_explicit_abstention
    from .experiment_store import (enqueue, get_execution, initialize, mark_interrupted,
                                   pending_jobs, update_execution)
    from .identity import (canonical_json, dataset_snapshot, evaluator_identity,
                           pipeline_identity, question_label, question_session_id, source_manifest)
    from .indexer import build_index, corpus_paths
    from .intermediate_cache import scope_for as intermediate_cache_scope, use_cache as use_intermediate_cache
    from .evaluator_specs import CORRECTNESS_SPECS, DEFAULT_CORRECTNESS, JUDGE_MODELS, evaluator_manifest
    from .observability import record_cache_lookup, use_client
    from .pipeline import PROMPT_HASHES, run_pipeline
    from .prompt_assets import ManagedJudgePrompt, load_managed_evaluators, load_prompt_bundle, prompt_manifests
    from .resolved_config import ResolvedPipelineConfig, resolve_ollama_model, resolve_pipeline_model_identities
    from .pipeline_resolver import ResolvedRun, resolve
    from .pipeline_catalog import load_catalog
    from .pipeline_runner import run as run_resolved_pipeline
except ImportError:
    import answer_cache
    from corpus_config import corpus_config, corpus_data_dir, corpus_id, langfuse_project, langfuse_dataset_name
    from corpus_profiles import profile_identity, prompt_identity
    from evaluation import citation_support, correctness, is_explicit_abstention
    from experiment_store import (enqueue, get_execution, initialize, mark_interrupted,
                                  pending_jobs, update_execution)
    from identity import (canonical_json, dataset_snapshot, evaluator_identity,
                         pipeline_identity, question_label, question_session_id, source_manifest)
    from indexer import build_index, corpus_paths
    from intermediate_cache import scope_for as intermediate_cache_scope, use_cache as use_intermediate_cache
    from evaluator_specs import CORRECTNESS_SPECS, DEFAULT_CORRECTNESS, JUDGE_MODELS, evaluator_manifest
    from observability import record_cache_lookup, use_client
    from pipeline import PROMPT_HASHES, run_pipeline
    from prompt_assets import ManagedJudgePrompt, load_managed_evaluators, load_prompt_bundle, prompt_manifests
    from resolved_config import ResolvedPipelineConfig, resolve_ollama_model, resolve_pipeline_model_identities
    from pipeline_resolver import ResolvedRun, resolve
    from pipeline_catalog import load_catalog
    from pipeline_runner import run as run_resolved_pipeline

_jobs: queue.Queue[str] = queue.Queue()
_worker: threading.Thread | None = None
_active_lock = threading.Lock()


def _item_question(item: Any) -> Any:
    return item.input.get("question") if isinstance(item.input, dict) else item.input


def _item_session(dataset_name: str, item: Any) -> str:
    return question_session_id(dataset_name, item.id, item.metadata, _item_question(item))


def _answer_cache_identity(question: str, resolved: ResolvedRun, collection: str) -> dict[str, Any]:
    return answer_cache.identity(
        project_id=langfuse_project(), corpus_id=resolved.corpus_id,
        pipeline_version=resolved.version, pipeline_fingerprint=resolved.fingerprint,
        pipeline_id=resolved.pipeline_id, corpus_checksum=resolved.corpus_checksum,
        profile_id=resolved.profile_id, profile_identity=resolved.profile_identity,
        prompt_identity=resolved.prompt_identity, collection=collection, question=str(question),
        config=resolved.config.manifest(),
        agent_settings=(resolved.agent_settings.__dict__ if resolved.agent_settings else None))


def _cached_output_with_timing(payload: dict[str, Any], source_trace_id: str | None,
                               lookup_seconds: float) -> dict[str, Any]:
    elapsed = round(lookup_seconds, 4)
    output = dict(payload)
    output.update({"answer_cache_status": "hit", "cache_hit": True,
                   "cache_source_trace_id": source_trace_id,
                   "cache_latency_seconds": elapsed, "latency_seconds": elapsed,
                   "timings": {"answer_cache_lookup_seconds": elapsed}})
    return output


class ExperimentLangfuse(Langfuse):
    """Scope the SDK's entire item tree, including root and judges, to one question.

    The question tag also reaches the item's scores: score charts filter on their trace's tags.

    This adapter targets the pinned Langfuse 4.17 SDK. Its item hook is covered by
    a regression test and the live observation/session acceptance check.
    """
    async def _process_experiment_item(self, item: Any, *args: Any, **kwargs: Any) -> Any:
        session = _item_session(item.dataset_name, item)
        tags = [f"question:{question_label(item.dataset_name, item.id, item.metadata)}"]
        with propagate_attributes(session_id=session, tags=tags, environment="sdk-experiment"):
            return await super()._process_experiment_item(item, *args, **kwargs)


def _client() -> Langfuse:
    return ExperimentLangfuse(environment="sdk-experiment")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dict__"):
        return {k: _jsonable(v) for k, v in vars(value).items() if not k.startswith("_")}
    return value


def _ollama_identity(model: str) -> dict[str, Any]:
    try:
        return resolve_ollama_model(model, os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")).__dict__
    except Exception:
        return {"name": model, "digest": None}


def _evaluator_prompt_manifest(prompt_versions: dict[str, Any]) -> dict[str, Any]:
    """Return immutable evaluator prompt identities, excluding movable aliases."""
    return {name: {key: value[key] for key in ("id", "version")}
            for name, value in prompt_versions.items() if name.startswith("rag-eval-")}


def _fingerprints(config: ResolvedPipelineConfig, version: datetime, prompt_versions: dict[str, Any],
                  managed_evaluators: dict[str, Any], correctness_name: str = DEFAULT_CORRECTNESS,
                  resolved: ResolvedRun | None = None) -> tuple[dict[str, Any], dict[str, Any], str]:
    repo_root = Path(__file__).resolve().parents[1]
    sources = source_manifest(str(repo_root))
    corpus_files = corpus_paths()
    corpus_manifest = [{"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in corpus_files]
    corpus_checksum = hashlib.sha256(canonical_json(corpus_manifest).encode()).hexdigest()
    enriched = config.manifest()
    enriched["prompt_hashes"] = {name: hashlib.sha256(canonical_json(asset).encode()).hexdigest()
                                  for name, asset in prompt_versions.items()}
    enriched["generation_model"] = (config.generation_model.__dict__ if resolved else _ollama_identity(config.generation_model.name))
    enriched["embedding_model"] = {"name": config.embedding_model.name, "revision": config.embedding_model.revision}
    enriched["reranker_model"] = {"name": config.reranker_model.name, "revision": config.reranker_model.revision}
    enriched["corpus_checksum"] = corpus_checksum
    enriched["corpus_id"] = (resolved.corpus_id if resolved else corpus_id())
    enriched["profile_identity"] = profile_identity()
    enriched["prompt_identity"] = prompt_identity()
    pipeline = ({**resolved.version_fields, "fingerprint": resolved.fingerprint,
                 "git_revision": sources["git_revision"], "dirty": sources["dirty"],
                 "source_fingerprint": sources["source_fingerprint"], "resolved_config": enriched,
                 "corpus_checksum": corpus_checksum} if resolved else
                pipeline_identity(git_revision=sources["git_revision"], dirty=sources["dirty"],
                                  source_fingerprint=sources["source_fingerprint"], resolved_config=enriched,
                                  corpus_checksum=corpus_checksum))
    pipeline["source_manifest"] = sources
    pipeline["corpus_manifest"] = corpus_manifest
    if resolved and resolved.agent_settings:
        pipeline["agent_settings"] = resolved.agent_settings.__dict__
    evaluator_model_name = os.getenv("EVALUATOR_MODEL", "qwen3:8b")
    evaluator_endpoint = os.getenv("EVALUATOR_OLLAMA_URL") or os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        evaluator_model = resolve_ollama_model(evaluator_model_name, evaluator_endpoint).__dict__
    except Exception:
        evaluator_model = {"name": evaluator_model_name, "digest": None}
    if correctness_name in JUDGE_MODELS:
        executor, judge_model, _ = JUDGE_MODELS[correctness_name]
        evaluator_model = {"name": judge_model, "digest": None, "executor": executor}
    evaluator_prompt = canonical_json({"specs": evaluator_manifest(), "managed": managed_evaluators,
                                       # Labels are aliases. The immutable prompt ID/version defines the
                                       # evaluator behavior, so moving the same version under another
                                       # label must not create a different evaluator identity.
                                       "prompts": _evaluator_prompt_manifest(prompt_versions)})
    evaluator_code = hashlib.sha256((Path(__file__).resolve().parent / "evaluation.py").read_bytes()).hexdigest()
    evaluator = evaluator_identity(model=evaluator_model, settings={"temperature": 0, "stream": False, "format": "json"},
                                   rubric=evaluator_prompt, prompt=evaluator_prompt, code_version=f"evaluation.py:{evaluator_code}")
    return pipeline, {"evaluator_id": evaluator, "managed_evaluators": managed_evaluators,
                      "model": evaluator_model, "specs": evaluator_manifest(),
                      "settings": {"temperature": 0, "stream": False, "format": "json"},
                      "code_fingerprint": evaluator_code}, corpus_checksum


def _flush_client(client: Langfuse, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    """Flush SDK queues without shutting down the process-wide shared manager."""
    result: dict[str, Any] = {"completed": False, "error": None}

    def cleanup() -> None:
        resources = getattr(client, "_resources", None)
        if resources is None:
            result["error"] = "Langfuse client has no initialized resources"
            result["completed"] = True
            return
        deadline = time.monotonic() + timeout_seconds
        try:
            provider = getattr(resources, "tracer_provider", None)
            if provider is not None and not isinstance(provider, otel_trace_api.ProxyTracerProvider):
                provider_timeout = max(1000, int(min(timeout_seconds, 10.0) * 1000))
                if not provider.force_flush(timeout_millis=provider_timeout):
                    result["error"] = "Langfuse trace exporter flush timed out"
                    result["completed"] = True
                    return
        except Exception as exc:
            result["error"] = f"Langfuse trace exporter flush failed: {type(exc).__name__}: {exc}"
            result["completed"] = True
            return
        for queue_name in ("_score_ingestion_queue", "_media_upload_queue"):
            queue = getattr(resources, queue_name, None)
            while queue is not None and queue.unfinished_tasks and time.monotonic() < deadline:
                time.sleep(0.05)
            if queue is not None and queue.unfinished_tasks:
                result["error"] = f"Langfuse {queue_name.removeprefix('_').removesuffix('_queue')} queue has {queue.unfinished_tasks} pending task(s)"
                result["completed"] = True
                return
        result["completed"] = True

    thread = threading.Thread(target=cleanup, name="langfuse-bounded-cleanup", daemon=True)
    thread.start()
    thread.join(timeout_seconds + 2)
    if thread.is_alive():
        result["error"] = f"Langfuse flush exceeded {timeout_seconds:g}s"
    return result


def _verify_trace_upload(client: Langfuse, trace_id: str | None, *, attempts: int = 5) -> str | None:
    """Confirm the item task reached Langfuse; exporter flush alone can hide HTTP failures."""
    if not trace_id:
        return "Langfuse experiment item did not return a trace ID"
    last_error = "Langfuse observations API did not return experiment-item-task"
    for attempt in range(attempts):
        try:
            page = client.api.observations.get_many(trace_id=trace_id, limit=100)
            if any(observation.name == "experiment-item-task" for observation in page.data):
                return None
        except Exception as exc:
            last_error = f"Langfuse observations lookup failed: {type(exc).__name__}: {exc}"
        if attempt + 1 < attempts:
            time.sleep(0.5)
    return f"trace {trace_id}: {last_error}"


def _dataset_for(payload: dict[str, Any], client: Langfuse) -> tuple[Any, datetime]:
    name = langfuse_dataset_name(payload.get("dataset_name") or os.getenv("DATASET_NAME"))
    supplied_version = payload.get("dataset_version")
    version = datetime.fromisoformat(supplied_version.replace("Z", "+00:00")) if supplied_version else None
    if version is not None and version.utcoffset() is None:
        raise ValueError("dataset_version must be an ISO-8601 timezone-aware timestamp")
    if version is None:
        latest = client.get_dataset(name)
        # SDK 4.17 does not expose the resolved "latest" item snapshot timestamp.
        # Pin the dataset's server update timestamp and refetch through its historical
        # version adapter before materializing any experiment items.
        timestamps = [latest.updated_at]
        timestamps.extend(item.updated_at for item in latest.items if getattr(item, "updated_at", None) is not None)
        version = max(timestamps)
        if version.utcoffset() is None:
            version = version.replace(tzinfo=timezone.utc)
    dataset = client.get_dataset(name, version=version)
    if payload.get("dataset_id") and payload["dataset_id"] != dataset.id:
        raise ValueError("trigger dataset_id does not match dataset_name")
    projects = getattr(client.api.projects.get(), "data", []) or []
    matches = [project for project in projects if project.name == langfuse_project() and project.id == dataset.project_id]
    if len(matches) != 1:
        raise RuntimeError(f"dataset does not belong to configured Langfuse project {langfuse_project()!r}")
    resolved_version = dataset.version or version
    if resolved_version.utcoffset() is None:
        resolved_version = resolved_version.replace(tzinfo=timezone.utc)
    return dataset, resolved_version.astimezone(timezone.utc)


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
        cache_mode = payload.get("cache_mode", "bypass")
        if cache_mode not in {"use", "bypass", "refresh"}:
            raise ValueError("cache_mode must be use, bypass, or refresh")
        cache_layers = answer_cache.normalize_layers(payload.get("cache_layers"))
        cache_enabled = cache_mode != "bypass" and "answer" in cache_layers
        resolved = resolve(payload.get("pipeline"), payload.get("settings"), prompt_label=payload.get("prompt_label"))
        config = resolved.config
        client = _client()
        dataset, version = _dataset_for(payload, client)
        prompt_bundle = (load_prompt_bundle(client, versions=resolved.prompts) if resolved.engine == "fixed"
                         and resolved.status != "draft" else
                         load_prompt_bundle(client, label=payload.get("prompt_label")) if resolved.engine == "fixed" else {})
        prompt_versions = prompt_manifests(prompt_bundle)
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
        pipeline_manifest, evaluator_manifest, corpus_checksum = _fingerprints(config, version, prompt_versions, managed_evaluators, correctness_name, resolved)
        # Include the selected frozen snapshot and exact corpus content in each execution manifest.
        variant = re.sub(r"[^A-Za-z0-9._-]+", "-", payload.get("variant_label", resolved.version)).strip("-")[:50] or "run"
        run_name = f"{variant}-{execution_id}"
        corpus_title = corpus_config().title
        (corpus_data_dir() / "executions" / execution_id).mkdir(parents=True, exist_ok=True)
        manifest = {"execution_id": execution_id, "variant_label": variant, "dataset_snapshot": snapshot,
                    "pipeline": pipeline_manifest, "evaluator": evaluator_manifest,
                    "prompt_label": payload.get("prompt_label"),
                    "prompts": prompt_versions,
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
            cache_scope = _answer_cache_identity(str(question), resolved, collection) if cache_enabled else None
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
                        trace_metadata["agent_automatic_scene_search"] = resolved.agent_settings.initial_scene_probe
                        trace_metadata["agent_scene_candidate_count"] = resolved.agent_settings.scene_candidate_count
                    trace_metadata.update({f"prompt_{name}": f"{asset['id']}@{asset['version']}:{asset['label']}"
                                           for name, asset in prompt_versions.items()})
                    trace_metadata.update({f"managed_eval_{name}": f"{asset['id']}@{asset['version']}"
                                           for name, asset in managed_evaluators.items()})
                    with propagate_attributes(session_id=session, metadata=trace_metadata,
                                              tags=[f"pipeline:{resolved.pipeline_id}"]):
                        record_cache_lookup("answer", cache_statuses[item.id],
                                            cache_lookup_seconds, cache_source,
                                            input={"question": question}, output=cached_output)
                        if cached_output is not None:
                            return _cached_output_with_timing(cached_output, cache_source,
                                                              cache_lookup_seconds)
                        layer_scope = intermediate_cache_scope(resolved, collection, langfuse_project())
                        with use_intermediate_cache(cache_mode, cache_layers, layer_scope):
                            output = run_resolved_pipeline(str(question), resolved, collection, prompt_bundle)
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
            experiment_metadata["agent_automatic_scene_search"] = resolved.agent_settings.initial_scene_probe
            experiment_metadata["agent_scene_candidate_count"] = resolved.agent_settings.scene_candidate_count
            experiment_metadata["agent_endpoint"] = ("responses" if resolved.agent_settings.provider == "openai"
                                                      and resolved.agent_settings.reasoning_effort != "none"
                                                      else "chat_completions" if resolved.agent_settings.provider == "openai"
                                                      else "ollama")
        # One key per setting: Langfuse drops propagated metadata values over 200 characters.
        experiment_metadata.update({f"config_{key}": value if isinstance(value, str) else json.dumps(value, sort_keys=True)
                                    for key, value in config.manifest().items() if key != "prompt_hashes"})
        experiment_metadata.update({f"prompt_{name}": f"{asset['id']}@{asset['version']}:{asset['label']}"
                                    for name, asset in prompt_versions.items()})
        experiment_metadata.update({f"managed_eval_{name}": f"{asset['id']}@{asset['version']}"
                                    for name, asset in managed_evaluators.items()})
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
                          "managed_evaluators": managed_evaluators, "prompts": prompt_versions,
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


def submit(payload: dict[str, Any], *, idempotency_key: str | None = None) -> tuple[dict[str, Any], bool]:
    execution_id = str(uuid.uuid4())
    row, created = enqueue(execution_id, payload, idempotency_key)
    if created:
        _jobs.put(execution_id)
    return row, created


def submit_retry(execution_id: str, *, idempotency_key: str | None = None) -> tuple[dict[str, Any], bool]:
    """Queue a deliberate, linked retry of a failed or partial execution."""
    source = get_execution(execution_id)
    if source is None:
        raise KeyError(execution_id)
    if source["status"] not in {"failed", "partial"}:
        raise ValueError(f"only failed or partial executions can be retried (status={source['status']})")
    payload = json.loads(source["payload_json"])
    if "pipeline" not in payload:
        raise ValueError("pre-migration executions cannot be retried")
    payload["retry_of_execution_id"] = execution_id
    return submit(payload, idempotency_key=idempotency_key)


def _worker_loop() -> None:
    while True:
        execution_id = _jobs.get()
        try:
            execute_execution(execution_id)
        finally:
            _jobs.task_done()


def start_worker() -> None:
    global _worker
    initialize()
    mark_interrupted()
    for row in pending_jobs():
        _jobs.put(row["execution_id"])
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_worker_loop, name="experiment-worker", daemon=True)
        _worker.start()


def cli() -> int:
    parser = argparse.ArgumentParser(description="Run Millennium RAG against a pinned Langfuse dataset version")
    parser.add_argument("--dataset", default=os.getenv("DATASET_NAME", "QA.csv"))
    parser.add_argument("--dataset-version", help="ISO-8601 UTC dataset version timestamp")
    parser.add_argument("--variant", default=None)
    parser.add_argument("--prompt-label", default=None)
    parser.add_argument("--pipeline", default=None)
    parser.add_argument("--cache-mode", choices=("use", "bypass", "refresh"), default="bypass",
                        help="answer-cache mode; experiments bypass by default")
    parser.add_argument("--cache-layer", action="append", dest="cache_layers", choices=sorted(answer_cache.LAYERS),
                        help="cache layer to use; repeatable, defaults to all supported layers")
    settings_group = parser.add_mutually_exclusive_group()
    settings_group.add_argument("--settings", type=Path, help="JSON settings overrides file")
    settings_group.add_argument("--config", type=Path, help="alias for --settings")
    parser.add_argument("--item-id", action="append", dest="item_ids")
    parser.add_argument("--correctness-evaluator", choices=sorted(CORRECTNESS_SPECS), default=DEFAULT_CORRECTNESS)
    args = parser.parse_args()
    settings_file = args.settings or args.config
    default_pipeline = load_catalog().default
    selected_pipeline = args.pipeline or default_pipeline
    payload = {"dataset_name": args.dataset, "dataset_version": args.dataset_version,
               "pipeline": selected_pipeline, "variant_label": args.variant or selected_pipeline,
               "settings": json.loads(settings_file.read_text()) if settings_file else {},
               "item_ids": args.item_ids, "prompt_label": args.prompt_label,
               "cache_mode": args.cache_mode, "cache_layers": args.cache_layers,
               "correctness_evaluator": args.correctness_evaluator}
    initialize()
    row, _ = enqueue(str(uuid.uuid4()), payload, None)
    result = execute_execution(row["execution_id"])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(cli())
