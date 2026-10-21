"""Active corpus metadata and corpus-scoped filesystem paths."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CorpusConfig:
    id: str
    title: str
    language: str
    profile_id: str
    root: Path
    books: Path
    question_sets: dict[str, dict[str, Any]]
    answer_facts: Path | None
    langfuse: dict[str, Any]


@lru_cache(maxsize=16)
def _load(corpus_id: str, configured_root: str) -> CorpusConfig:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", corpus_id):
        raise ValueError(f"invalid corpus id {corpus_id!r}")
    root = Path(configured_root).resolve() if configured_root else ROOT / "corpora" / corpus_id
    metadata_path = root / "corpus.yaml"
    if not metadata_path.is_file():
        raise ValueError(f"corpus metadata not found: {metadata_path}")
    raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("id") != corpus_id:
        raise ValueError(f"{metadata_path} must declare id {corpus_id!r}")
    sets = raw.get("question_sets", {})
    if not isinstance(sets, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in sets.items()):
        raise ValueError(f"{metadata_path}: question_sets must map names to definitions")
    for name, definition in sets.items():
        question_path = definition.get("path")
        if question_path is None:
            continue
        if not isinstance(question_path, str):
            raise ValueError(f"{metadata_path}: question set {name!r} path must be a relative file path")
        resolved_question_path = (root / question_path).resolve()
        if root != resolved_question_path and root not in resolved_question_path.parents:
            raise ValueError(f"{metadata_path}: question set {name!r} path must stay inside its corpus directory")
    books = (root / str(raw.get("books", "books"))).resolve()
    if books != root and root not in books.parents:
        raise ValueError("books path must stay inside its corpus directory")
    facts = raw.get("answer_facts")
    facts_path = (root / facts).resolve() if isinstance(facts, str) else None
    if facts_path and root not in facts_path.parents:
        raise ValueError("answer_facts path must stay inside its corpus directory")
    profile_id = str(raw.get("profile", corpus_id))
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", profile_id):
        raise ValueError(f"{metadata_path}: invalid profile id {profile_id!r}")
    return CorpusConfig(id=corpus_id, title=str(raw.get("title", corpus_id)),
                        language=str(raw.get("language", "en")), profile_id=profile_id,
                        root=root, books=books, question_sets=sets, answer_facts=facts_path,
                        langfuse=dict(raw.get("langfuse") or {}))


def corpus_config() -> CorpusConfig:
    return _load(os.getenv("CORPUS_ID", "millennium"), os.getenv("CORPUS_ROOT", ""))


def corpus_id() -> str:
    return corpus_config().id


def langfuse_project() -> str:
    return str(corpus_config().langfuse.get("project", corpus_id()))


def langfuse_evaluator_prefix() -> str:
    return str(corpus_config().langfuse.get("evaluator_prefix", corpus_id()))


def langfuse_prompt_label() -> str:
    return str(corpus_config().langfuse.get("prompt_label", "production"))


def langfuse_dataset_name(name: str | None = None) -> str:
    config = corpus_config()
    requested = name or config.langfuse.get("default_dataset")
    definition = config.question_sets.get(str(requested), {})
    return str(definition.get("langfuse_dataset", requested or ""))


def corpus_data_dir() -> Path:
    base = Path(os.getenv("EXPERIMENT_DATA_DIR", str(ROOT / "data"))).expanduser()
    path = base if base.name == corpus_id() else base / corpus_id()
    path.mkdir(parents=True, exist_ok=True)
    return path


def corpus_file_path(environment_name: str, default_name: str) -> Path:
    """Resolve an optional cache path inside the selected corpus's data namespace."""
    configured = os.getenv(environment_name)
    if not configured:
        return corpus_data_dir() / default_name
    path = Path(configured).expanduser()
    if path.is_dir() or not path.suffix:
        return path if path.name == corpus_id() else path / corpus_id() / default_name
    if path.parent.name == corpus_id():
        return path
    return path.parent / corpus_id() / path.name


def corpus_dir_path(environment_name: str, default_name: str) -> Path:
    configured = os.getenv(environment_name)
    if not configured:
        return corpus_data_dir() / default_name
    path = Path(configured).expanduser()
    if path.name == corpus_id():
        return path / default_name
    if path.name == default_name:
        return path.parent / corpus_id() / default_name
    return path / corpus_id() / default_name
