# Pipeline versions: naming, selecting and recording query flows

Status: proposed; not implemented. Prepared 2026-10-20; open questions resolved with the owner the
same day. This is the handoff spec: the sections "Decisions taken", "Payload contract", "Endpoints",
"Resolution, identity and traces" and "Implementation guide" are normative.

An owner review of this draft resolved two remaining points: pre-migration experiment payloads are
out of scope, and the agent's non-tool steps emit named spans so the flow test covers them.

## Context

Two pipelines exist today — the fixed RAG flow and the agentic flow — but neither can be
named, selected, or reproduced by identity:

- An experiment always runs the fixed flow; the agent is reachable only through the
  interactive endpoint.
- The `pipeline_id` shown on traces and manifests is a hash of code, settings, prompts and
  corpus. It proves what ran, but nothing accepts it as input, so it cannot re-run anything.
- The engine is not part of that hash, so agent and fixed runs can carry the same ID. The
  agent's model, tool set and loop limits are not in it at all: they come from code and an
  environment variable, so two different agent methods share one identity.
- Settings arrive as env-driven defaults plus ad-hoc overrides; a behavior change has no
  name, and going back to "how it worked before the agent" is a manual reconstruction.

The goal is a named **query flow** per version: a name that always means the same method,
selectable per question and per experiment, and recorded on every run so past runs stay
comparable. Freezing means only that: a name keeps its meaning, and a change gets a new name.
Answers, scores and experimentation are not frozen. One question may run `v1` while the web
UI keeps using the default `v2`.

## What a version pins

A version describes the pipeline's method: which steps run, in what order, under which
conditions, with which instruments.

Pinned:

- the engine (fixed RAG or agent),
- the ordered stages and how they feed each other,
- the branch conditions and thresholds that select optional paths,
- which optional paths exist and are enabled,
- the agent's tool set, loop limits and instructions, when the engine is the agent,
- model names (and revisions where available), prompt versions, index collection and corpus
  checksum.

**Not** pinned:

- answers, wording, token streams, or latency,
- model nondeterminism between two runs of the same flow,
- evaluator scores.

A version is about methodological behavior, not output equality.

## Decisions taken

Catalog and identity:

- The catalog is `pipelines.md` at the repository root; release fingerprints are
  `pipelines.sha256` beside it. Both are part of the source fingerprint.
- The catalog declares its own default — a `default` entry in its header block. The test
  rejects a default that is not a released version. The default is **v2**.
- A released version never changes. Retiring it is a status change, not an edit; `status` and
  `notes` are outside the fingerprint for that reason.
- A released version's `code` entry is a best-effort provenance bookmark, not a requirement:
  some recorded runs carry only `unknown`, so it may be absent.
- `flow` uses the instrumentation names emitted today, unchanged, except for the agent's
  non-tool steps, which gain spans so they can be named (see Version 2). A step that is not a span
  (the wider-pool admission, the low-confidence path) is recorded as a condition on the stage
  it affects, not invented as a stage name.
- v1 reproduces the recorded pre-agent run — its settings, its prompt versions, its index — not
  today's fixed flow. Where a recorded value no longer exists, the block says so instead of
  substituting today's value.
- v2 records its own `agent` section: model, tool set, loop limits, and a fingerprint of the
  in-code instructions. It records only the settings the agent reads; `notes` says which
  retrieval settings belong to the fixed flow.
- No environment variable supplies a setting inside a released version (endpoints and model
  keep-alive remain deployment configuration). v2's model and limits change only by publishing a new
  version, never by editing `.env`.

Payload and recording:

- Both `/ask` (and `/ask/stream`) and `/experiments/run` accept `pipeline` and `settings`.
- `settings` overrides are allowed; such a run is recorded as *derived*, its identity carries
  a `derived-` marker, and it is never presented as the released flow.
- The engine cannot be overridden by `settings`; a different engine is a different version.
- Legacy payload fields are accepted as aliases (see "Payload contract") for convenience, not for
  migration: pre-migration experiment payloads are not supported, and old executions are not
  retried across this change.
- `variant_label` stays on the experiment trigger: it labels the run, not the pipeline, and
  defaults to the version id.
- Draft versions are selectable for authoring and are recorded as `draft`. Retired versions
  still run when named explicitly; only the default must be released.
- Verification is by instrumentation — same steps and methods — not by comparing answers.

## Catalog format

`pipelines.md` is both the human-readable catalog and the machine-readable definition:

