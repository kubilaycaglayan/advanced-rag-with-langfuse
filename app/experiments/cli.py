"""experiments / cli responsibilities."""
from __future__ import annotations

from app.cache import answers as answer_cache
from app.evaluation.specs import CORRECTNESS_SPECS
from app.evaluation.specs import DEFAULT_CORRECTNESS
from app.experiments.execution import execute_execution
from app.experiments.store import enqueue
from app.pipelines.catalog import load_catalog
from app.storage import initialize
from pathlib import Path
import argparse
import json
import os
import uuid



def cli() -> int:
    parser = argparse.ArgumentParser(description="Run Millennium RAG against a pinned Langfuse dataset version")
    parser.add_argument("--dataset", default=os.getenv("DATASET_NAME", "QA.csv"))
    parser.add_argument("--dataset-version", help="ISO-8601 UTC dataset version timestamp")
    parser.add_argument("--variant", default=None)
    parser.add_argument("--pipeline", default=None)
    parser.add_argument("--cache-mode", choices=("use", "bypass", "refresh"), default="refresh",
                        help="cache mode; experiments refresh by default without reading cached answers")
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
               "item_ids": args.item_ids,
               "cache_mode": args.cache_mode, "cache_layers": args.cache_layers,
               "correctness_evaluator": args.correctness_evaluator}
    initialize()
    row, _ = enqueue(str(uuid.uuid4()), payload, None)
    result = execute_execution(row["execution_id"])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "completed" else 1

