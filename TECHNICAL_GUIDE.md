# Millennium v2.16 technical guide

## Supported workflow

The only supported pipeline is **v2.16**. HTTP questions and dataset experiments
share `app/pipeline_resolver.py` and `app/pipeline_runner.py`. Older pipeline
versions and the fixed engine are unsupported. Git history contains their code.

The agent gathers evidence through 13 tools, runs connection/scene/true-account/
sequence/moment/premise checks, verifies submissions, and synthesizes cited
answers. On timeout, turn limit, or tool limit it answers from the compacted
conversation without tools. See [the catalog](pipelines.md) and
[tool reference](docs/pipeline-v2.16-tools.md).

The catalog defaults to local Ollama `qwen3.6:35b`. The Millennium frontend
explicitly selects OpenAI `gpt-6-luna` with high reasoning effort. Both choices
use v2.16. Query transformations still use the configured local generation
model, and embeddings/reranking stay local.

## Configuration

Supply `settings` to `POST /ask` or an experiment. Omit `pipeline` to follow
the catalog default, or send `"pipeline":"v2.16"`.

| Setting | Purpose |
| --- | --- |
| `agent_provider` | `ollama` or `openai` |
| `agent_model` | Local Ollama model override |
| `agent_think` | Local thinking toggle |
| `agent_context_length` | Positive local context length |
| `agent_reasoning_effort` | OpenAI: none, low, medium, high, xhigh, max |
| `automatic_scene_search` | Enable/disable initial scene probe |
| `scene_candidate_count` | Scene candidate pool, 1–100; default 30 |
| `premise_early_stop` | Direct premise resolution; default false |
| `retrieval_mode` | expand_query transformations: baseline, hyde, query_expansion, hyde_query_expansion, full |
| `hyde` | Include hypothetical passage when the selected transformation mode supports it |
| `expansion_count` | Number of alternative queries, 1–10; default 3 |
| `parallel_transformations` | Run independent transformations concurrently |
| `name_completion` | Name normalization used by current tools |
| `scene_search_hits` | Candidate count for moment-scene selection |
| `scene_window`, `scene_stride` | Scene index window/stride |
| `scene_thinking` | Thinking for index-time summaries |
| `passage_chars`, `min_passage_chars`, `passage_overlap` | Passage indexing configuration |
| `generation` | Local transformation temperature, context_length, output_budgets |

A transformation mode is an option within v2.16, not a historical pipeline.
For example, `baseline` disables expand_query rewrites; it does not select the
removed fixed retrieval engine. Local-only settings are rejected for OpenAI.
OpenAI failures do not silently fall back to Ollama.

The old fixed-pipeline candidate counts, wide retrieval, RRF, low-confidence,
entity-matrix, graph, context-index, answer-thinking, and prompt-label settings
are removed. Unsupported settings and pipeline IDs fail explicitly.

## Corpus and indexing

Set `CORPUS_ID` to the corpus folder name. Its `corpus.yaml` selects books,
question sets, answer facts, language, behavior profile, and Langfuse project.
`CORPUS_ROOT` supports a separately mounted corpus. Generated data stays under
`data/<corpus-id>/`; collections are isolated by corpus and index identity.

Indexing builds passage vectors, overlapping scene-summary vectors, and entity
cards. BM25 uses an in-memory index of the same passages. Obsolete context and
event-graph index builders are removed; existing stored collections/files are
left untouched.

`POST /index` builds an index; `POST /ask` validates it without rebuilding.
Changing chunking or embedding identities requires a matching index. Incomplete
indexes require an explicit rebuild. Existing other collections are retained.

## Interactive API

Local default:

```bash
curl -sS http://127.0.0.1:8001/ask -H 'Content-Type: application/json' \
  -d '{"question":"Who tried to shoot Mikael?","pipeline":"v2.16","cache_mode":"bypass"}'
```

OpenAI:

```bash
curl -sS http://127.0.0.1:8001/ask -H 'Content-Type: application/json' \
  -d '{"question":"Who tried to shoot Mikael?","settings":{"agent_provider":"openai","agent_reasoning_effort":"high"},"cache_mode":"bypass"}'
```

