"""One-time, non-destructive QA.csv import into a hosted Langfuse dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from langfuse import Langfuse
from langfuse.api import NotFoundError

try:
    from .identity import canonical_json, normalize_question, seed_row_key, seeded_item_id
except ImportError:
    from identity import canonical_json, normalize_question, seed_row_key, seeded_item_id


def read_seed(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw = path.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["Question", "Answer"]:
            raise ValueError("QA.csv must have exactly the columns Question,Answer in that order")
        rows = list(reader)

    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=2):
        question = (row.get("Question") or "").strip()
        answer = (row.get("Answer") or "").strip()
        if not question or not answer:
            raise ValueError(f"blank Question or Answer at CSV row {row_number}")
        normalized = normalize_question(question)
        if normalized in seen:
            raise ValueError(f"duplicate normalized question at CSV row {row_number}")
        seen.add(normalized)
        occurrence = 1
        key = seed_row_key(question, occurrence)
        items.append({
            "id": seeded_item_id("qa-csv", checksum, key),
            "input": {"question": question},
            "expected_output": {"answer": answer},
            "metadata": {
                "seed_row_key": key,
                "source_checksum": checksum,
                "source_row": row_number,
                "seed_occurrence": occurrence,
            },
        })
    return items, checksum


def _item_payload(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "input": item.input,
        "expected_output": item.expected_output,
        "metadata": item.metadata or {},
    }


def _resolve_project_and_dataset(client: Langfuse, dataset_name: str) -> tuple[Any, Any | None]:
    project_response = client.api.projects.get()
    projects = getattr(project_response, "data", []) or []
    matches = [candidate for candidate in projects if candidate.name == "millenium"]
    if len(matches) != 1:
        raise RuntimeError("configured credentials do not resolve to exactly one project named 'millenium'")
    project = matches[0]

    try:
        dataset = client.get_dataset(dataset_name)
    except NotFoundError:
        dataset = None
    if dataset is not None and dataset.project_id != project.id:
        raise RuntimeError("dataset is not in the required Langfuse project")
    return project, dataset


def inspect_langfuse(dataset_name: str) -> dict[str, Any]:
    """Read-only project and dataset access check; never creates or changes data."""
    client = Langfuse()
    try:
        project, dataset = _resolve_project_and_dataset(client, dataset_name)
        return {
            "project_name": project.name,
            "project_id": project.id,
            "dataset_name": dataset_name,
            "dataset_id": dataset.id if dataset is not None else None,
            "dataset_items": len(dataset.items) if dataset is not None else 0,
            "dataset_exists": dataset is not None,
        }
    finally:
        try:
            client.flush()
        finally:
            client.shutdown()


def _seed_dataset(
    csv_path: Path,
    mapping_path: Path,
    client: Langfuse,
    *,
    reconcile_existing: bool = False,
) -> dict[str, Any]:
    source_items, checksum = read_seed(csv_path)
    previous: dict[str, Any] = {}
    if mapping_path.exists():
        previous = json.loads(mapping_path.read_text(encoding="utf-8"))
        if previous.get("source_checksum") != checksum:
            raise RuntimeError("QA.csv differs from the original seed; edit QA items in Langfuse instead")
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_name = os.getenv("DATASET_NAME", "QA.csv")

    project, dataset = _resolve_project_and_dataset(client, dataset_name)
    exists = dataset is not None

    if previous and not exists:
        raise RuntimeError("the dataset recorded in the local seed mapping no longer exists; refusing to recreate it")
    if not exists:
        dataset = client.create_dataset(
            name=dataset_name,
            description="Initial QA.csv seed; maintain question and reference edits in Langfuse.",
            input_schema={"type": "object", "required": ["question"], "properties": {"question": {"type": "string"}}},
            expected_output_schema={"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}},
        )
        existing_items: list[Any] = []
    else:
        existing_items = list(dataset.items)
        if dataset.project_id != project.id:
            raise RuntimeError("dataset is not in the required Langfuse project")
    if previous:
        if previous.get("dataset_id") != dataset.id:
            raise RuntimeError("local seed mapping belongs to a different Langfuse dataset")
    if existing_items and not previous and not reconcile_existing:
        raise RuntimeError(
            f"dataset {dataset_name!r} already has {len(existing_items)} items; "
            "inspect them and rerun with --reconcile-existing only if these are the seeded QA items"
        )

    expected = {item["id"]: item for item in source_items}
    observed: dict[str, Any] = {}
    unrelated: list[str] = []
    for item in existing_items:
        payload = _item_payload(item)
        if payload["id"] not in expected:
            unrelated.append(payload["id"])
        else:
            observed[payload["id"]] = payload
    if unrelated and not previous:
        raise RuntimeError("existing dataset contains items outside this seed mapping; refusing to modify it")

    created = 0
    missing: list[str] = []
    for item_id, item in expected.items():
        if item_id in observed:
            if (observed[item_id].get("metadata") or {}).get("seed_row_key") != item["metadata"]["seed_row_key"]:
                raise RuntimeError(f"existing item {item_id} has conflicting seed provenance")
            continue
        if previous:
            missing.append(item_id)
            continue
        if existing_items and not reconcile_existing:
            missing.append(item_id)
            continue
        client.create_dataset_item(
            dataset_name=dataset_name,
            id=item["id"],
            input=item["input"],
            expected_output=item["expected_output"],
            metadata=item["metadata"],
        )
        created += 1

    if missing:
        raise RuntimeError(
            f"{len(missing)} original seed items are absent; routine seeding will not recreate deleted items"
        )

    manifest = {
        "dataset_name": dataset_name,
        "dataset_id": dataset.id,
        "source_checksum": checksum,
        "items": [{"id": item["id"], "seed_row_key": item["metadata"]["seed_row_key"], "source_row": item["metadata"]["source_row"]} for item in source_items],
    }
    if previous and previous != manifest:
        raise RuntimeError("local mapping differs from source rows; no changes were made to Langfuse items")
    mapping_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    return {"dataset_name": dataset_name, "dataset_id": dataset.id, "source_checksum": checksum, "source_rows": len(source_items), "created": created, "existing_verified": len(observed)}


def seed_dataset(csv_path: Path, mapping_path: Path, *, reconcile_existing: bool = False) -> dict[str, Any]:
    client = Langfuse()
    try:
        return _seed_dataset(
            csv_path,
            mapping_path,
            client,
            reconcile_existing=reconcile_existing,
        )
    finally:
        client.flush()
        client.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path(__file__).resolve().parents[1] / "QA.csv")
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--check-only", action="store_true", help="verify project/dataset access without creating or changing data")
    parser.add_argument("--reconcile-existing", action="store_true", help="verify existing items by their deterministic IDs and provenance")
    args = parser.parse_args()
    data_dir = Path(os.getenv("EXPERIMENT_DATA_DIR", "./data"))
    mapping = args.mapping or data_dir / "seed-mapping.json"
    try:
        if args.check_only:
            print(json.dumps(inspect_langfuse(os.getenv("DATASET_NAME", "QA.csv")), indent=2))
        else:
            print(json.dumps(seed_dataset(args.csv, mapping, reconcile_existing=args.reconcile_existing), indent=2))
    except Exception as exc:
        detail = type(exc).__name__ if type(exc).__module__.startswith("langfuse") else f"{type(exc).__name__}: {exc}"
        print(f"seed failed: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
