"""Run the pinned organization sample against existing indexes only.

Run from repository root with python -m scripts.verification.organization_comparison
and the one-off container mounts documented in AGENTS.md.
"""
import argparse
import json
import uuid
from pathlib import Path
from unittest.mock import patch

from app.experiments import execution as experiments
from app.agent.instructions import instruction_manifest
from app.experiments.store import enqueue
from app.storage import initialize
from app.indexing.passages import index_identity, validate_index
from app.pipelines.resolver import resolve


def existing_index(config):
    """Fail rather than invoke any index builder during verification."""
    collection = index_identity(config)[0]
    validate_index(collection, config)
    return {"collection": collection}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["baseline", "final"])
    args = parser.parse_args()
    manifest = json.loads(Path("docs/experiments/2026-11-25-organization-comparison.json").read_text())
    output = Path("data/millennium/comparisons/2026-11-25-organization")
    output.mkdir(parents=True, exist_ok=True)
    contracts = {"instructions": instruction_manifest(), "providers": {}}
    for provider in ("ollama", "openai"):
        resolved = resolve("v2.16", {"agent_provider": provider})
        contracts["providers"][provider] = {"pipeline_id": resolved.pipeline_id,
            "settings": resolved.agent_settings.__dict__, "index": resolved.index,
            "config": resolved.config.manifest()}
    (output / f"{args.phase}-contracts.json").write_text(json.dumps(contracts, indent=2, default=str))
    initialize()
    for name, dataset in manifest["datasets"].items():
        for provider in ("ollama", "openai"):
            target = output / f"{args.phase}-{name.replace(' ', '-')}-{provider}.json"
            if target.exists() and json.loads(target.read_text()).get("status") == "completed":
                print(f"Already recorded: {target}", flush=True)
                continue
            if target.exists():
                previous = json.loads(target.read_text())
                target.rename(target.with_name(target.stem + "-failed-" + previous["execution_id"] + ".json"))
            payload = {"dataset_name": name, "dataset_version": dataset["version"],
                "dataset_id": dataset["id"], "pipeline": "v2.16",
                "settings": {"agent_provider": provider}, "cache_mode": "bypass",
                "item_ids": [item["id"] for item in dataset["items"]],
                "variant_label": f"organization-{args.phase}-{provider}"}
            execution_id = str(uuid.uuid4())
            enqueue(execution_id, payload, None)
            print(f"Starting {name} / {provider}: {execution_id}", flush=True)
            with patch.object(experiments, "build_index", existing_index):
                result = experiments.execute_execution(execution_id)
            target.write_text(json.dumps(result, indent=2, default=str))
            print(f"Finished {name} / {provider}: {result['status']}", flush=True)


if __name__ == "__main__":
    main()
