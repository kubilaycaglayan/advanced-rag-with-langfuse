"""Rescore saved experiment answers in a separate Langfuse dataset run and traces."""
from __future__ import annotations

import argparse
from datetime import datetime
from functools import partial
import hashlib
import json

from langfuse import Langfuse

try:
    from .corpus_config import corpus_data_dir
    from .evaluation import correctness
    from .evaluator_specs import ANSWER_CORRECTNESS_CODEX_V1
    from .prompt_assets import ManagedJudgePrompt, load_managed_evaluators
except ImportError:
    from corpus_config import corpus_data_dir
    from evaluation import correctness
    from evaluator_specs import ANSWER_CORRECTNESS_CODEX_V1
    from prompt_assets import ManagedJudgePrompt, load_managed_evaluators


def run(source_execution_id: str) -> dict:
    source_dir = corpus_data_dir() / "executions" / source_execution_id
    source = json.loads((source_dir / "results.json").read_text())
    request = json.loads((source_dir / "request.json").read_text())
    rows = source["item_results"]
    if len(rows) != source["dataset_item_count"] or len(rows) != source["completed_item_count"]:
        raise ValueError("source must contain every pinned dataset item")
    if any(row.get("failed") or not row.get("output", {}).get("answer") for row in rows):
        raise ValueError("source has a missing answer")
    source_by_id = {row["item_id"]: row for row in rows}
    if len(source_by_id) != len(rows):
        raise ValueError("source has duplicate items")
    output_path = corpus_data_dir() / "codex_rescores" / f"{source_execution_id}-separate.json"
    if output_path.exists():
        raise FileExistsError(f"rescore artifact already exists: {output_path}")

    client = Langfuse(environment="sdk-experiment")
    try:
        version = datetime.fromisoformat(source["dataset_version"])
        dataset = client.get_dataset(request["dataset_name"], version=version)
        if dataset.id != source["dataset_id"] or {item.id for item in dataset.items} != set(source_by_id):
            raise ValueError("pinned dataset differs from the source run")
        managed = load_managed_evaluators()[ANSWER_CORRECTNESS_CODEX_V1.name]
        run_name = f"codex-rescore-{source_execution_id}"
        evaluator_id = hashlib.sha256(f"{run_name}:{managed['id']}@{managed['version']}".encode()).hexdigest()

        def task(*, item, **kwargs):
            row = source_by_id[item.id]
            print(f"Rescoring {item.id}", flush=True)
            return row["output"]

        result = client.run_experiment(
            name="Millennium saved-answer Codex rescore", run_name=run_name,
            description=f"Separate traces for saved answers from execution {source_execution_id}; no RAG rerun",
            data=dataset.items, task=task,
            evaluators=[partial(correctness, spec=ANSWER_CORRECTNESS_CODEX_V1,
                evaluator_id=evaluator_id, langfuse_client=client,
                managed_prompt=ManagedJudgePrompt(managed),
                evaluator_version=managed["version"], managed_evaluator_id=managed["id"])],
            max_concurrency=2, _dataset_version=version,
            metadata={"source_execution_id": source_execution_id,
                      "source_dataset_run_id": source["dataset_run_id"],
                      "rescore_evaluator": ANSWER_CORRECTNESS_CODEX_V1.name,
                      "source_pipeline_version": source["pipeline_version"]})
        client.flush()
        item_results = []
        for item_result in result.item_results:
            source_row = source_by_id[item_result.item.id]
            codex = next((score for score in item_result.evaluations
                          if score.name == ANSWER_CORRECTNESS_CODEX_V1.name), None)
            item_results.append({"item_id": item_result.item.id, "source_trace_id": source_row["trace_id"],
                "rescore_trace_id": item_result.trace_id,
                "original_score": source_row["correctness_score"],
                "codex_score": codex.value if codex else None,
                "codex_comment": codex.comment if codex else None,
                "evaluations": [vars(score) for score in item_result.evaluations]})
        if any(row["rescore_trace_id"] == row["source_trace_id"] for row in item_results):
            raise RuntimeError("rescore reused a source trace")
        payload = {"source_execution_id": source_execution_id,
            "source_dataset_run_id": source["dataset_run_id"],
            "rescore_dataset_run_id": result.dataset_run_id,
            "rescore_dataset_run_url": result.dataset_run_url,
            "evaluator": ANSWER_CORRECTNESS_CODEX_V1.name,
            "evaluator_version": managed["version"], "items": item_results}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, default=str))
        return payload
    finally:
        client.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_execution_id")
    args = parser.parse_args()
    result = run(args.source_execution_id)
    print(json.dumps({"rescore_dataset_run_url": result["rescore_dataset_run_url"],
                      "items": len(result["items"])}))
