"""Score existing Langfuse experiment answers without rerunning the RAG pipeline."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time

from langfuse import Langfuse

try:
    from .evaluation import correctness
    from .evaluator_specs import ANSWER_CORRECTNESS_CODEX_V1
    from .prompt_assets import ManagedJudgePrompt, load_managed_evaluators
except ImportError:
    from evaluation import correctness
    from evaluator_specs import ANSWER_CORRECTNESS_CODEX_V1
    from prompt_assets import ManagedJudgePrompt, load_managed_evaluators


def _save(path: Path, state: dict) -> None:
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    pending.replace(path)


def run(execution_id: str, *, max_items: int | None = None, workers: int = 2) -> dict:
    if not 1 <= workers <= 2:
        raise ValueError("workers must be 1 or 2")
    execution_dir = Path(os.getenv("EXPERIMENT_DATA_DIR", "./data")) / "executions" / execution_id
    source = json.loads((execution_dir / "results.json").read_text(encoding="utf-8"))
    request = json.loads((execution_dir / "request.json").read_text(encoding="utf-8"))
    if source.get("status") != "completed" or source.get("dataset_item_count") != source.get("completed_item_count"):
        raise ValueError("source execution must be a completed full dataset run")
    rows = source["item_results"]
    if len(rows) != len({row["item_id"] for row in rows}) or any(not row.get("trace_id") for row in rows):
        raise ValueError("source execution has missing or duplicate item identities")
    state_path = Path(os.getenv("EXPERIMENT_DATA_DIR", "./data")) / "codex_rescores" / f"{execution_id}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = (json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else
             {"source_execution_id": execution_id, "dataset_run_id": source["dataset_run_id"],
              "dataset_run_url": source["dataset_run_url"], "evaluator": ANSWER_CORRECTNESS_CODEX_V1.name,
              "items": {}, "started_at": datetime.now().astimezone().isoformat()})
    if state["source_execution_id"] != execution_id or state["dataset_run_id"] != source["dataset_run_id"]:
        raise ValueError("rescore state belongs to a different experiment")

    client = Langfuse(environment="sdk-experiment")
    started = time.perf_counter()
    processed = 0
    try:
        dataset = client.get_dataset(request["dataset_name"], version=datetime.fromisoformat(source["dataset_version"]))
        if dataset.id != source["dataset_id"]:
            raise ValueError("pinned dataset ID does not match source execution")
        items = {item.id: item for item in dataset.items}
        if set(items) != {row["item_id"] for row in rows}:
            raise ValueError("pinned dataset items do not match source execution")
        managed = load_managed_evaluators()[ANSWER_CORRECTNESS_CODEX_V1.name]
        prompt = ManagedJudgePrompt(managed)
        evaluator_id = hashlib.sha256(
            f"{execution_id}:{managed['id']}@{managed['version']}".encode()).hexdigest()

        def evaluate(row: dict) -> tuple[dict, dict, float]:
            item_id = row["item_id"]
            item = items[item_id]
            item_started = time.perf_counter()
            with client.start_as_current_observation(
                    name="codex rescore existing answer", as_type="evaluator",
                    trace_context={"trace_id": row["trace_id"]},
                    input={"question": item.input, "answer": row["output"].get("answer")},
                    metadata={"source_execution_id": execution_id, "dataset_item_id": item_id}) as parent:
                score = correctness(input=item.input, output=row["output"], expected_output=item.expected_output,
                                    spec=ANSWER_CORRECTNESS_CODEX_V1, evaluator_id=evaluator_id,
                                    langfuse_client=client, managed_prompt=prompt,
                                    evaluator_version=managed["version"], managed_evaluator_id=managed["id"])
                parent.update(output={"score": score["value"], "comment": score.get("comment")})
            return row, score, round(time.perf_counter() - item_started, 4)

        def commit(row: dict, score: dict, item_seconds: float) -> None:
            nonlocal processed
            item_id = row["item_id"]
            if score["name"] != ANSWER_CORRECTNESS_CODEX_V1.name:
                raise RuntimeError(f"item {item_id} failed: {score.get('comment')}")
            task_observations = client.api.observations.get_many(trace_id=row["trace_id"],
                name="experiment-item-task", limit=100, fields="core,basic")
            if len(task_observations.data) != 1:
                raise RuntimeError(f"item {item_id} has no unique experiment task observation")
            client.create_score(trace_id=row["trace_id"], observation_id=task_observations.data[0].id,
                                name=score["name"],
                                value=score["value"], comment=score["comment"], metadata=score["metadata"])
            client.flush()
            for attempt in range(45):
                uploaded = client.api.scores_v3.get_many_v3(trace_id=row["trace_id"],
                    name=score["name"], fields="details,subject", limit=100)
                if any(item.value == score["value"] for item in uploaded.data):
                    break
                time.sleep(1)
            else:
                raise RuntimeError(f"item {item_id} score did not reach Langfuse")
            state["items"][item_id] = {"trace_id": row["trace_id"], "score": score["value"],
                                        "comment": score["comment"],
                                        "usage": score["metadata"].get("codex_usage"),
                                        "judge_seconds": score["metadata"].get("evaluator_latency_seconds"),
                                        "item_seconds": item_seconds}
            processed += 1
            state["completed_count"] = len(state["items"])
            state["sum_item_seconds"] = round(state.get("sum_item_seconds", state.get("run_seconds", 0)) + item_seconds, 4)
            _save(state_path, state)
            print(json.dumps({"item": state["completed_count"], "of": len(rows), "item_id": item_id,
                              "score": score["value"], "judge_seconds": state["items"][item_id]["judge_seconds"],
                              "item_seconds": state["items"][item_id]["item_seconds"],
                              "usage": state["items"][item_id]["usage"]}), flush=True)

        # A score can be indexed after the previous invocation's verifier timed out.
        # Recover it before starting another Codex session for the same answer.
        for row in rows:
            item_id = row["item_id"]
            if item_id in state["items"]:
                continue
            uploaded = client.api.scores_v3.get_many_v3(trace_id=row["trace_id"],
                name=ANSWER_CORRECTNESS_CODEX_V1.name, fields="details,subject", limit=100)
            matching = [score for score in uploaded.data
                        if (score.metadata or {}).get("evaluator_model") == "gpt-5.6-luna"]
            if not matching:
                continue
            score = matching[-1]
            metadata = score.metadata or {}
            state["items"][item_id] = {
                "trace_id": row["trace_id"], "score": score.value,
                "comment": score.comment, "usage": metadata.get("codex_usage"),
                "judge_seconds": metadata.get("evaluator_latency_seconds"),
                "item_seconds": None, "recovered_from_langfuse": True,
            }
            state["completed_count"] = len(state["items"])
            _save(state_path, state)
            print(json.dumps({"recovered_item": item_id, "score": score.value}), flush=True)

        pending_rows = [row for row in rows if row["item_id"] not in state["items"]]
        if max_items is not None:
            pending_rows = pending_rows[:max_items]
        row_iter = iter(pending_rows)
        error: Exception | None = None
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="codex-rescore") as pool:
            pending = {}
            for row in list(pending_rows[:workers]):
                pending[pool.submit(evaluate, row)] = row
                next(row_iter)
            while pending:
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    pending.pop(future)
                    try:
                        commit(*future.result())
                    except Exception as exc:
                        if error is None:
                            error = exc
                    if error is None:
                        next_row = next(row_iter, None)
                        if next_row is not None:
                            pending[pool.submit(evaluate, next_row)] = next_row
        if error is not None:
            raise error
        state["status"] = "completed" if len(state["items"]) == len(rows) else "partial"
        elapsed = round(time.perf_counter() - started, 4)
        state["cumulative_wall_seconds"] = round(state.get("cumulative_wall_seconds", state.get("last_invocation_seconds", 0)) + elapsed, 4)
        state["last_invocation_seconds"] = elapsed
        state["finished_at"] = datetime.now().astimezone().isoformat()
        _save(state_path, state)
        return state
    finally:
        client.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution_id")
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    result = run(args.execution_id, max_items=args.max_items, workers=args.workers)
    print(json.dumps({"status": result["status"], "completed_count": result["completed_count"],
                      "wall_seconds": result["cumulative_wall_seconds"], "dataset_run_url": result["dataset_run_url"]}))
