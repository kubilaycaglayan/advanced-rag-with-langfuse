"""retrieval / queries responsibilities."""
from __future__ import annotations

from app.cache.intermediate import cache_value as _cache_value
from app.corpus_profiles import profile_prompt
from app.models.local import local_generate
from app.observability import observation as _observe
from app.observability import update as _update
from app.pipelines.config import ResolvedPipelineConfig
from app.prompt_templates import PROMPT_TEMPLATES
from concurrent.futures import ThreadPoolExecutor
from typing import Any
import contextvars


def transform_query(question: str, config: ResolvedPipelineConfig) -> tuple[str | None, list[str], str | None]:
    mode = config.retrieval_mode

    def transform_cache_key(operation: str) -> dict[str, Any]:
        return {"query": question, "model": config.generation_model.name,
                "model_revision": config.generation_model.revision,
                "temperature": config.generation.temperature,
                "context_length": config.generation.context_length,
                "output_budgets": list(config.generation.output_budgets), "operation": operation}

    def hyde() -> str:
        with _observe("HyDE transformation", input=question) as obs:
            messages = [
                {"role": "system", "content": profile_prompt("hyde_system", PROMPT_TEMPLATES["hyde_system"])}, {"role": "user", "content": question}]
            hypothetical = _cache_value("query", "hyde", transform_cache_key("hyde"),
                input={"query": question, "operation": "hyde"},
                compute=lambda: local_generate(messages, config.generation_model.name, config.generation.output_budgets,
                    config.generation.temperature, config.generation.context_length,
                    name="hypothetical document generation"))
            _update(obs, output=hypothetical)
        return hypothetical

    def expansion() -> list[str]:
        with _observe("query expansion", input=question) as obs:
            # Prompts may reference {{expansion_count}}; templates without it ignore the value.
            messages = [
                {"role": "system", "content": profile_prompt("query_expansion_system", PROMPT_TEMPLATES["query_expansion_system"]).replace("{{expansion_count}}", str(config.expansion_count))},
                {"role": "user", "content": question}]
            raw = _cache_value("query", "expansion", transform_cache_key("expansion"),
                input={"query": question, "operation": "expansion"},
                compute=lambda: local_generate(messages, config.generation_model.name, config.generation.output_budgets,
                    config.generation.temperature, config.generation.context_length,
                    name="literary query generation"))
            _update(obs, output=raw)
        alternatives = list(dict.fromkeys(line.strip().lstrip("-•0123456789. )") for line in raw.splitlines() if line.strip()))
        alternatives = [q for q in alternatives if q and q.casefold() != question.casefold()][:config.expansion_count]
        if len(alternatives) != config.expansion_count:
            raise ValueError(f"query expansion must return {config.expansion_count} distinct alternative queries")
        return alternatives

    def grammar() -> str:
        with _observe("grammar correction", input=question) as obs:
            messages = [
                {"role": "system", "content": profile_prompt("grammar_system", PROMPT_TEMPLATES["grammar_system"])}, {"role": "user", "content": question}]
            corrected = _cache_value("query", "grammar", transform_cache_key("grammar"),
                input={"query": question, "operation": "grammar"},
                compute=lambda: local_generate(messages, config.generation_model.name, config.generation.output_budgets,
                    config.generation.temperature, config.generation.context_length,
                    name="grammar corrected query generation"))
            _update(obs, output=corrected)
        return corrected

    # hyde=false keeps every other step of the mode and only drops the hypothetical document.
    steps = {"hypothetical": hyde if config.hyde and mode in {"hyde", "hyde_query_expansion", "full"} else None,
             "alternatives": expansion if mode in {"query_expansion", "hyde_query_expansion", "full"} else None,
             "corrected": grammar if mode == "full" else None}
    steps = {key: step for key, step in steps.items() if step}
    if config.parallel_transformations and len(steps) > 1:
        # The rewrites are independent requests; Ollama answers them together when OLLAMA_NUM_PARALLEL allows it.
        # Each runs in a copy of this context, so its Langfuse spans stay under the current trace.
        with ThreadPoolExecutor(max_workers=len(steps)) as pool:
            futures = {key: pool.submit(contextvars.copy_context().run, step) for key, step in steps.items()}
            done = {key: future.result() for key, future in futures.items()}
    else:
        done = {key: step() for key, step in steps.items()}
    return done.get("hypothetical"), done.get("alternatives", []), done.get("corrected")


def prompted(system: str, user: str, config: ResolvedPipelineConfig, name: str) -> str:
    """One generation-model request using the active corpus's local template."""
    messages = [{"role": "system", "content": profile_prompt(system, PROMPT_TEMPLATES[system])},
                {"role": "user", "content": user}]
    return local_generate(messages, config.generation_model.name, config.generation.output_budgets,
                   config.generation.temperature, config.generation.context_length, name=name)
