"""Read and validate the versioned query-flow catalog."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from dataclasses import fields
from pathlib import Path
from typing import Any

try:
    from .identity import canonical_json
    from .resolved_config import ResolvedPipelineConfig
except ImportError:
    from identity import canonical_json
    from resolved_config import ResolvedPipelineConfig

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "pipelines.md"
RELEASES = ROOT / "pipelines.sha256"
FINGERPRINT_KEYS = ("id", "engine", "flow", "agent", "settings", "prompts", "index", "models")
VERSION_KEYS = set(FINGERPRINT_KEYS) | {"status", "notes", "code"}
MODEL_KEYS = {"embedding_model", "reranker_model", "generation_model", "scene_summary_model"}
IDENTITY_KEYS = {"corpus_checksum", "prompt_hashes"}
V2_SETTINGS = {"retrieval_mode", "hyde", "expansion_count", "name_completion", "scene_search_hits",
               "scene_window", "scene_stride", "passage_chars", "min_passage_chars", "passage_overlap",
               "generation", "parallel_transformations", "scene_thinking"}
AGENT_KEYS = {"model", "tools", "max_turns", "max_tool_calls", "min_tool_calls", "timeout_seconds",
              "context_length", "num_predict", "think", "snippet_chars", "instruction_fingerprint"}
AGENT_OPTIONAL_KEYS = {"query_aware_reranking", "scene_candidate_count", "initial_scene_probe", "provider"}


def fingerprint(block: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json({key: block.get(key) for key in FINGERPRINT_KEYS}).encode()).hexdigest()


@dataclass(frozen=True)
class PipelineCatalog:
    default: str
    versions: dict[str, dict[str, Any]]
    releases: dict[str, str]

    def get(self, version: str | None = None) -> dict[str, Any]:
        key = self.default if version is None else version
        if key not in self.versions:
            raise ValueError(f"unknown pipeline {key!r}")
        return self.versions[key]

    def check_fingerprints(self) -> None:
        for version, digest in self.releases.items():
            block = self.versions.get(version)
            if block is None or block["status"] == "draft":
                raise ValueError(f"fingerprint line names missing or draft version {version}")
            if fingerprint(block) != digest:
                raise ValueError(f"{version}: publish a new version; a released version is immutable")
        for version, block in self.versions.items():
            if block["status"] in {"released", "retired"} and version not in self.releases:
                raise ValueError(f"{version}: released version has no fingerprint")


def load_catalog(path: Path = CATALOG, releases_path: Path = RELEASES) -> PipelineCatalog:
    source = path.read_text(encoding="utf-8")
    blocks = list(re.finditer(r"```json\s*\n(.*?)\n```", source, re.DOTALL))
    if not blocks:
        raise ValueError("pipeline catalog has no JSON header")
    try:
        header = json.loads(blocks[0][1])
    except json.JSONDecodeError as exc:
        raise ValueError("invalid pipeline catalog header") from exc
    if set(header) != {"default"} or not isinstance(header["default"], str):
        raise ValueError("pipeline catalog header must contain only a string default")
    versions: dict[str, dict[str, Any]] = {}
    for match in blocks[1:]:
        preceding = source[:match.start()].splitlines()
        heading = next((line for line in reversed(preceding) if line.startswith("## ")), "")
        if not heading.startswith("## Version "):
            raise ValueError("each pipeline block requires a Version heading")
        try:
            block = json.loads(match[1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON under {heading}") from exc
        unknown = set(block) - VERSION_KEYS
        missing = (VERSION_KEYS - {"code", "notes"}) - set(block)
        if unknown or missing:
            raise ValueError(f"{heading}: unknown fields {sorted(unknown)}; missing fields {sorted(missing)}")
        version = block["id"]
        if not isinstance(version, str) or not re.fullmatch(r"v[1-9]\d*(?:\.\d+)?", version):
            raise ValueError(f"invalid pipeline id {version!r}")
        if version in versions:
            raise ValueError(f"duplicate pipeline id {version}")
        if block["status"] not in {"draft", "released", "retired"} or block["engine"] not in {"fixed", "agent"}:
            raise ValueError(f"{version}: invalid status or engine")
        if not isinstance(block["flow"], list) or not block["flow"] or not all(isinstance(step, dict) and
                set(step) <= {"name", "when", "parallel"} and ("name" in step or "parallel" in step)
                for step in block["flow"]):
            raise ValueError(f"{version}: invalid flow")
        if any(("name" in step and (not isinstance(step["name"], str) or not step["name"])) or
               ("when" in step and not isinstance(step["when"], str)) or
               ("parallel" in step and (not isinstance(step["parallel"], list) or
                not all(isinstance(name, str) and name for name in step["parallel"])))
               for step in block["flow"]):
            raise ValueError(f"{version}: invalid flow stage")
        if not isinstance(block["settings"], dict) or not isinstance(block["prompts"], dict) or not isinstance(block["index"], dict) or not isinstance(block["models"], dict):
            raise ValueError(f"{version}: invalid settings/prompts/index/models")
        if set(block["index"]) != {"collection", "corpus_checksum"}:
            raise ValueError(f"{version}: index needs collection and corpus_checksum")
        known_settings = {field.name for field in fields(ResolvedPipelineConfig)} - MODEL_KEYS - IDENTITY_KEYS
        required_settings = known_settings if block["engine"] == "fixed" else V2_SETTINGS
        if set(block["settings"]) != required_settings:
            raise ValueError(f"{version}: settings must match engine settings; missing={sorted(required_settings - set(block['settings']))}, extra={sorted(set(block['settings']) - required_settings)}")
        if set(block["models"]) != MODEL_KEYS:
            raise ValueError(f"{version}: models must list generation, embedding, reranker, and scene summary")
        if block["engine"] == "agent" and block["prompts"]:
            raise ValueError(f"{version}: agent must not pin managed RAG prompts")
        if block["engine"] == "fixed" and len(block["prompts"]) != 7:
            raise ValueError(f"{version}: fixed pipeline must pin all seven managed prompts")
        if block["engine"] == "agent" and (not isinstance(block["agent"], dict) or
                not AGENT_KEYS <= set(block["agent"]) or
                set(block["agent"]) - AGENT_KEYS - AGENT_OPTIONAL_KEYS):
            raise ValueError(f"{version}: agent settings required")
        if block["engine"] == "fixed" and block["agent"] is not None:
            raise ValueError(f"{version}: fixed flow cannot have agent settings")
        versions[version] = block
    if header["default"] not in versions or versions[header["default"]]["status"] != "released":
        raise ValueError("default must name a released pipeline")
    releases: dict[str, str] = {}
    for line in releases_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[1]) or parts[0] in releases:
            raise ValueError(f"invalid or duplicate fingerprint line: {line}")
        releases[parts[0]] = parts[1]
    catalog = PipelineCatalog(header["default"], versions, releases)
    catalog.check_fingerprints()
    return catalog


def write_fingerprints(path: Path = CATALOG, releases_path: Path = RELEASES) -> None:
    """Explicit release operation; runtime and tests only compare fingerprints."""
    source = path.read_text(encoding="utf-8")
    blocks = [json.loads(value) for value in re.findall(r"```json\s*\n(.*?)\n```", source, re.DOTALL)[1:]]
    releases_path.write_text("".join(f"{block['id']} {fingerprint(block)}\n" for block in blocks
                                     if block["status"] in {"released", "retired"}), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-fingerprints", action="store_true")
    args = parser.parse_args()
    if args.write_fingerprints:
        write_fingerprints()
    else:
        load_catalog()