- the **first fenced block** is the catalog header: `{"default": "v2"}`;
- then one `## Version …` section per version, each with a short prose description of the flow
  followed by one fenced JSON block.

A parser reads the blocks at app startup; a malformed catalog fails startup and the test
suite. The image copies `pipelines.md` and `pipelines.sha256`, so the container parses the same
catalog and the source manifest can hash both. A separate command writes `pipelines.sha256`; the
test only compares, so editing a released version fails the tests. Editing a block and its line
together still passes: the file is a speed bump, not tamper evidence. A change to a released
version is published as a new version.

Each version block records:

| Field | Meaning |
|---|---|
| `id` | `v1`, `v2`, `v2.1`, … |
| `status` | `draft`, `released`, `retired` |
| `engine` | `fixed` or `agent` |
| `flow` | ordered stage names, with `when` for conditional stages |
| `agent` | tool set, loop limits, instruction fingerprint; present only when the engine is `agent` |
| `settings` | every setting the engine reads, with explicit values; no env defaults inside a released version |
| `prompts` | managed prompt name → exact version; empty when the engine is the agent (its instructions are code) |
| `index` | collection name and corpus checksum |
| `models` | generation/embedding/reranker/summary model, revision or digest |
| `code` | release git revision and source fingerprint, for provenance (best effort) |
| `notes` | known limitations, the reason the version exists, and what is not listed above |

`pipelines.sha256` format: one line per released version, `v1 4c1d9a…` (full hex). Test rules:

- every released version has a line, and it matches;
- every line names a version that exists;
- a draft needs no line; retiring keeps its line;
- a mismatch fails with the message "publish a new version; a released version is immutable".

Fingerprint payload: canonical JSON (sorted keys, no whitespace) of `id`, `engine`, `flow`,
`agent`, `settings`, `prompts`, `index`, `models` — everything except `status`, `notes` and
`code`.

The flow stage names are the instrumentation names already emitted today, so the catalog and the
traces speak the same language: "query translation", "HyDE transformation", "query expansion",
"grammar correction", "name completion", "candidate retrieval", "RRF candidate merge",
"cross encoder reranking", "keyword search", "scene context search", "entity names",
"entity matrix", "scene search", "moment scene search", "evidence formatting",
"answer generation", "citation extraction". A version's `flow` lists the ones it runs, in order,
with a `when` for each conditional one. Spans nested inside a stage (a query embedding per search,
a generation call inside each rewrite) are not separate entries; the order check compares first
occurrences, so a stage emitted several times still matches. Stages that run concurrently —
v1.1's parallel transformations — are listed as one parallel group, so the order check does not
depend on scheduling. Admission rules that are not spans
(the wider pool, the low-confidence path) belong in the condition that admits them, not in the
stage list.

## What a version does not pin

Some behavior lives in code and is not a setting. The blocks do not list it; `notes` names it, and
the flow test plus code review are the guard. Reading the code, this is the full list:

- v1: the name-completion thresholds (20 mentions, 0.5 share, 3.0 ratio), BM25 `k1=1.2`/`b=0.75`,
  the stop-word/title/scope/anchor word lists, the "English share" definition (only its threshold
  is a setting), the rule that query expansion raises unless it returns exactly `expansion_count`
  alternatives, the previous-passage join, the evidence text format, and the citation regex.
- v2: the name-normalization cutoffs, the trigger regexes behind the pre-checks, and the tool
  snippet sizes. The prompts and messages themselves are fingerprinted (see Version 2); the code
  that applies them is not.

A version therefore pins the *method as configured*, not every line of code that implements it.
This is deliberate: the alternative is freezing source hashes and never being able to fix a bug.

## Version numbering

- **Major** (`v1` → `v2`): an engine or structural change. The fixed flow is v1; the agent
  is v2.
- **Minor** (`v1` → `v1.1`): a stage or setting change within the same family. Example:
  `v1.1` is v1 with `parallel_transformations` enabled.
- A released version never changes. Retiring it is a status change, not an edit.
- The default may point only at a released version.

## Version 1 — fixed RAG (pre-agent)

The flow as it ran in the last pre-switch experiment with default settings — the recorded run, not
today's code:

1. query translation (conditional: when the English word share is below the threshold)
2. HyDE transformation
3. query expansion ×3
4. grammar correction
5. name completion (conditional: a bare name that matches the corpus)
6. candidate retrieval: dense search per query, then RRF candidate merge, plus a wider candidate pool
7. cross encoder reranking; wider-pool admission by score margin
8. keyword search, BM25 (conditional)
9. scene context search (conditional)
10. entity names, then entity matrix (conditional)
11. scene search, then moment scene search (conditional)
12. evidence formatting
13. answer generation
14. citation extraction

