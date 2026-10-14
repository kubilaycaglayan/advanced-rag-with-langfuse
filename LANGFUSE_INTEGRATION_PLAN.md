# Millennium RAG: Langfuse integration and experiment runner

Status: implementation handoff plan; no integration changes have been implemented by writing this document.
Prepared: 2026-10-14.

## 1. Objective and confirmed decisions

Build an experiment workflow around the existing retrieval and answer pipeline. A user must be able to start an experiment from Langfuse, run a versioned QA dataset through a particular pipeline configuration, inspect its complete trace trees, and compare both aggregate scores and one question's scores across experiments.

The work has three stages: (1) Langfuse integration preparation, (2) building the experiment runner with integration, and (3) completing any integration left unfinished in stage 2. Stage 3 is a completion gate; required capabilities must not be dropped merely because they did not fit stage 2.

Confirmed user decisions:

- Use the existing local Langfuse instance and a project named exactly `millenium`.
- Import `QA.csv` once, then make Langfuse the dataset source of truth. Grow and edit the dataset in Langfuse thereafter.
- Step 2 means an experiment runner around the existing RAG implementation.
- Use a local Ollama LLM to judge answer correctness and citation support separately, with numeric scores from 0 to 1 and explanations.
- Use one stable session per dataset question across experiments.
- Identify pipeline versions automatically using Git revision and effective configuration fingerprints. Every execution also needs its own experiment/run identifier.
- Support controlled component changes, including indexed passage size, with separately recorded results and scores.
- Store this handoff at the root of the implementation target: `<repository root>/LANGFUSE_INTEGRATION_PLAN.md`.

## 2. Repository and environment orientation

The implementation target is **`<repository root>`**. Build the RAG experiment directly at this repository root. `<legacy checkout>` is a read-only reference checkout for existing pipeline behavior; do not make migration or implementation changes there. The root `QA.csv` is the seed input. `machine profile guidance` contains the machine profile; use current machine facts rather than older hardware claims in the reference README.

Use the legacy checkout selectively as behavioral reference. Do not copy notebooks, notebook-only grammar/Jina variants, saved results, generated HTML, local indexes, model caches, virtual environments, logs, secrets, or unrelated files into this target. Create only runtime code, required configuration, the three EPUB corpus inputs, and concise operator documentation. Keep dependencies limited to imported packages and preserve retrieval behavior unless a planned change explicitly specifies otherwise. `.env` and credentials must remain untracked and excluded from manifests.

The intended root layout is:

| Path | Purpose |
| --- | --- |
| `RETRIEVAL_PIPELINE.md` | Root documentation to create only as needed to explain implemented retrieval behavior. |
| `app/` | FastAPI service, shared pipeline, experiment runner, evaluation, identity/configuration, and storage modules. |
| `compose.yaml` | Qdrant and RAG API services; Langfuse is hosted separately. |
| `app/Dockerfile` | Build recipe for the actual target modules. |
| `app/requirements.txt` | Runtime dependencies actually imported by the target application, including the pinned compatible Langfuse SDK. |
| `.env.example` | Secret-free template for the target configuration surface. Actual credentials belong in ignored root `.env`. |
| `README.md` | Concise setup, seed, run, and experiment operations documentation. |
| Legacy notebooks and generated results | Reference only; do not add unless a confirmed requirement depends on them. |
| `QA.csv` | Target-root seed input: 35 rows, columns `Question` and `Answer`, no blank questions or answers at inspection. |
| `books/` | The three EPUB source books used by the indexer. |

Use `<repository root>/QA.csv` as the one explicit seed input; do not switch to the legacy repository's copy implicitly. At plan preparation time, both copies had identical SHA-256 hashes: `af25aeb4b0411822decab5362dced6b147379d5427e07c67143ef678f26e8844`. Recheck the target copy before import and record its checksum. If the two copies later differ, the target copy remains authoritative unless the user explicitly changes this decision.

