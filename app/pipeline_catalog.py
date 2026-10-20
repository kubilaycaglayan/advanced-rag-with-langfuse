"""Read and validate the versioned query-flow catalog."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from .identity import canonical_json
except ImportError:
    from identity import canonical_json

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "pipelines.md"
RELEASES = ROOT / "pipelines.sha256"
FINGERPRINT_KEYS = ("id", "engine", "flow", "agent", "settings", "prompts", "index", "models")
VERSION_KEYS = set(FINGERPRINT_KEYS) | {"status", "notes", "code"}


def fingerprint(block: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json({key: block.get(key) for key in FINGERPRINT_KEYS}).encode()).hexdigest()


@dataclass(frozen=True)
class PipelineCatalog:
    default: str
    versions: dict[str, dict[str, Any]]
    releases: dict[str, str]

    def get(self, version: str | None = None) -> dict[str, Any]:
        key = version or self.default
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
        if not isinstance(block["settings"], dict) or not isinstance(block["prompts"], dict) or not isinstance(block["index"], dict) or not isinstance(block["models"], dict):
            raise ValueError(f"{version}: invalid settings/prompts/index/models")
        if set(block["index"]) != {"collection", "corpus_checksum"}:
            raise ValueError(f"{version}: index needs collection and corpus_checksum")
        if block["engine"] == "agent" and not isinstance(block["agent"], dict):
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