Each line names the stage as the block records it; the block adds the trigger for every
conditional one.

Settings: the exact resolved defaults of that run (full retrieval mode, 30 candidates,
top 10, 1200-character passages, minimum 400, HyDE on, three expansions, translation on,
name completion on, RRF constant 60, wide pool 100/3, keyword 30 hits with margin 4.0,
scene context and scene search on, entity names and entity matrix on, entity graph off,
low-confidence threshold 2.0 with top 15, parallel transformations off, `qwen3:8b` at
temperature 0 with 8k context and 4096/8192 output budgets).

Prompts: the seven `rag-*` versions recorded by that run, pinned by version — answer, hyde,
query-expansion, query-translation, grammar-correction, scene-moment, scene-select.

Index and corpus: the collection and checksum recorded by that run. The block records the
pipeline-style checksum (the list-of-files value the reference run's manifest carries); the
indexer's own checksum is recomputed from disk for the collection name and is not stored twice.
The recorded embedding and reranker revisions are pinned literally, and a released version never
re-resolves them from the Hub. The reference run's recorded revision (`35b543a`) is stale — it
predates the settings that run used — so `code` is omitted for v1.

`v1.1` is the same flow with parallel transformations enabled; it is the minor-version
example and is not required for the first release.

## Version 2 — agentic (current Millennium UI)

Engine: agent. The flow is a loop rather than a sequence: the model chooses tools until it
submits an answer. Each tool reuses retrieval code, some of which also runs in v1; the agent also
has instruments v1 lacks (reading passages and chapters, entity cards and connections, the
true-account search), and v1 has paths with no tool here (the scene context path, the entity
names and matrix admission).

Tools: `semantic_search`, `keyword_search`, `expand_query`, `search_scenes`, `read_scene`,
`scene_moment`, `true_account`, `entity_card`, `find_connections`, `find_names`,
`read_passage`, `read_chapter`, then `submit_answer`.

Loop and model: model `qwen3.6:35b`, at most 10 turns and 16 tool calls, at least 4 tool
calls before an answer is accepted, 900-second timeout, 16384-token context, 1600-token
answer budget, 300-character tool snippets. The block records all of this in its `agent`
section, because none of it is a setting and none of it is recorded anywhere today (the
interactive model comes from an environment variable that never touches the pipeline identity).

The agent reads only part of the settings, through the helpers it borrows from v1: the model
identities, the generation settings, `retrieval_mode`, `hyde`, `expansion_count`,
`name_completion`, `scene_search_hits`, and `scene_window`, `scene_stride` and
`scene_summary_model` (those three through the scene index name). The other retrieval knobs
belong to the fixed flow; the block records only what the agent reads and `notes` names the
rest as unused here.

The flow also declares what the loop does outside the model's choice, because it changes
behavior and must be frozen with the version:

- the four pre-checks before the first turn (connection, true account, sequence, moment);
- the minimum-tool-call and no-tool nudges, and the coverage check;
- submission verification (at most 2 retries) and the name-check message after `find_names`;
- the forced answer at the turn budget, tool budget or timeout (recorded as `stopped: budget`),
  and the abstention synthesis and coverage rewrite in the final pass;
- the recorded stop reason (`submit`, `content`, `budget`, plus any synthesis or speech
  fallback).

Each of these steps emits a span of its own; the block lists those names in `flow`, so the flow
test asserts them the same way it asserts v1's stages. The tools stay in `agent.tools`: the model
chooses the order, so a replay compares the declared tool set, not the sequence of calls.

The agent's instructions live in code and the `rag-*` prompts are not used by this engine;
the version records a fingerprint of every prompt and message template in `agent.py`: the system
prompt, the forced-answer prompt, the synthesis prompt, the pre-check, nudge, verification and
coverage messages, and the templates the tools compile, so nobody assumes the managed prompts
still shape v2 and an instruction edit cannot pass as the same version.

## Payload contract

Common shape, on both endpoints:

```json
{"pipeline": "v2", "settings": {"expansion_count": 2}}
```

- `pipeline` omitted → the default (`v2`).
- `settings` is merged over the version's settings. The run is recorded as *derived*, its
  identity carries a `derived-` prefix, and the requested version is still recorded.
- `settings` keys are the `ResolvedPipelineConfig` field names. `corpus_checksum` and
  `prompt_hashes` are identity, not settings, and are rejected.
- The engine cannot be overridden by `settings`; a different engine is a different version.
- The `agent` section is not overridable either: a changed tool set, limit or model is a new
  version, which is what keeps two v2 runs comparable.

### `POST /ask` and `POST /ask/stream`

Add `pipeline` and `settings`. Existing fields keep working:

| Field | Rule |
|---|---|
| `engine` | Legacy alias when `pipeline` is absent: `fixed` → `v1`, `agent` → `v2`. If both are present and disagree, 400. |
| `mode`, `candidate_count`, `top_k`, `passage_chars` | Become `settings` overrides when present and therefore mark the run derived. Their defaults are now `None`, so a request that sends none of them is exactly the version. `mode` maps to `retrieval_mode`. |
| `collection` | Must equal the collection the version's settings resolve to, otherwise 400. The version pins the index. |
| `prompt_label` | 400 for a released version (prompts are pinned). A draft may use it while being authored. |
| everything else | Unchanged (`question`, `session_id`, `user_id`, `source`, `client_ip`, `production`). |

Unknown top-level body fields stay ignored (today's behavior); only `settings` keys are strictly
validated. The result gains `pipeline_version` and `pipeline_derived` next to `pipeline_id`.

### `POST /experiments/run`

The Langfuse trigger payload (`customPayload`/`payload`, sent as an object or a JSON string)
accepts `pipeline` and `settings`. Migration:

| Field | Rule |
|---|---|
| `config` | Accepted as an alias for `settings`; if both are present, 400. |
| `variant_label` | Kept. Defaults to the version id; used in the run name and manifest only, never in the identity. |
| `prompt_label` | 400 for a released version; drafts may use it. |
| `dataset_version`, `item_ids`, `correctness_evaluator` | Unchanged. |

The CLI (`python app/experiments.py`) gains `--pipeline` (default v2) and `--settings`, with
`--config` kept as an alias; `--prompt-label` is rejected for released versions.

### Choosing a version from the Langfuse UI

The version is a field in the payload the UI sends; there is no separate picker:

1. Dataset → **Run experiment** → **Run remote dataset run**.
2. In the editable **Config** JSON box (pre-filled from the dataset's saved remote-experiment
   payload), set `"pipeline": "v1"` and, if needed, `"settings"` — for example
   `{"pipeline": "v1", "variant_label": "passages-600", "settings": {"passage_chars": 600}}`.
3. **Run**. Omitting `pipeline` selects the default.

Saving the payload in the dataset's remote-experiment settings keeps a per-dataset default.

### Validation

A 400 is returned before anything is queued or executed for: an unknown `pipeline`; an unknown
`settings` key; a setting of the wrong type or outside its allowed range; an identity key in
`settings`; `engine`/`pipeline` disagreement; `config` and `settings` both present;
`prompt_label` on a released version; a `collection` that does not match the version's index.

### Derived, draft, retired

- A derived run records the requested version, `derived: true`, and an identity under the
  `derived-` prefix. It is never described as the released flow.
- A draft run is recorded with `status: draft` and never as released.
- A retired version runs when named explicitly and is recorded as retired.

## Endpoints after this change

No endpoint is added; eight exist before and after.

| Endpoint | Change |
|---|---|
| `POST /ask`, `POST /ask/stream` | `pipeline` + `settings`; legacy fields mapped as above; result gains version fields |
| `POST /index` | Optional `pipeline` + `settings` (resolved the same way) so the index a version needs can be built; result gains `pipeline_version` |
| `POST /experiments/run` | `pipeline` + `settings`; `config` alias; `variant_label` kept |
| `GET /experiments/{execution_id}` | Response adds `pipeline_version` and `pipeline_derived` |
| `POST /experiments/{execution_id}/retry` | Unchanged for executions created after this change; the copied payload keeps the version and its derived state. Pre-migration executions are not retried |
| `GET /health`, `POST/GET /langfuse-ollama/v1/{path}` | Unchanged |

## Resolution, identity and traces

- One resolver turns a version plus overrides into a runnable configuration (resolved settings,
  prompt pins or instruction fingerprint, engine, agent settings). One runner executes it and
  returns the same result shape for both engines.
- Both endpoints call the resolver and the runner; the endpoint becomes transport. A dataset
  experiment routes through the runner exactly like `/ask`, so v2 is reachable from
  `/experiments/run` too.
- Identity is readable: `pipeline-v1-<8 hex>` for a released version,
  `derived-v1-<8 hex>` with overrides, `draft-v3-<8 hex>` for a draft. The hash is
  `sha256(canonical_json({id, fingerprint, overrides}))` where `fingerprint` is the version's
  entry in `pipelines.sha256` (for a draft, the fingerprint of its current block).
- Traces carry `pipeline_id`, `pipeline_version` and `pipeline_derived` in metadata, next to
  `collection` and `source`; the `pipeline:<pipeline_id>` tag stays.
- Experiment manifests carry the same three under `pipeline`, next to the dataset version and
  evaluator versions, and the Langfuse experiment metadata repeats them.
- A released version's settings are literal values. Environment variables are not read inside a
  version, so a changed env cannot silently alter it, and `AGENT_MODEL` stops affecting v2.
- The source manifest (`app/identity.py`) includes `pipelines.md` and `pipelines.sha256`, so
  provenance covers the catalog that described the run.

## Verification: instrumentation, not output

Primary — static flow test:

- For every released version, run the pipeline on a fixture with stubbed models and assert
  that the emitted instrumentation names occur in the version's declared order (first
  occurrence, because one stage can be emitted several times).
- Conditional stages are listed with their condition; the fixture forces each trigger so the
  branch must appear.
- For the agent, assert the tool catalog, the loop limits, and that each declared non-tool step
  emits its span (pre-checks, nudges, verification, forced answer, synthesis).

Secondary — replay:

- Replay a small question set and compare the ordered stage names with the reference trace. For
  the agent, compare the declared tool catalog and the stages, not the model's tool-call sequence:
  the model chooses the calls, so their order is not stable.
- Branches that depend on retrieval or model scores may differ between runs; those are not
  failures. The check is that the stages and methods are the same, not that the same branch
  fires.

No answer diffing is part of acceptance.

## Implementation guide

### New modules

- `app/pipeline_catalog.py` — parse `pipelines.md` (header + version blocks), validate the schema,
  expose `default`, `get(id)`, `fingerprint(block)`, and `check_fingerprints()` against
  `pipelines.sha256`. Raises on a malformed catalog.
- `app/pipeline_resolver.py` — `resolve(pipeline: str | None, overrides: Mapping) -> ResolvedRun`
  returning the engine, `ResolvedPipelineConfig`, `AgentSettings` (or `None`), prompt pins or
  instruction fingerprint, the resolved identity and the derived/draft flags. All 400-worthy
  validation lives here as `ValueError`, so both endpoints map one exception to one status.
- `app/pipeline_runner.py` — `run(question, resolved, collection, prompt_bundle, on_token,
  on_status) -> dict`: dispatches to `run_pipeline` or `run_agent` and returns the fixed shape
  (the adapter currently in `main._run_agent_ask`, moved here), plus the version fields.

### Changes to existing modules

- `resolved_config.py`: split `from_mapping` so the version path reads no environment variables
  (keep the env-default variant for `/index` when no pipeline is given). A released version's
  model identities are literal, so the version path never calls `resolve_pipeline_model_identities`.
- `main.py`: `AskRequest` gains `pipeline`/`settings` and `None` defaults for the legacy
  retrieval fields; `_prepare_ask` uses the resolver; `_run_ask` uses the runner; traces and the
  result gain the version fields; `/index` accepts the optional pipeline.
- `experiments.py`: resolve once per execution, run through `pipeline_runner`, put the version
  fields in the manifest and the experiment metadata, accept `config` as a `settings` alias,
  add `--pipeline`/`--settings` to the CLI, and default `--prompt-label` to `None` so the CLI does
  not reject a released version by its own default.
- `prompt_assets.py`: `load_prompt_bundle(client, versions=None, label=None)` — fetch each prompt
  by its pinned version when `versions` is given, by label only for drafts; a missing version
  fails preflight with the prompt name and version.
- `agent.py`: answers unchanged. Expose the tool names and `AgentSettings` defaults as data so
  the catalog test can compare them; take the model from the resolver, never from the environment;
  emit a span for each declared non-tool step (pre-checks, nudges, verification, forced answer,
  synthesis).
- `identity.py`: add `pipelines.md`, `pipelines.sha256` to `PIPELINE_SOURCE_FILES`.

### Tests to add (`tests/test_pipelines.py`, plus cases in `tests/test_api.py`)

1. Every block parses; ids unique; `default` names a released version; no unknown fields; every
   setting the engine reads is present, so a missing field cannot fall back to a code default.
2. Every released version matches `pipelines.sha256`; an edited released block fails; a line
   without a block fails; a draft without a line passes.
3. `v1` resolution reproduces the recorded run's settings and prompt pins.
4. `v2` resolution produces the declared `AgentSettings` and tool list; the fingerprint matches
   the block.
5. Unknown pipeline, unknown setting, wrong type, identity key, `engine` conflict,
   `config`+`settings`, `prompt_label` on a released version, mismatched `collection` → 400.
6. Derived run: identity has the `derived-` prefix; the requested version stays in the record.
7. Legacy `engine: fixed` resolves to v1 with no overrides; the UI payload with no pipeline
   resolves to v2.
8. Static flow order for v1 with stubbed models; forced branch fixture.
9. Agent catalog, limits and non-tool step spans match the block; the replay check ignores the
   model's tool-call order.
10. Prompt loading by version; missing version fails before the run.
11. Experiment path: `/experiments/run` with `pipeline: v2` reaches the agent runner and the
    manifest records the version and `derived: false`.
12. Index mismatch: a version whose corpus checksum differs from disk refuses with a clear
    message and does not substitute today's collection.

### Definition of done

- `pipelines.md` and `pipelines.sha256` exist, with `v1` and `v2` released and the default set.
- Both endpoints accept `pipeline`/`settings`; the legacy aliases behave as tabled above.
- `/ask` with no fields still answers with v2, and its trace metadata shows `pipeline_version`.
- A Langfuse UI remote run with `{"pipeline": "v1"}` scores v1; with `{"pipeline": "v2"}` scores
  the agent.
- `pipelines.sha256` is enforced by the tests, and `pipelines.md` is named in the docs.
- `python -m unittest discover -s tests` passes (the repo has no CI; this suite is the guard).

## Implementation phases

| Phase | Work | Estimate |
|---|---|---|
| 1 | `pipelines.md` schema, parser, validation and immutability test | 0.5–1 day |
| 2 | Write `v1` from the recorded run, `v2` from the agent code and its traces | 0.5 day |
| 3 | Resolver, `pipeline` + `settings` in both payloads, legacy aliases, derived marking | 1–1.5 days |
| 4 | One runner for both engines with a shared result shape, agent reachable from experiments | 1–1.5 days |
| 5 | Load prompts by pinned version; fail preflight when a version is missing | 0.5 day |
| 6 | Static flow test and replay check | 0.5–1 day |
| 7 | Tests and documentation | 0.5 day |
|  | **Total** | **~4.5–6.5 days** |

Phase 3 can ship before phase 4, with `v1` working end to end while `v2` still runs only
through the interactive endpoint; that is the smallest useful slice. Phase 4 puts the agent
behind the experiment trigger too, so `v2` is scored on datasets through the same runner,
evaluators and manifests as `v1`.

## Risks and mitigations

- **Markdown as the source of truth.** Fenced JSON per version plus a parser test; a released
  block is fingerprinted in `pipelines.sha256` so an edit fails the test suite.
- **v2 has no reference experiment.** The agent is not reachable from the experiment trigger
  today, so `v2` is written from the code and its interactive traces; phase 4 makes it
  measurable, and the flow test — not a past run — is what holds it.
- **The catalog and the code can disagree.** A version pins the method as configured, not every
  line of code (see "What a version does not pin"); the flow test and review are the guard, and
  `notes` must name the code-only parts.
- **Prompt versions are not currently selectable** — prompts are loaded by label. Version-
  aware loading is a small, explicit change, and a missing version fails before the run.
- **Conditional stages make static verification subtle.** Encode each condition in the
  catalog and force it in the fixture.
- **Overrides weaken the guarantee.** They are allowed, but always marked derived and never
  described as the released flow.
- **Pre-migration payloads are not expected.** The saved Langfuse dataset payload is updated once
  during rollout, and old executions are not retried; the alias rules remain for convenience, not
  compatibility.
- **Code can drift from the recorded revision.** The released flow test, not the revision
  hash, is the guard; a revision, where known, stays for provenance.
- **Existing runs cannot be renamed.** They keep their hashed IDs; the catalog takes effect
  for new runs.
- **A pinned corpus or index no longer exists.** The run stops with a message naming the version
  and what is missing; it never substitutes today's corpus, collection or prompt version.

## Out of scope

- output determinism, answer equality, or model tag pinning beyond recording revisions,
- evaluator changes (already pinned per run),
- re-running an old run by its historical hashed ID, as opposed to by a version,
- a version picker in the web UI; the UI keeps sending no pipeline, so it stays on the default,
- per-user or per-session version pinning.
