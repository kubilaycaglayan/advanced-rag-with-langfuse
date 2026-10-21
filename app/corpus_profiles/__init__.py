"""Load a corpus's Python behavior profile from its declarative corpus metadata."""
from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any

try:
    from ..corpus_config import corpus_config
    from ..identity import canonical_json
except ImportError:
    from corpus_config import corpus_config
    from identity import canonical_json


@dataclass(frozen=True)
class CorpusProfile:
    id: str
    language: str
    name_pattern: str
    name_word_pattern: str
    agent_context: str
    translation_exception: str = ""
    chapter_reference_pattern: str = r"^\s*In Chapter \d+,\s*"
    prompt_overrides: dict[str, str] | None = None
    agent_prompt_name: str = "agent-system.txt"

    def identity(self) -> str:
        material = {"id": self.id, "language": self.language, "name_pattern": self.name_pattern,
                    "name_word_pattern": self.name_word_pattern,
                    "agent_context": self.agent_context, "translation_exception": self.translation_exception,
                    "chapter_reference_pattern": self.chapter_reference_pattern,
                    "prompt_overrides": self.prompt_overrides or {},
                    "agent_prompt": (Path(__file__).parent / self.id / self.agent_prompt_name).read_text(encoding="utf-8")}
        return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def load_profile(profile_id: str | None = None) -> CorpusProfile:
    config = corpus_config()
    selected = profile_id or config.profile_id
    if selected != config.profile_id:
        raise ValueError(f"profile {selected!r} does not match selected corpus {config.id!r}")
    module = importlib.import_module(f".{selected}.profile", __name__)
    profile = module.PROFILE
    if not isinstance(profile, CorpusProfile) or profile.id != selected:
        raise ValueError(f"invalid corpus profile {selected!r}")
    return profile


def profile_identity() -> str:
    return load_profile().identity()


def agent_prompt() -> str:
    profile = load_profile()
    return (Path(__file__).parent / profile.id / profile.agent_prompt_name).read_text(encoding="utf-8")


def prompt_identity() -> str:
    profile = load_profile()
    try:
        from ..prompt_templates import PROMPT_TEMPLATES
    except ImportError:
        from prompt_templates import PROMPT_TEMPLATES
    templates = {**PROMPT_TEMPLATES, **(profile.prompt_overrides or {})}
    material = {"agent_prompt": agent_prompt(), "templates": templates}
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def profile_prompt(name: str, fallback: str) -> str:
    return (load_profile().prompt_overrides or {}).get(name, fallback)


def langfuse_enabled() -> bool:
    setting = os.getenv("LANGFUSE_ENABLED")
    legacy_tracing_setting = os.getenv("LANGFUSE_TRACING_ENABLED")
    config = corpus_config().langfuse
    credentials_present = bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))
    configured = setting.strip().casefold() in {"1", "true", "yes", "on"} if setting is not None else bool(config.get("enabled", True))
    if legacy_tracing_setting is not None and legacy_tracing_setting.strip().casefold() in {"0", "false", "no", "off"}:
        configured = False
    return configured and credentials_present