Known service addresses:

- Langfuse: `http://127.0.0.1:28420`. A read-only call to `/api/public/health` returned `{"status":"OK","version":"4.59.0"}` during planning. Recheck before implementation; project access and credentials have not been verified.
- RAG API: `http://127.0.0.1:8000` according to the repository configuration.
- Qdrant: `http://127.0.0.1:6333`.
- Ollama: `http://127.0.0.1:11434`.

## 3. Current pipeline and integration gaps

`POST /index` extracts paragraph text from exactly three EPUBs, splits long paragraphs near sentence/word boundaries, embeds the passages, and stores their vectors and source metadata in Qdrant. `PASSAGE_CHARS` defaults to 1200. Vectors use cosine distance and normalized embeddings. Source metadata includes book, section, paragraph, part, chapter, and page where available. Index point IDs are currently random UUIDs. The current collection defaults to `millennium_books_rag_v1`; a rebuild deletes that collection before recreating it.

`POST /ask` accepts `question`, `mode`, `candidate_count`, and `top_k`. Default values are `baseline`, 30 candidates, and 10 evidence passages. Modes are `baseline`, `hyde`, `query_expansion`, and `hyde_query_expansion`.

The question and enabled generated texts are embedded and searched. HyDE creates a hypothetical answer; query expansion asks for three alternatives. Combined transformation calls are sequential and each sees the original question. Non-baseline results merge by passage ID using RRF with `1 / (60 + rank)` and retain at most 30 candidates. Baseline can retain up to the requested candidate count, whose API maximum is 100. A cross-encoder scores question/passage pairs, and the top passages are labeled `[E1]`, `[E2]`, etc. Ollama receives an evidence-only answer prompt. Citation extraction currently uses a regex; it does not validate that labels exist or that evidence supports each claim.

Default models are `sentence-transformers/multi-qa-MiniLM-L6-cos-v1`, `cross-encoder/ms-marco-MiniLM-L-6-v2`, and `qwen3:8b`. Generation settings include temperature 0, context length 8192, and progressively larger output budgets for empty responses. Record the resolved settings, not merely model names.

Grammar correction and Jina reranking are reference-checkout notebook additions and are outside the first runner target. Implement the shared API pipeline with its four existing retrieval modes. Do not silently substitute notebook behavior. Future variants must enter through an explicit configuration and receive a different pipeline fingerprint.

Existing tracing is optional and usually fails open. It includes a root API observation and some child observations, but does not instrument every stage. Notebook child stages can be reconstructed after execution rather than timed around the actual work. Current sessions hash question plus pipeline/configuration, so changing configuration changes the session; replace this behavior for dataset experiments. The current trace metadata is not a Langfuse dataset or experiment linkage. No dataset import, experiment runner, or judge scoring exists. The container also does not mount `QA.csv`; the experiment path must fetch expected answers from Langfuse rather than rely on the helper's local CSV lookup.

## 4. Identity and reproducibility contract

Keep these identities separate and attach them to the appropriate experiment and observations:

| Identity | Required behavior |
| --- | --- |
| Dataset item ID | Langfuse's durable item identity. Preserve it when editing an existing question or reference answer. |
| Dataset version | Resolve and pin one dataset version at run start. Store the version timestamp and a checksum of the selected item snapshot. |
| Question session | `qa-<dataset-id>-<dataset-item-id>`, subject to Langfuse's session length limit. It must be independent of pipeline configuration and run ID. |
| Execution ID | New UUID for every explicitly requested execution, including reruns of an identical configuration. |
| Experiment | A Langfuse dataset experiment created through the SDK, with a unique run name containing a readable variant label and execution ID. Record its returned identifier/URL. |
| Pipeline ID | Hash of the Git revision, resolved pipeline settings, prompt hashes, dependency/model identities, and corpus/index manifest. Store the full manifest and a readable short hash. |
| Evaluator ID | Separate fingerprint of judge model identity, settings, rubric, prompt, and evaluator code version. |

