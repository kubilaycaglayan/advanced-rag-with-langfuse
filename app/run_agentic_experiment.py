# Workaround for agentic experiment w Langfuse
"""Run one Langfuse dataset through the production Agentic question workflow.

This is a temporary bridge until the durable /experiments runner accepts a
pipeline selection. Langfuse's hosted dataset experiment API still provides the
experiment entry, item traces, and evaluator scores.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any

from langfuse import propagate_attributes

from app.corpus_config import corpus_data_dir
from app.corpus_config import corpus_config

from app.agent import AgentSettings, run_agent
from app.evaluation import correctness
from app.experiments import ExperimentLangfuse, _dataset_for, _item_session, _jsonable
from app.identity import canonical_json, dataset_snapshot, question_label, source_manifest
from app.indexer import index_identity, validate_index
from app.observability import use_client
from app.prompt_assets import ManagedJudgePrompt, load_managed_evaluators
from app.resolved_config import ResolvedPipelineConfig, resolve_pipeline_model_identities
from app.evaluator_specs import ANSWER_CORRECTNESS_V2


DATASETS = tuple(corpus_config().question_sets)


def _identity(config: ResolvedPipelineConfig, collection: str, agent_model: str,
              evaluator: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    root = Path(__file__).resolve().parents[1]
    source = source_manifest(str(root))
    pipeline_values = {
        "engine": "agent",
        "source_fingerprint": source["source_fingerprint"],
        "dirty": source["dirty"],
        "resolved_config": config.manifest(),
        "collection": collection,
        "agent": AgentSettings(model=agent_model).__dict__,
    }
    pipeline_id = "agentic-" + hashlib.sha256(canonical_json(pipeline_values).encode()).hexdigest()[:16]
    evaluator_values = {
        "name": ANSWER_CORRECTNESS_V2.name,
        "version": ANSWER_CORRECTNESS_V2.version,
        "managed_id": evaluator["id"],
        "managed_version": evaluator["version"],
        "model": os.getenv("EVALUATOR_MODEL", "qwen3:8b"),
        "spec": ANSWER_CORRECTNESS_V2.manifest(),
    }
    evaluator_id = hashlib.sha256(canonical_json(evaluator_values).encode()).hexdigest()
    return pipeline_id, evaluator_id, {"pipeline": pipeline_values, "evaluator": evaluator_values}


def run_dataset(dataset_name: str) -> dict[str, Any]:
    client = ExperimentLangfuse(environment="sdk-experiment")
    config = resolve_pipeline_model_identities(ResolvedPipelineConfig())
    agent_model = os.getenv("AGENT_MODEL", "qwen3.6:35b")
    managed = load_managed_evaluators()
    evaluator = managed.get(ANSWER_CORRECTNESS_V2.name)
    if not evaluator or not evaluator.get("id") or not evaluator.get("version"):
        raise RuntimeError("Managed answer_correctness_v2 evaluator is unavailable")
    dataset, version = _dataset_for({"dataset_name": dataset_name}, client)
    items = list(dataset.items)
    if not items:
        raise RuntimeError(f"Dataset {dataset_name!r} contains no items")

    collection = index_identity(config)[0]
    validate_index(collection, config)
    pipeline_id, evaluator_id, identity = _identity(config, collection, agent_model, evaluator)
    snapshot = dataset_snapshot(
        [{"id": item.id, "input": item.input, "expected_output": item.expected_output, "metadata": item.metadata}
         for item in items],
        dataset_id=dataset.id, dataset_name=dataset.name, version=version,
    )
    run_id = str(uuid.uuid4())
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", dataset_name).strip("-")
    run_name = f"agentic-{slug}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{run_id[:8]}"
    metadata = {
        "workflow": "HMT Agentic",
        "engine": "agent",
        "execution_id": run_id,
        "pipeline_id": pipeline_id,
        "evaluator_id": evaluator_id,
        "correctness_evaluator": ANSWER_CORRECTNESS_V2.name,
        "managed_evaluator_id": evaluator["id"],
        "managed_evaluator_version": str(evaluator["version"]),
        "agent_model": agent_model,
        "dataset_version": version.isoformat(),
        "snapshot_sha256": snapshot["sha256"],
        "collection": collection,
    }

    def task(*, item: Any, **_: Any) -> dict[str, Any]:
        question = item.input.get("question") if isinstance(item.input, dict) else item.input
        session_id = _item_session(dataset.name, item)
        tags = [f"question:{question_label(dataset.name, item.id, item.metadata)}", "pipeline:agentic"]
        trace_metadata = {**metadata, "dataset_item_id": item.id, "dataset_id": dataset.id,
                          "dataset_name": dataset.name}
        try:
            with use_client(client), propagate_attributes(session_id=session_id, tags=tags,
                                                          metadata=trace_metadata,
                                                          environment="sdk-experiment"):
                return run_agent(str(question), collection, config,
                                 settings=AgentSettings(model=agent_model))
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "answer": "", "evidence": [], "trace": []}

    judge = partial(
        correctness,
        evaluator_id=evaluator_id,
        langfuse_client=client,
        spec=ANSWER_CORRECTNESS_V2,
        managed_prompt=ManagedJudgePrompt(evaluator),
        evaluator_version=evaluator["version"],
        managed_evaluator_id=evaluator["id"],
    )
    print(f"Starting {dataset_name}: {len(items)} items; run={run_name}; pipeline={pipeline_id}; evaluator=answer_correctness_v2", flush=True)
    result = client.run_experiment(
        name=f"Millennium Agentic: {dataset_name}",
        run_name=run_name,
        description=(f"Agentic production workflow; {len(items)} items; dataset version {version.isoformat()}; "
                     f"pipeline {pipeline_id}; evaluator answer_correctness_v2"),
        data=items,
        task=task,
        evaluators=[judge],
        max_concurrency=1,
        metadata=metadata,
        _dataset_version=version,
    )
    client.flush()

    scores: list[float] = []
    failed = 0
    traces: list[dict[str, Any]] = []
    for item_result in result.item_results:
        output = item_result.output
        failed += int(not isinstance(output, dict) or bool(output.get("error")))
        for evaluation in item_result.evaluations:
            if getattr(evaluation, "name", None) == ANSWER_CORRECTNESS_V2.name and isinstance(getattr(evaluation, "value", None), (float, int)):
                scores.append(float(evaluation.value))
        traces.append({"item_id": item_result.item.id, "trace_id": item_result.trace_id,
                       "answer": (output or {}).get("answer") if isinstance(output, dict) else str(output),
                       "evaluations": [_jsonable(evaluation) for evaluation in item_result.evaluations]})
    artifact = {
        "dataset_name": dataset_name,
        "dataset_id": dataset.id,
        "dataset_version": version.isoformat(),
        "dataset_snapshot_sha256": snapshot["sha256"],
        "execution_id": run_id,
        "pipeline_id": pipeline_id,
        "evaluator_id": evaluator_id,
        "identity": identity,
        "run_name": result.run_name,
        "experiment_id": result.experiment_id,
        "dataset_run_id": result.dataset_run_id,
        "dataset_run_url": result.dataset_run_url,
        "item_count": len(items),
        "completed_item_count": len(result.item_results),
        "failed_item_count": failed,
        "answer_correctness_v2_mean": sum(scores) / len(scores) if scores else None,
        "answer_correctness_v2_count": len(scores),
        "items": traces,
    }
    out_dir = corpus_data_dir() / "agentic-experiments"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slug}-{run_id}.json"
    out_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {key: artifact[key] for key in (
        "dataset_name", "item_count", "completed_item_count", "failed_item_count",
        "answer_correctness_v2_mean", "answer_correctness_v2_count", "dataset_run_url",
    )}
    summary["artifact"] = str(out_path)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=DATASETS)
    args = parser.parse_args()
    run_dataset(args.dataset)


if __name__ == "__main__":
    main()
