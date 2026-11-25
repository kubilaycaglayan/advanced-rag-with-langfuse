# Backend and Express code map

The supported pipeline is v2.16. The UI at `frontends/millennium/ui/` is an
unchanged submodule and consumes the Express HTTP API.

## Following a question

`app/main.py` exposes the FastAPI application assembled in `api/application.py`.
`api/questions.py` validates and prepares requests, reserves admission locks,
and sends ordinary or streaming responses. `answering/interactive.py` owns
interactive tracing and cache coordination. `answering/execution.py` executes
the resolved agent and maps its answer, evidence, usage, and events to the shared
result contract. Experiments use that same execution function while retaining
their own dataset, cache, tracing, and index-preparation policies.

`agent/runner.py` coordinates prechecks, model turns, tool calls, verification,
and budget exits. It does not implement search or HTTP transport. Tools update
`context/evidence.py`, which stores evidence, deliberate focus, and retrieval
provenance. Conversation compaction and final handoff live in `context/`.

| Change | Owner |
| --- | --- |
| Agent settings and execution state | `app/agent/state.py` |
| Main agent loop and precheck ordering | `app/agent/runner.py` |
| Corpus-independent agent instructions | `app/agent/prompts.py` |
| Instruction integrity manifest | `app/agent/instructions.py` |
| Tool schemas | `app/agent/schemas.py` |
| Tool argument handling and dispatch | `app/agent/protocol.py`, `app/agent/tools/dispatch.py` |
| Search, scene, entity, reading, true-account, and submission tools | Corresponding modules in `app/agent/tools/` |
| Prechecks and their message builders | `app/agent/prechecks.py` |
| Coverage of sequence stages | `app/agent/tools/coverage.py` |
| Verification, synthesis, citation finalization, and forced answers | `app/agent/submission.py` |
| Evidence storage, focus, and query provenance | `app/context/evidence.py` |
| Passage formatting and conversation compaction | `app/context/citations.py`, `app/context/conversation.py` |
| Protected final conversation handoff | `app/context/agent_final_handoff.py` |
| Keyword/name indexes and search | `app/retrieval/search.py` |
| Query transformation and scene-moment selection | `app/retrieval/queries.py`, `app/retrieval/moments.py` |
| Passage, scene, and entity lookup | `app/retrieval/passages.py`, `scenes.py`, `entities.py` |
| Shared search payload type | `app/retrieval/types.py` |
| Agent provider clients and usage | `app/models/agent.py` |
| Local generation for query transformations | `app/models/local.py` |
| Embedding and reranking access | `app/models/retrieval.py` |
| EPUB extraction, chunking, and passage index building | `app/indexing/passages.py` |
| Scene and entity index building | `app/indexing/scenes.py`, `app/indexing/entities.py` |
| Index-manifest persistence | `app/indexing/manifests.py` |
| Catalog, resolved settings, and version resolution | `app/pipelines/catalog.py`, `config.py`, `resolver.py` |
| Shared answer execution and cache identity | `app/answering/execution.py`, `cache_identity.py` |
| Answer and intermediate caches | `app/cache/answers.py`, `app/cache/intermediate.py` |
| API schemas, access checks, and route groups | `app/api/` |
| Dataset snapshots and item/session selection | `app/experiments/datasets.py` |
| Dataset execution and artifacts | `app/experiments/execution.py` |
| Queue, retries, and execution persistence | `app/experiments/queue.py`, `store.py` |
| Experiment metadata, fingerprints, and trace upload | `app/experiments/metadata.py`, `telemetry.py` |
| Experiment command line | `app/experiments/cli.py`, `__main__.py` |
| Shared SQLite connection and unchanged schema | `app/storage.py` |
| Judges, evaluator definitions, metrics, and review | `app/evaluation/` |
| Native evaluator installation and submission | `app/quality_evaluators/` |
| Corpus configuration, assets, and overrides | `app/corpus_config.py`, `app/corpus_profiles/` |
| Trace scopes and cache observations | `app/observability.py` |
| Express entry point and development startup | `frontends/millennium/server.js`, `server/development.js` |
| Express app assembly and static serving | `frontends/millennium/server/application.js` |
| Question forwarding and streaming | `frontends/millennium/server/questions.js` |
| Feedback and trace access | `frontends/millennium/server/traces.js` |
| Browser ownership, client IP, and authentication | `frontends/millennium/server/security.js` |
| Response mapping and server configuration | `frontends/millennium/server/responses.js`, `config.js` |

## Dependency boundaries

Retrieval does not import agent state, conversation, or the agent loop. It uses
model access, cache, configuration, and index lookup. Model providers never
import the agent runner. Context stores and formats information without calling
providers. Agent tools combine retrieval with evidence state; the runner
coordinates tools, prechecks, provider calls, and submission. API transport stays
outside retrieval and agent logic.

Cache implementations and observability do not import their callers. Shared
cache identity belongs to answering. Corpus profiles supply corpus behavior
without depending on API transport. Configuration and shared payload types do
not import orchestration. Internal imports use the `app` package; no top-level
fallback import path is supported.

Index manifests retain the existing SQLite table and rows. Moving ownership does
not authorize rebuilding indexes. Source-hashed extraction and merge functions
retain their source text. Instruction-builder names and literal values remain
stable in the multi-module instruction manifest. Read the verification report
for the selected experiment sample and its limits.