Record the Git commit and dirty state. For a dirty worktree also record a content fingerprint of the pipeline source and dependency files so two different uncommitted implementations cannot share the same identity. Make the result explicitly identifiable as dirty. Capture Ollama model digests and resolved embedding/reranker revisions where available; an unpinned model name is insufficient to claim exact reproducibility.

Editing a Langfuse item preserves the question session but creates a new dataset version. Comparisons must show dataset and evaluator versions so changed reference answers or judges are not mistaken for pipeline improvements. Default comparisons use the same dataset snapshot and evaluator version. For datasets of different sizes, compare common item IDs separately from newly added items.

## 5. Stage 1 — Langfuse integration preparation

1. Verify Langfuse health, installed SDK compatibility, Ollama availability, and project-scoped credentials. Create or reuse project `millenium`; do not assume the older README's `millennium notebook` project is correct. Never put credentials into tracked files, manifests, or trace metadata. Pin the working SDK release after confirming its experiment API.
2. Add an explicit seed command for dataset `QA.csv`. Map `Question` to `input.question` and `Answer` to `expected_output.answer`; keep source checksum and seed row provenance in metadata. Reject blank fields and duplicate normalized questions before import. Make re-running the seed idempotent using stable initial item IDs or a stored import mapping. Do not overwrite subsequent Langfuse edits or recreate deleted items on routine startup. Subsequent maintenance occurs in Langfuse.
3. Define numeric score configurations `answer_correctness_v1` and `citation_support_v1`, both in `[0,1]`. Store evaluator prompt/rubric versions in code and manifests.
4. Establish a resolved configuration object, identity helpers, and dataset snapshot manifest before adding the runner. Include retrieval mode, candidate count, top_k, chunk size, model identities, prompt hashes, RRF constant, corpus checksum, and generation settings.
5. Verify network routing for Langfuse's remote experiment callback. `127.0.0.1` inside a Langfuse container may not reach the host's runner; configure a reachable host address without assuming identical network namespaces.

Stage 1 deliverables: configured project access, seeded dataset, identity/configuration contract, versioned evaluator specification, and a documented callback URL/configuration. Record real project/dataset IDs and operational commands in the implementation README after setup.

### Decisions that remove implementation ambiguity

These mechanisms are part of the plan, not open product questions:

