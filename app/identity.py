"""Stable identity and canonical snapshot helpers used by experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


SEED_ITEM_NAMESPACE = uuid.UUID("f7b2a6de-8c54-4a7a-a6df-e919d527cd8e")
PIPELINE_SOURCE_PATHS = (
    "app",
    "compose.yaml",
)
PIPELINE_SOURCE_FILES = (
    "app/requirements.txt",
)
PIPELINE_SOURCE_EXCLUDES = (
    ".env and other dot-env files",
    ".venv directories",
    "data directories",
    "outputs directories",
    "__pycache__ directories and bytecode files",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_question(question: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", question).casefold().split())


def seed_row_key(question: str, occurrence: int = 1) -> str:
    if occurrence < 1:
        raise ValueError("occurrence must be a positive integer")
    normalized = normalize_question(question)
    source_key = f"{normalized}\0{occurrence}"
    return hashlib.sha256(source_key.encode("utf-8")).hexdigest()


def seeded_item_id(dataset_name: str, source_checksum: str, row_key: str) -> str:
    name = f"{dataset_name.casefold()}:{source_checksum}:{row_key}"
    return str(uuid.uuid5(SEED_ITEM_NAMESPACE, name))


def question_session_id(dataset_id: str, item_id: str, max_length: int = 200) -> str:
    session_id = f"qa-{dataset_id}-{item_id}"
    if len(session_id) <= max_length:
        return session_id
    suffix = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
    prefix_len = max_length - len(suffix) - 1
    if prefix_len < 1:
        raise ValueError("max_length is too short for a stable session identifier")
    return f"{session_id[:prefix_len]}-{suffix}"


def dataset_snapshot(
    items: Sequence[Mapping[str, Any]],
    *,
    dataset_id: str,
    dataset_name: str,
    version: datetime,
) -> dict[str, Any]:
    """Return a sorted immutable-data representation and its content checksum."""
    version_text = version.isoformat()
    offset = version.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError("dataset version must be a timezone-aware UTC timestamp")
    normalized = [
        {
            "id": item["id"],
            "input": item.get("input"),
            "expected_output": item.get("expected_output"),
            "metadata": item.get("metadata"),
        }
        for item in items
    ]
    normalized.sort(key=lambda item: str(item["id"]))
    digest = hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()
    return {
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "dataset_version": version_text,
        "item_count": len(normalized),
        "sha256": digest,
        "items": normalized,
    }


def pipeline_identity(
    *,
    git_revision: str,
    dirty: bool,
    source_fingerprint: str,
    resolved_config: Mapping[str, Any],
    corpus_checksum: str,
) -> dict[str, Any]:
    manifest = {
        "git_revision": git_revision,
        "dirty": dirty,
        "source_fingerprint": source_fingerprint,
        "resolved_config": resolved_config,
        "corpus_checksum": corpus_checksum,
    }
    full_hash = hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()
    return {"pipeline_id": f"pipeline-{full_hash[:16]}", "sha256": full_hash, **manifest}


def evaluator_identity(
    *,
    model: Mapping[str, Any],
    settings: Mapping[str, Any],
    rubric: str,
    prompt: str,
    code_version: str,
) -> str:
    manifest = {
        "model": model,
        "settings": settings,
        "rubric_sha256": hashlib.sha256(rubric.encode("utf-8")).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "code_version": code_version,
    }
    return hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()


def source_manifest(repo_root: str) -> dict[str, Any]:
    """Fingerprint pipeline code/config files, including tracked and untracked edits."""
    root = str(repo_root)
    pathspecs = [*PIPELINE_SOURCE_PATHS, *PIPELINE_SOURCE_FILES]
    listed = subprocess.run(
        ["git", "-C", root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *pathspecs],
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    relative_paths = sorted({entry.decode("utf-8") for entry in listed if entry})
    files: list[dict[str, str]] = []
    for relative in relative_paths:
        path = Path(root, relative)
        if (
            any(part == ".venv" or part == "__pycache__" or part in {"data", "outputs"} for part in path.parts)
            or any(part.startswith(".env") for part in path.parts)
            or path.suffix in {".pyc", ".pyo"}
        ):
            continue
        if not path.is_file():
            continue
        files.append({
            "path": relative,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })

    status = subprocess.run(
        ["git", "-C", root, "status", "--porcelain", "--", *pathspecs],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    revision = subprocess.run(
        ["git", "-C", root, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    fingerprint = hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest()
    return {
        "git_revision": revision,
        "dirty": bool(status.strip()),
        "source_fingerprint": fingerprint,
        "included_paths": [*PIPELINE_SOURCE_PATHS, *PIPELINE_SOURCE_FILES],
        "excluded_patterns": list(PIPELINE_SOURCE_EXCLUDES),
        "files": files,
    }
