"""Add answer facts from datasets/answer-facts.json to Langfuse dataset items as a new dataset version.

Each item keeps its expected `answer` and gains `required_facts` and `supporting_details`, which only
`answer_correctness_v2` reads. Langfuse keeps the earlier item versions, so a run pinned to an earlier
`dataset_version` (or judged with `answer_correctness_v1`) is unaffected.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from langfuse import Langfuse

FACTS_PATH = Path(__file__).resolve().parents[1] / "datasets" / "answer-facts.json"


def plan(client: Langfuse, facts: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the items whose expected output differs from the facts file."""
    changes = []
    for dataset_name, items in facts["datasets"].items():
        current = {item.id: item for item in client.get_dataset(dataset_name).items}
        missing = sorted(set(items) - set(current))
        if missing:
            raise RuntimeError(f"{dataset_name}: items absent from the dataset: {missing}")
        for item_id, item_facts in items.items():
            item = current[item_id]
            expected = dict(item.expected_output or {})
            updated = {**expected, "required_facts": item_facts["required_facts"],
                       "supporting_details": item_facts["supporting_details"], "facts_version": facts["version"]}
            if updated != expected:
                changes.append({"dataset_name": dataset_name, "id": item_id, "input": item.input,
                                "expected_output": updated, "metadata": item.metadata})
    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="upload the changes (default: dry run)")
    args = parser.parse_args()
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    client = Langfuse()
    try:
        changes = plan(client, facts)
        if args.apply:
            for change in changes:
                client.create_dataset_item(**change)
        counts: dict[str, int] = {}
        for change in changes:
            counts[change["dataset_name"]] = counts.get(change["dataset_name"], 0) + 1
        print(json.dumps({"applied": args.apply, "changed_items": counts}, indent=2))
    finally:
        client.shutdown()


if __name__ == "__main__":
    main()
