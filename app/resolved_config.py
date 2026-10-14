"""Typed, serializable resolved pipeline configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Any, Mapping
from urllib.error import URLError
from urllib.request import urlopen


@dataclass(frozen=True)
class ModelIdentity:
    name: str
    digest: str | None = None
    revision: str | None = None


@dataclass(frozen=True)
class GenerationSettings:
    temperature: float = 0.0
    context_length: int = 8192
    output_budgets: tuple[int, ...] = (256, 512, 1024)


@dataclass(frozen=True)
class EvaluatorSettings:
    model: ModelIdentity = ModelIdentity("qwen3:8b")
    temperature: float = 0.0
    stream: bool = False
    response_format: str = "json"


@dataclass(frozen=True)
class ResolvedPipelineConfig:
    retrieval_mode: str = "baseline"
    candidate_count: int = 30
    top_k: int = 10
    passage_chars: int = 1200
    embedding_model: ModelIdentity = ModelIdentity("sentence-transformers/multi-qa-MiniLM-L6-cos-v1")
    reranker_model: ModelIdentity = ModelIdentity("cross-encoder/ms-marco-MiniLM-L-6-v2")
    generation_model: ModelIdentity = ModelIdentity("qwen3:8b")
    generation: GenerationSettings = GenerationSettings()
    rrf_constant: int = 60
    corpus_checksum: str = ""
    prompt_hashes: Mapping[str, str] | None = None

    def __post_init__(self) -> None:
        if self.retrieval_mode not in {"baseline", "hyde", "query_expansion", "hyde_query_expansion"}:
            raise ValueError(f"unsupported retrieval mode: {self.retrieval_mode}")
        if not 1 <= self.candidate_count <= 100:
            raise ValueError("candidate_count must be between 1 and 100")
        if not 1 <= self.top_k <= self.candidate_count:
            raise ValueError("top_k must be between 1 and candidate_count")
        if self.passage_chars < 1 or self.rrf_constant < 1:
            raise ValueError("passage_chars and rrf_constant must be positive")

    def manifest(self) -> dict[str, Any]:
        value = asdict(self)
        value["generation"]["output_budgets"] = list(self.generation.output_budgets)
        value["prompt_hashes"] = dict(self.prompt_hashes or {})
        return value


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
