# Backend and server ownership

This map describes the target of the organization refactor. Until the moves land,
use the current-owner column to locate code. The UI submodule is a separate,
unchanged HTTP consumer.

| Responsibility | Current owner | Intended owner |
| --- | --- | --- |
| Agent coordinator | `app/agent.py:run_agent` | `app/agent/runner.py` |
| Agent settings and state | `AgentSettings`, `AgentState` | `app/agent/state.py` |
| Model-facing tool dispatch and schemas | `_tool_*`, `_run_tool`, `_tool_specs` | `app/agent/tools/` |
| Prechecks and their messages | `_connection_precheck`, `_true_account_precheck`, `_sequence_precheck`, `_moment_precheck`, `_premise_probe` | `app/agent/prechecks.py` |
| Submission verification and synthesis | `_verify_submission`, `_synthesize`, `_finish`, `_forced_answer` | `app/agent/submission.py` |
| Evidence and provenance | evidence/focus methods on `AgentState` | `app/context/evidence.py` |
| Conversation formatting | `_compact`, final conversation handoff | `app/context/conversation.py` |
| Search and query transformation | `app/pipeline.py`, reusable search helpers in `agent.py` | `app/retrieval/` |
| Provider access and model loading | `_agent_chat`, `_ollama`, `_embedder`, `_reranker` | `app/models/` |
| EPUB extraction, chunking, index building | `app/indexer.py`, `scenes.py`, `entities.py` | `app/indexing/` |
| Index manifest persistence | index functions in `app/experiment_store.py` | `app/indexing/manifests.py` |
| Catalog, resolution, execution adapter | `pipeline_catalog.py`, `pipeline_resolver.py`, `resolved_config.py`, `pipeline_runner.py` | `app/pipelines/` |
| Shared question execution | execution/cache setup in `main.py` and `experiments.py` | `app/answering/` |
| HTTP routes and request models | `app/main.py` | `app/api/` |
| Experiment selection, execution, queue, CLI | `app/experiments.py` | `app/experiments/` |
| Experiment persistence | execution functions in `app/experiment_store.py` | `app/experiments/store.py` |
| Evaluation and review | `evaluation.py`, `evaluator_specs.py`, `quality_metrics.py`, `quality_review.py`, `quality_evaluators/` | `app/evaluation/` |
| Answer and intermediate caches | `answer_cache.py`, `intermediate_cache.py` | `app/cache/` |
| Corpus identity and profile assets | `corpus_config.py`, `corpus_profiles/` | Retain cohesive existing owners |
| Trace and usage reporting | `observability.py`, agent usage helpers | Observability plus provider usage normalization |
| Express routes, ownership, response mapping | `frontends/millennium/server.js` | `frontends/millennium/server/` |

## Dependency direction

Configuration and shared data types are leaves: they do not import execution,
HTTP routes, or experiment orchestration. Corpus profiles supply corpus behavior
without depending on API transport. Model clients depend on configuration and
observability, never the agent runner. Retrieval depends on model access, cache,
configuration, and index lookup; it does not import agent state or conversation.
Context stores evidence and formats conversation without invoking providers.
Agent tools combine retrieval and context; the runner coordinates tools,
prechecks, provider calls, and submission. Answer execution coordinates a resolved
pipeline and caches. HTTP and experiments call answer execution while retaining
their distinct admission, cache, trace, dataset, and preparation policies.

Cache implementations must not import their callers. Shared cache identity
construction belongs with answer execution or pipeline identity. Observability
must not import agent, HTTP, or experiment orchestration. Boundary types belong
with their producing subsystem unless both sides need a small shared definition.
Avoid import cycles rather than hiding them with broad ImportError fallbacks.

Index-manifest code retains the existing SQLite schema and rows. Moving ownership
does not authorize changing storage or rebuilding indexes. Preserve the source
text of source-hashed extraction and merge functions. Keep model-visible builder
names and literal values stable in the instruction manifest across module moves.