`POST /ask/stream` provides the streaming form. Responses include citations,
pipeline identity, model/provider metadata, timings, and trace ID when tracing
is enabled. Cache modes are use, bypass, and refresh; cache layers are
request-scoped. Rate limiting and the shared interactive admission lock remain.

## Experiments and Langfuse

Use the durable `app.experiments` runner. The temporary
`run_agentic_experiment.py` bridge was removed.

From the repository root, use a one-off container with Git mounted and the
worktree marked safe:

```bash
docker compose run --no-deps --rm -T \
  -v "$PWD:/workspace" \
  -v "$(command -v git):/usr/local/bin/git:ro" \
  -w /workspace \
  -e GIT_CONFIG_COUNT=1 \
  -e GIT_CONFIG_KEY_0=safe.directory \
  -e GIT_CONFIG_VALUE_0=/workspace \
  app python -m app.experiments --dataset QA.csv --pipeline v2.16 \
  --item-id ITEM_ID --cache-mode bypass
```

Use `--settings /workspace/path/to/settings.json` for provider or other
overrides. Experiments refresh caches by default. CLI options also support
dataset version, repeated item IDs, variant label, cache layers, and correctness
evaluator selection. Reference answers go only to evaluators.

Remote Langfuse dataset experiments use `POST /experiments/run` and
`X-Experiment-Trigger-Token`. An empty custom payload selects v2.16 defaults.
Payloads support pipeline, settings (config alias), variant_label,
dataset_version, item_ids, correctness_evaluator, cache_mode, and cache_layers.
The handler accepts object or JSON-string payloads. Queueing, idempotency,
status inspection, retries, trace-upload verification, and failure categories
remain supported. Deployment-specific webhook routing should be checked against
the running deployment.

Interactive tracing is optional: `LANGFUSE_ENABLED=false` disables it.
Hosted experiments require the configured project and credentials.
`OPENAI_API_KEY` is required for OpenAI. Keep credentials in local environment
configuration; the frontend proxy keeps them out of browser code.

Generation instructions come from local templates and corpus profiles.
Historical Langfuse RAG prompt objects remain stored but are no longer loaded or
reconciled. Langfuse **Evaluators** remain the versioned source of judge rubrics.
Inspect them with `python -m app.prompt_assets`; explicit
`--create-missing` and `--create-new-versions` flags retain evaluator management.

Correctness evaluator versions are independent of pipeline versions and remain
supported. The default is `answer_correctness_v2`; citation support remains
`citation_support_v1`. See `app/evaluator_specs.py`,
`app/quality_evaluators/README.md`, and `app/quality_metrics.py` for current
contracts/executors. Do not duplicate scores with additional managed rules when
the experiment runner already executes the same judges.

Existing results, metrics, manifests, dataset history, and Langfuse trace links
are preserved. Rescoring utilities remain available without historical pipeline
execution. Historical setup and experiment evidence are retained in the
[archived technical guide](docs/handoff/2026-11-25-pre-cleanup-technical-guide.md).

## Identity and verification

`pipelines.sha256` protects the catalog definition. The instruction manifest
protects current system/synthesis prompts, tool schemas, transformation
templates, and named message builders. Conversation handoff has a separate
byte-level hash. Source fingerprints, Git revision, corpus/profile/prompt/model
identities, and derived settings remain recorded.

The maintenance keeps the name v2.16 while deliberately migrating fingerprints.
Historical manifests are not rewritten. Cache identities distinguish changed
definitions and supported settings.

Run Python tests using the one-off container command above, replacing the final
command with `python -m unittest discover -s tests -v`. Set
`EXPERIMENT_DATA_DIR=/tmp/cleanup-unit-tests` in that container to isolate test
locks/data from live requests. Frontend checks run from its directory:
`npm test` and `npm run build`.

The [cleanup plan](docs/plans/2026-11-25-v2.16-maintenance-cleanup.md) records
scope and the verification checklist.
