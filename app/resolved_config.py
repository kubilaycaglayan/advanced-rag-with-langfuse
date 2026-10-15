"""Typed, serializable resolved pipeline configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import replace
from functools import lru_cache
import json
import os
import math
from typing import Any, Mapping
from urllib.error import URLError
from urllib.request import urlopen


@dataclass(frozen=True)
class ModelIdentity:
    name: str
    digest: str | None = None
    revision: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("model name must be a non-empty string")
        if self.digest is not None and not isinstance(self.digest, str):
            raise ValueError("model digest must be a string when provided")
        if self.revision is not None and not isinstance(self.revision, str):
            raise ValueError("model revision must be a string when provided")


@dataclass(frozen=True)
class GenerationSettings:
    temperature: float = 0.0
    context_length: int = 8192
    output_budgets: tuple[int, ...] = (4096, 8192)

    def __post_init__(self) -> None:
        if isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float)) or not math.isfinite(self.temperature) or self.temperature < 0:
            raise ValueError("generation temperature must be a finite non-negative number")
        if isinstance(self.context_length, bool) or not isinstance(self.context_length, int) or self.context_length < 1:
            raise ValueError("generation context_length must be a positive integer")
        if not self.output_budgets or any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in self.output_budgets):
            raise ValueError("generation output_budgets must contain positive integers")


@dataclass(frozen=True)
class EvaluatorSettings:
    model: ModelIdentity = ModelIdentity("qwen3:8b")
    temperature: float = 0.0
    stream: bool = False
    response_format: str = "json"


@dataclass(frozen=True)
class ResolvedPipelineConfig:
    retrieval_mode: str = "full"
    candidate_count: int = 30
    top_k: int = 10
    passage_chars: int = 1200
    embedding_model: ModelIdentity = ModelIdentity("sentence-transformers/multi-qa-MiniLM-L6-cos-v1")
    reranker_model: ModelIdentity = ModelIdentity("cross-encoder/ms-marco-MiniLM-L-6-v2")
    generation_model: ModelIdentity = ModelIdentity("qwen3:8b")
    generation: GenerationSettings = GenerationSettings()
    rrf_constant: int = 60
    min_passage_chars: int = 400
    passage_overlap: int = 0
    expansion_count: int = 3
    answer_thinking: bool = False
    name_completion: bool = True
    name_completion_hits: int = 300
    low_confidence_score: float | None = 2.0
    low_confidence_top_k: int = 15
    wide_candidate_count: int = 100
    wide_trigger_score: float | None = 3.5
    wide_override_margin: float | None = 2.0
    wide_max_hits: int = 3
    corpus_checksum: str = ""
    prompt_hashes: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.embedding_model, ModelIdentity) or not isinstance(self.reranker_model, ModelIdentity) or not isinstance(self.generation_model, ModelIdentity):
            raise ValueError("embedding_model, reranker_model, and generation_model must be model identities")
        if not isinstance(self.generation, GenerationSettings):
            raise ValueError("generation must be GenerationSettings")
        for name, number in (("candidate_count", self.candidate_count), ("top_k", self.top_k), ("passage_chars", self.passage_chars), ("rrf_constant", self.rrf_constant),
                             ("min_passage_chars", self.min_passage_chars), ("passage_overlap", self.passage_overlap), ("expansion_count", self.expansion_count),
                             ("low_confidence_top_k", self.low_confidence_top_k), ("wide_candidate_count", self.wide_candidate_count), ("wide_max_hits", self.wide_max_hits), ("name_completion_hits", self.name_completion_hits)):
            if isinstance(number, bool) or not isinstance(number, int):
                raise ValueError(f"{name} must be an integer")
        if not isinstance(self.retrieval_mode, str):
            raise ValueError("retrieval_mode must be a string")
        if not isinstance(self.answer_thinking, bool) or not isinstance(self.name_completion, bool):
            raise ValueError("answer_thinking and name_completion must be booleans")
        if self.low_confidence_score is not None and (isinstance(self.low_confidence_score, bool) or not isinstance(self.low_confidence_score, (int, float))
                                                      or not math.isfinite(self.low_confidence_score)):
            raise ValueError("low_confidence_score must be a finite number or null")
        if self.wide_trigger_score is not None and (isinstance(self.wide_trigger_score, bool) or not isinstance(self.wide_trigger_score, (int, float))
                                                    or not math.isfinite(self.wide_trigger_score)):
            raise ValueError("wide_trigger_score must be a finite number or null")
        if self.wide_override_margin is not None and (isinstance(self.wide_override_margin, bool) or not isinstance(self.wide_override_margin, (int, float))
                                                      or not math.isfinite(self.wide_override_margin) or self.wide_override_margin < 0):
            raise ValueError("wide_override_margin must be a non-negative finite number or null")
        if not isinstance(self.corpus_checksum, str):
            raise ValueError("corpus_checksum must be a string")
        if self.prompt_hashes is not None and (not isinstance(self.prompt_hashes, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in self.prompt_hashes.items())):
            raise ValueError("prompt_hashes must map strings to strings")
        if self.retrieval_mode not in {"baseline", "hyde", "query_expansion", "hyde_query_expansion", "full"}:
            raise ValueError(f"unsupported retrieval mode: {self.retrieval_mode}")
        if not 1 <= self.candidate_count <= 100:
            raise ValueError("candidate_count must be between 1 and 100")
        if not 1 <= self.top_k <= self.candidate_count:
            raise ValueError("top_k must be between 1 and candidate_count")
        if not 1 <= self.low_confidence_top_k <= self.candidate_count:
            raise ValueError("low_confidence_top_k must be between 1 and candidate_count")
        if not 0 <= self.wide_candidate_count <= 200:
            raise ValueError("wide_candidate_count must be between 0 and 200")
        if not 0 <= self.name_completion_hits <= 1000:
            raise ValueError("name_completion_hits must be between 0 and 1000")
        if not 0 <= self.wide_max_hits <= 30:
            raise ValueError("wide_max_hits must be between 0 and 30")
        if self.passage_chars < 1 or self.rrf_constant < 1:
            raise ValueError("passage_chars and rrf_constant must be positive")
        if self.min_passage_chars < 0:
            raise ValueError("min_passage_chars must not be negative")
        if not 0 <= self.passage_overlap <= 5:
            raise ValueError("passage_overlap must be between 0 and 5")
        if self.passage_overlap and not self.min_passage_chars:
            raise ValueError("passage_overlap requires min_passage_chars (paragraph merging)")
        if not 1 <= self.expansion_count <= 10:
            raise ValueError("expansion_count must be between 1 and 10")

    def manifest(self) -> dict[str, Any]:
        value = asdict(self)
        value["generation"]["output_budgets"] = list(self.generation.output_budgets)
        value["prompt_hashes"] = dict(self.prompt_hashes or {})
        return value

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None = None) -> "ResolvedPipelineConfig":
        """Validate a JSON config without accepting unknown or identity fields."""
        value = dict(value or {})
        defaults: dict[str, Any] = {
            "retrieval_mode": "full",
            "candidate_count": 30,
            "top_k": 10,
            "passage_chars": int(os.getenv("PASSAGE_CHARS", "1200")),
            "min_passage_chars": int(os.getenv("MIN_PASSAGE_CHARS", "400")),
            "embedding_model": os.getenv("EMBEDDING_MODEL", "sentence-transformers/multi-qa-MiniLM-L6-cos-v1"),
            "reranker_model": os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"),
            "generation_model": os.getenv("GENERATION_MODEL", "qwen3:8b"),
        }
        defaults.update(value)
        value = defaults
        allowed = {"retrieval_mode", "candidate_count", "top_k", "passage_chars", "embedding_model", "reranker_model", "generation_model", "generation", "rrf_constant",
                   "min_passage_chars", "passage_overlap", "expansion_count", "answer_thinking", "name_completion", "name_completion_hits",
                   "low_confidence_score", "low_confidence_top_k", "wide_candidate_count", "wide_trigger_score", "wide_override_margin", "wide_max_hits", "corpus_checksum", "prompt_hashes"}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown config fields: {', '.join(sorted(unknown))}")
        for key in ("embedding_model", "reranker_model", "generation_model"):
            if key in value and isinstance(value[key], str):
                value[key] = ModelIdentity(value[key])
            elif key in value and isinstance(value[key], Mapping):
                value[key] = ModelIdentity(**value[key])
            elif key in value:
                raise ValueError(f"{key} must be a model name or model identity object")
        if "generation" in value:
            generation = value["generation"]
            if not isinstance(generation, Mapping):
                raise ValueError("generation must be an object")
            unknown_generation = set(generation) - {"temperature", "context_length", "output_budgets"}
            if unknown_generation:
                raise ValueError(f"unknown generation fields: {', '.join(sorted(unknown_generation))}")
            generation = dict(generation)
            if "output_budgets" in generation:
                generation["output_budgets"] = tuple(generation["output_budgets"])
            value["generation"] = GenerationSettings(**generation)
        return cls(**value)


def resolve_ollama_model(model_name: str, base_url: str = "http://127.0.0.1:11434") -> ModelIdentity:
    """Resolve a local Ollama tag to its content digest for reproducible manifests."""
    try:
        with urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=5) as response:
            payload = json.load(response)
    except (OSError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"cannot resolve Ollama model identity from {base_url}") from exc
    for model in payload.get("models", []):
        if model.get("name") == model_name:
            digest = model.get("digest")
            if not digest:
                raise RuntimeError(f"Ollama model {model_name!r} has no reported digest")
            return ModelIdentity(name=model_name, digest=digest)
    raise RuntimeError(f"Ollama model {model_name!r} is not installed")


@lru_cache(maxsize=16)
def _resolve_huggingface_revision(model_name: str) -> str | None:
    """Resolve the current Hub commit, falling back to a locally cached snapshot."""
    try:
        from huggingface_hub import HfApi
        revision = HfApi().model_info(model_name, timeout=5).sha
        if revision:
            return revision
    except Exception:
        pass
    try:
        from huggingface_hub import try_to_load_from_cache
        cached_config = try_to_load_from_cache(model_name, "config.json")
        if isinstance(cached_config, str):
            return __import__("pathlib").Path(cached_config).parent.name
    except Exception:
        pass
    return None


def resolve_pipeline_model_identities(config: ResolvedPipelineConfig) -> ResolvedPipelineConfig:
    """Pin Hub models to commit SHAs when the Hub or local cache can identify them."""
    def resolve(identity: ModelIdentity) -> ModelIdentity:
        if identity.revision:
            return identity
        revision = _resolve_huggingface_revision(identity.name)
        return replace(identity, revision=revision) if revision else identity
    return replace(config, embedding_model=resolve(config.embedding_model), reranker_model=resolve(config.reranker_model))