1. **Pinning a hosted dataset version:** Resolve the dataset once at execution creation and pass its version timestamp to the SDK's historical-version dataset fetch. The current Langfuse experiment documentation states that fetching a dataset accepts a version timestamp and includes items later updated or deleted. Capture the returned items and references into an immutable local snapshot before scheduling item work; compute the snapshot checksum from canonical JSON containing item IDs, inputs, expected outputs, and metadata, sorted by item ID. For item-targeted runs, filter this pinned snapshot by item ID after fetching, never fetch a fresh/latest dataset per item. If the installed pinned SDK cannot fetch a historical version, implement the documented dataset API request for the versioned snapshot behind one adapter and feed that immutable item list to the SDK experiment runner; do not silently fall back to latest. Verify this behavior against the installed SDK in stage 1. ([Langfuse experiment SDK documentation](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk))
2. **Index manifest persistence and validation:** Store index manifests in the experiment SQLite database, in an `index_manifests` table keyed by collection name and manifest fingerprint. A manifest row includes canonical config JSON, corpus/source hashes, splitter code fingerprint, embedding identity, vector settings, expected point count, actual point count, creation state (`building`/`ready`/`failed`), and timestamps. Build into a fingerprint-named collection; mark it `ready` only after writes complete and Qdrant reports the expected count. On every retrieval, require a matching `ready` row and verify the live collection exists and its point count equals the recorded count. A missing DB row, mismatched fingerprint, unavailable collection, or count mismatch is a hard error for experiment runs. Never auto-rebuild or fall back to the default collection. An interrupted `building` manifest remains failed/incomplete until an explicit rebuild action creates and verifies it.
3. **Stable IDs for the one-time seed:** Assign each source row a stable `seed_row_key` from the normalized question plus its occurrence number among identical normalized questions (duplicates are rejected, so occurrence is normally 1). On first import, assign the Langfuse dataset item ID as UUIDv5 in a fixed application namespace over `dataset-slug + source-checksum + seed-row-key`; write `seed_row_key`, original source checksum, and source row number into item metadata, and save the resulting mapping in the experiment volume. Before initial import, reject a dataset that already has items unless an operator explicitly selects a reconciliation mode; never blindly recreate missing seeded rows. On subsequent seed-command runs, treat the command as verification only: match by metadata/mapping, report absent or changed source rows, and never update/delete Langfuse items. If the original CSV's question changes, it is a new source row for reconciliation purposes; edits to a live QA case happen in Langfuse and preserve that Langfuse item ID.
4. **Dirty-source fingerprint scope:** Build the pipeline source fingerprint from a sorted manifest of every source file that can affect pipeline or evaluator behavior: all Python modules imported by the API/runner, prompt/template files, requirements/lock files, Docker packaging, and index extraction/splitting code. Include tracked changes, staged changes, and untracked files under those relevant directories; exclude caches, runtime databases, generated indexes/artifacts, `.env`, and secrets. Hash each path and byte content, then hash the canonical manifest. Record the Git revision, dirty boolean, and this fingerprint. A clean tree records the revision and the same file manifest; a dirty tree must have a distinct source fingerprint when any included file changes. Keep the include/exclude list explicit in code and expose it in the saved pipeline manifest.
5. **Acceptance test classification:** Label checks as (a) mocked automated checks, (b) live-service integration checks, or (c) manual UI acceptance. Mocked checks must run without Langfuse, Qdrant, Ollama, or network access. Live checks require the corresponding services and valid credentials and must report prerequisites separately from implementation assertions. UI acceptance requires a reachable Langfuse UI, project permissions, a configured callback URL, and the callback signing/token configuration. A missing prerequisite is reported as `not run: prerequisite unavailable`, never as a passing check or an implementation defect. Each acceptance result records category, prerequisite status, command/procedure, outcome, and artifact/log location.

The currently published Langfuse documentation supports historical dataset versions, hosted-dataset SDK experiments, evaluators, and asynchronous remote triggers. Stage 1 must still verify the exact Python SDK method signatures and behavior against the version pinned for this repository; the adapter above is the required compatibility boundary, not permission to weaken version pinning. ([SDK experiments](https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk), [datasets](https://langfuse.com/docs/evaluation/experiments/datasets))

## 6. Stage 2 — Shared pipeline and experiment runner

### Shared execution and configuration

Implement the answer workflow as `run_pipeline(question, config)` in a reusable module under `app/`. Keep `/ask` as a thin adapter with the reference pipeline's current request defaults and response fields. The experiment task calls the shared function in-process under the SDK's active observation context. This avoids creating disconnected HTTP traces and ensures both paths use the same pipeline implementation.

Preserve the answer, citations, candidates, reranked evidence, generated queries, model details, and timings in a structured result. Keep reference answers out of pipeline inputs and generation prompts; only the evaluator receives them. Add actual stage observations around transformation calls, query embedding, individual vector searches, RRF merge, reranking, evidence formatting, answer generation, and citation extraction. Record inputs, outputs, errors, model identity, and provider-reported token usage where available. Do not fabricate costs or token counts.

Use explicit configuration instances rather than mutating process-global environment settings between experiments. Models may be cached by model identity. Default to one experiment worker and one item at a time to avoid shared-state collisions and Ollama contention.

### Index variants

Treat `passage_chars` as an indexing setting. Build/reuse a collection named from an index manifest fingerprint containing corpus content hashes, extraction/splitting code version, passage size, embedding identity, and vector settings. Never rebuild the default collection to execute an experiment variant. Mark a new index ready only after all points are written and its manifest/count is recorded. Retrieval must reject a collection whose manifest does not match the requested configuration.

Preserve source-location provenance across chunk sizes. Qdrant point IDs may differ across indexes; they must not be used as the sole basis for cross-index relevance comparisons. Retain existing experiment collections until an explicit cleanup action is requested.

### Runner interfaces

Provide a CLI entry point and an HTTP trigger backed by the same runner implementation. Suggested modules are `pipeline.py`, `experiments.py`, `evaluation.py`, and `experiment_store.py`; update Docker packaging to include them.

- CLI: start a run with a dataset name/version, readable variant label, and configuration file. Optional item IDs support a smoke run or targeted question rerun; default to all active items in the pinned dataset version.
- `POST /experiments/run`: accept the Langfuse callback's dataset identity and custom payload containing `variant_label`, `config`, optional `dataset_version`, optional `item_ids`, and a shared trigger token. Validate dataset/project membership, allowed configuration fields, and the token. Configure the payload using the exact callback contract supported by the deployed Langfuse version.
- Return HTTP 202 with `execution_id` and `status_url` promptly, within Langfuse's documented 10-second trigger timeout. Do not run the dataset inside the request handler.
- `GET /experiments/{execution_id}`: report queued/running/completed/partial/failed status, item and scoring counts, manifest identifiers, and the Langfuse experiment URL once available.

Persist queued jobs and manifests in SQLite on a mounted experiment volume; a single worker executes them. Support an optional idempotency key for transport retries. Reusing the same key returns the existing execution; an intentional rerun uses a new key or none. A worker restart marks interrupted work clearly rather than silently claiming success or rerunning it under an indistinguishable identity. A user-requested retry creates a linked new execution.

Use the Langfuse SDK's hosted dataset experiment runner. Fetch the pinned dataset version once and use its item IDs to preserve comparison links. Attach the stable question session to each item's enclosing trace and propagate experiment/pipeline metadata to child observations. Avoid the existing API decorator opening a disconnected trace or overriding the experiment session.

### Local Ollama evaluators

Use a dedicated `EVALUATOR_MODEL` setting. Initial default: `qwen3:8b`, independently configurable from answer generation. Use temperature 0, non-streaming output, and structured JSON with named scores and explanations. Freeze the evaluator configuration across a component comparison.

- `answer_correctness_v1`: judge whether the answer accurately covers the reference answer's relevant facts. Rubric anchors: 0 incorrect/unsupported answer, 0.5 partly correct with material omissions or errors, 1 fully correct with no material errors. Do not require exact wording.
- `citation_support_v1`: judge whether factual claims are supported by their cited evidence, accounting for both citation coverage and entailment. Rubric anchors: 0 no supported factual claims, 0.5 mixed support or incomplete coverage, 1 all factual claims appropriately supported. Nonexistent labels cannot count as support. For an appropriate answer with no factual claims because it explicitly abstains, leave this score absent with a recorded not-applicable reason; correctness is still evaluated against the reference.

Give the judge the original question, reference answer for correctness, actual answer, and the exact labeled evidence supplied to generation. Instruct it to treat these as data, including any instructions appearing inside evidence. Validate response structure, finite numeric ranges, and explanations. Retry one malformed or transiently failed judge call; thereafter record an evaluation error, not a fabricated score of zero.

Trace the judge call and its output. Attach scores to the experiment item's trace using the SDK evaluator contract; ensure these are visible in experiment comparison. Add run-level mean scores with valid-score denominators, item failure count, evaluation failure count, and abstention count. Keep pipeline latency separate from evaluator latency. A partial run must remain visibly partial, with scoring coverage reported alongside averages.

### Results and comparison

Write each run's manifest and result artifacts under a unique execution directory on the mounted experiment volume; do not overwrite `latest` files as the only historical record. Store exact evidence/labels, pipeline result, scores/rationales, errors, dataset snapshot identity, and Langfuse IDs/URLs.

Use Langfuse's experiment comparison to inspect aggregate scores and item rows. Provide documented instructions for selecting one item across runs and opening its session to inspect the separate trace trees. Sessions group those traces; dataset item IDs and experiment metadata provide comparison identity. Do not imply sessions themselves create parent-child edges between separate runs.

## 7. Stage 3 — Complete integration and handoff

Aim to finish all integration during stage 2. Use stage 3 to close explicit gaps found during end-to-end acceptance: missing stage spans, missing experiment-item links, session propagation, evaluator scores, callback connectivity, or comparison visibility.

General interactive `/ask` requests should retain their current fail-open observability behavior. Experiment jobs must require valid Langfuse project/dataset access before starting and visibly report telemetry/export failures; they cannot be presented as fully recorded when their experiment linkage or scores are missing. Flush telemetry at worker shutdown and completed batch boundaries, and preserve local results for diagnosis.

Update the README, configuration template, Docker packaging/volumes, and pipeline document. Document exact seed/run/status commands, setting a remote experiment trigger in Langfuse, adding/editing QA items, changing one config component, comparing two runs or one question, and recovering from failed runs. Explain model/dataset/evaluator version controls and the difference between pipeline and execution identities.

## 8. Acceptance checks and completion criteria

Use the acceptance classification defined in section 5. Every scenario below must be tagged with its category and prerequisites in the implementation README. Scenarios that exercise live service behavior cannot be replaced by mocks for final acceptance; where an external prerequisite is unavailable, report the scenario as not run and keep the overall handoff incomplete.

Implement focused automated checks for identity stability/change detection, idempotent initial import, configuration validation, index manifest isolation, evaluator output validation, and queued-job lifecycle. Use mocked external calls for these checks. Run real integration checks separately against the configured services.

Required end-to-end scenarios:

1. Seed all 35 initial QA items. Rerun the seed command: no duplicates and no overwriting of Langfuse edits. An item added through Langfuse appears in a later unpinned run; a pinned historical run retains its original dataset.
2. Run a three-item smoke experiment. Each item has one stable question session, an experiment-linked trace tree showing retrieval through generation and evaluation, and valid scores or an explicit evaluation/not-applicable status.
3. Run the full dataset with the existing defaults: baseline mode, 30 candidates, top_k 10, passage_chars 1200, and the configured default models. Store all artifacts and report scoring coverage.
4. Repeat the full run with only passage_chars changed to 600. Reuse the same dataset and evaluator versions. Confirm a new pipeline ID, a separate index, and a distinct experiment/run identity. Compare aggregate and per-question scores without asserting in advance which configuration should win.
5. Rerun an unchanged configuration: new execution/experiment identity, unchanged pipeline fingerprint, and the same item session IDs. A prompt/code/config change must change the pipeline fingerprint.
6. Trigger an experiment from Langfuse's dataset UI. Confirm prompt acknowledgement, background completion, correct dataset/config selection, visible status, and results linked back to Langfuse.
7. Exercise an unavailable Ollama service, malformed judge JSON, empty retrieval results, invalid citation labels, partial item failure, telemetry failure, duplicate trigger delivery, and worker restart. Errors must remain distinguishable from quality scores and successful completion.
8. Select a question in two experiments. Confirm its scores and rationales can be compared, its session contains both trace trees, and each trace identifies its own pipeline configuration, dataset version, evaluator version, and experiment.

The work is complete only when these capabilities are demonstrated and their commands/results are documented. A successful trace upload alone is not sufficient.

## 9. Official references and operational unknowns

Consult the installed SDK signatures and these official references during implementation; pin compatible versions rather than assuming every latest-documentation feature exists locally:

- SDK experiment tasks, evaluations, and run summaries: https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk
- Dataset identity and versioned retrieval: https://langfuse.com/docs/evaluation/experiments/datasets
- Experiment data model and remote trigger fields: https://langfuse.com/docs/evaluation/experiments/data-model
- Remote experiment trigger behavior: https://langfuse.com/changelog/2025-07-24-remote-experiment-triggers
- Sessions and propagation: https://langfuse.com/docs/observability/features/sessions
- Score ingestion and targets: https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk

Remaining operational facts to discover during stage 1 are the actual project/API-key access, Langfuse deployment network configuration, installed Ollama models/digests, and installed Python SDK version. These do not require new product decisions. If a required credential is missing, ask for that credential through the environment's secure configuration mechanism, after completing independent preparation.

## 10. Stage 1 execution record — 2026-10-14

The following checks were run before implementation. Secrets were not printed or copied into this handoff.

| Check | Result | Evidence / disposition |
| --- | --- | --- |
| Target and reference repository state | Target `<repository root>` was clean at `ad1129a` when stage 1 inspection began. Reference `<legacy checkout>` is at `ae8472f` with modified app/config files, an untracked tracing module, and changed/untracked notebooks and generated results. | The reference working-tree differences were inspected; the target is built directly at its root. Avoid copying exploratory/generated content. Neither checkout contains a project-local `AGENTS.md`; `machine profile guidance` is the applicable machine profile. |
| Seed file | Target `QA.csv` has 35 rows and the `Question,Answer` columns; no blank fields or duplicate normalized questions were found. | Target and legacy copies match at SHA-256 `af25aeb4b0411822decab5362dced6b147379d5427e07c67143ef678f26e8844`. The target copy remains authoritative. |
| Langfuse service | Reachable at `http://127.0.0.1:28420`; `/api/public/health` returned `{"status":"OK","version":"4.59.0"}`. | Service health is confirmed. |
| Langfuse project access | The legacy `.env` contains configured key fields, but the authenticated projects request returned HTTP 401. | Credentials are not currently accepted. The `millenium` project ID, dataset state, and project permissions could not be verified. Dataset import was not attempted. Replace the credentials through the ignored local `.env`/approved secret configuration, then rerun the project access check. |
| Ollama | `http://127.0.0.1:11434/api/tags` is reachable; `qwen3:8b` is installed with digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`. | This confirms the planned initial evaluator model is locally available. |
| Python Langfuse SDK | The legacy RAG environment has `langfuse==4.17.0`. Its `Langfuse.get_dataset(name, *, fetch_items_page_size=50, version=None)` accepts a timezone-aware UTC version and forwards it to every paginated dataset-item request. `DatasetClient.run_experiment` carries the resolved dataset version through as `_dataset_version`. `Langfuse.run_experiment` is present. | The SDK's historical dataset fetch path is verified by installed source inspection. Pin `langfuse==4.17.0` when the target runtime requirements are created, then exercise a real historical fetch after project credentials are repaired. |
| Callback network route | Langfuse web and worker containers both reached the host through `http://172.18.0.1:8000/openapi.json`, which returned HTTP 200 from each. | `172.18.0.1` is the current Langfuse bridge gateway to the host. Candidate callback URL after stage 2 exposes the route: `http://172.18.0.1:8000/experiments/run`. This proves host reachability only; the route and remote-trigger settings do not exist yet. Recheck through an actual trigger after the endpoint is implemented. |

The plan defines the two versioned evaluator names/rubrics and pipeline identity/configuration fields. Root-level code now provides a read-only project/dataset access check, the seed command, typed resolved configuration, evaluator specs, and identity helpers. The SDK compatibility boundary is confirmed, but the configured Langfuse project, initial dataset import, and UI trigger cannot be completed until valid project-scoped credentials are installed. Stage 1 remains open until the project is verified and all 35 items are seeded idempotently; the trigger URL must then be configured against the implemented stage 2 endpoint and verified from Langfuse.
