# Backend and Express server code organization refactor

Date: 2026-11-25
Status: Complete. See `docs/experiments/2026-11-25-organization-verification.md` for checks, comparisons, investigated differences, and limitations.

## Objective and agreed decisions

Make the code easier for humans to navigate, read, and understand by organizing it around clear responsibilities and extracting responsibilities currently mixed inside large modules.

- Cover the Python backend and the frontend Express server. Exclude changes inside the UI submodule (`frontends/millennium/ui/`) and changes to its submodule pointer.
- Preserve behavior, generation instructions, tool contracts, API responses, pipeline defaults, frontend appearance, and interactions.
- Keep the pipeline named **v2.16**. Preserve instruction and index identities where possible; source fingerprints will change.
- The UI is the only identified consumer. Internal Python imports may change; preserve the HTTP contract and documented commands.
- Validate with automated tests, small live checks using both providers, and experiments using selected questions from all four Millennium datasets.
- Record behavior improvements separately rather than implementing them as part of this refactor.
- Preserve historical experiment results, manifests, scores, traces, and reports.
- Deployment, pushing, and publication are outside this plan.
- User approval: run the paid comparisons and commit frequently. Never rebuild indexes; skip any step that would require rebuilding, continue other work, and report the skipped step for acknowledgment in the final report.

This follows the completed v2.16 maintenance cleanup. It is a separate organization refactor, not another historical-code removal pass.

## Implementation approach

Use small, reviewable commits. Each commit must leave the supported execution path working and include the necessary caller, test, and documentation updates. Separate mechanical moves from substantive extraction when practical. Avoid introducing folders or abstractions that do not improve navigation or clarify ownership.

The UI at `frontends/millennium/ui/` is an unchanged consumer for this refactor. Do not reorganize its components, hooks, routes, API client, preview code, or configuration, and do not update its submodule pointer. Existing UI tests and builds may be used to verify compatibility without changing UI source.

## Step 1: Establish the baseline

Record the backend commit, UI submodule commit, working-tree state, and existing test results. Identify pre-existing failures before changing code.

Capture the contracts to preserve:

- Resolved settings, defaults, prompts, tool schemas, and instruction manifest.
- Answer fields, citations, streaming events, tracing, and cache behavior.
- Pipeline, corpus, model, and index identities.
- Agent precheck ordering, tool side effects, verification, synthesis, and budget exits.
- Express request/response contracts, streaming, feedback, trace access, session ownership, and client-IP handling. Verify compatibility with the unchanged UI.

**Completion gate:** Existing failures are identified and preserved behavior has a reproducible baseline.

## Step 2: Select and run baseline regression experiments

Use the four Millennium datasets listed in corpus configuration:

1. `QA.csv`
2. `Additional Questions`
3. `set3`
4. `right-set-3`

Start with three questions per dataset. Select the exact item IDs after reviewing the datasets and available historical evidence. Cover direct facts, connections, scenes/moments, sequences, premise correction, and broad answers across the selection. Include previously difficult cases rather than selecting only high scorers.

Record dataset versions, item IDs, provider/model settings, evaluator versions, index identities, and cache policy in a comparison manifest. Run the same 12 selected questions with both Ollama and OpenAI: 24 baseline question executions, repeated after the refactor.

Preserve source dataset membership by using separately labeled runs for each dataset and provider, linked by the comparison manifest. Bypass reusable answer and intermediate caches for the quality comparison so cached baseline answers cannot conceal a regression; check cache behavior separately with focused tests.

Record answers, correctness, citation support, abstentions, traces, failures, latency, tool calls, and usage. Pin available model identities and record any external model variability or changes.

**Completion gate:** Baseline experiment artifacts and settings are recorded before implementation begins.

## Step 3: Define module ownership and dependency rules

Create a concise code map assigning existing functions to their intended owners.

| Area | Responsibility |
| --- | --- |
| `agent/` | Agent loop, prechecks, verification, synthesis, model-facing tool wrappers |
| `retrieval/` | Semantic/keyword search, scene/entity/name lookup, query transformation, reranking |
| `context/` | Evidence storage, focus/provenance, conversation management, citation formatting |
| `indexing/` | EPUB extraction, chunking, passage/scene/entity index creation and manifests |
| `pipelines/` | Catalog, resolved configuration, resolution, execution adapter |
| `answering/` | Shared question execution and answer-cache coordination |
| `experiments/` | Dataset execution, queue, persistence, artifacts, CLI |
| `evaluation/` | Judges, evaluator definitions, metrics, review |
| `models/` | Provider clients and embedding/reranking model access |
| `api/` | HTTP validation, routes, streaming transport |
| `cache/` | Answer and intermediate caches |
| Corpus configuration/profiles | Corpus-specific configuration, prompts, and behavior |
| Observability | Tracing, observations, and usage reporting |

Dependency rules:

- Retrieval must not depend on the agent loop or its conversation.
- Context handling must not call model providers.
- Agent tools validate model arguments, call retrieval/reading operations, update evidence state, and format tool results.
- The agent runner coordinates these responsibilities.
- API transport concerns stay outside retrieval and agent logic.
- Keep small responsibilities together until splitting them improves understanding.

**Completion gate:** Existing functions have clear owners and the proposed dependencies avoid circular imports.

## Step 4: Prepare imports and integrity checks for moves

Standardize Python execution around the `app` package and update Docker entry points and callers accordingly. Replace duplicated relative/top-level fallback imports as consumers migrate.

Make instruction-manifest collection work across modules rather than parsing only `agent.py`. Update handoff-file lookup and file-relative resource paths so they survive relocation.

Compare the old and new instruction manifests before moving instruction builders. Preserve hash inputs where possible. Document any unavoidable identity migration while retaining v2.16 and historical records. Do not weaken validation, accept arbitrary hashes, or silently refresh protected values to make tests pass.

Keep the final-handoff file contents unchanged where possible; its bytes are separately protected.

**Completion gate:** Application startup, documented CLI commands, instruction tampering checks, and handoff checks pass.

## Step 5: Extract retrieval and model access

Split the retrieval responsibilities in `pipeline.py` into clearly named modules. Move reusable retrieval logic out of `agent.py`, retaining agent-specific state updates in tool wrappers.

Give shared underscore-prefixed helpers deliberate public interfaces. Introduce passage/search-result types at useful boundaries without attempting a wholesale typing rewrite.

Preserve ranking, limits, result ordering, cache keys, model parameters, and observation names. Keep query-generation provider behavior unchanged: choosing the OpenAI agent does not move existing local query transformations to OpenAI.

**Completion gate:** Search and query transformations retain their behavior, and retrieval is understandable independently of the agent.

## Step 6: Split the agent and context handling

Extract in small increments:

1. Settings and execution state.
2. Evidence storage, focus, and retrieval provenance.
3. Conversation formatting and compaction.
4. Tool groups, schemas, and dispatch.
5. Prechecks and their message builders.
6. Submission verification, coverage checks, synthesis, and citation handling.

Leave the main agent runner as a readable coordinator. Preserve precheck ordering, budgets, tool side effects, message contents, and forced-answer conversation handoff.

Update tests to patch the modules that own the behavior. Migrate tests that parse only `agent.py` to cover the relevant modules or observable behavior without reducing instrumentation coverage.

**Completion gate:** Contract fixtures, tool behavior, observations, and timeout/tool/turn budget exits pass.

## Step 7: Organize indexing, configuration, and evaluation

Group existing modules into their packages. Separate index building from runtime lookup and give index manifests a clear owner; they currently share storage code with experiment jobs.

Keep evaluator management distinct from generation instructions. Preserve corpus profile assets and their relative loading paths.

Avoid editing source-hashed chunking functions during mechanical moves. Check passage, scene, and entity identities rather than assuming a file move cannot affect them.

**Completion gate:** Both corpus profiles resolve correctly, existing indexes validate, and unchanged index inputs produce unchanged identities wherever possible. Any unavoidable change is explained before rebuilding anything.

## Step 8: Simplify API and experiment orchestration

Make `main.py` a small application entry point. Separate question, indexing, experiment, feedback, and model-proxy routes.

Extract shared question-execution behavior carefully. Preserve intentional differences between interactive requests and experiments, including cache policy, tracing requirements, dataset handling, and index preparation.

Separate experiment queueing, dataset selection, execution, persistence, and CLI responsibilities. Retain documented commands through thin entry points where necessary; do not add broad compatibility wrappers for private imports without an identified consumer.

**Completion gate:** Requests, streams, caching, rate limits, admission locks, retries, experiments, and trace uploads pass their checks.

## Step 9: Reorganize the frontend Express server

Keep `server.js` as the entry point. Extract cohesive modules for:

- Question forwarding and streaming.
- Feedback and trace access.
- Session ownership and client-IP handling.
- Response mapping and configuration.
- Static serving and development startup, where extraction improves clarity.

Preserve request limits, trusted-proxy handling, cookies, trace access restrictions, and pipeline/provider selection. Update the frontend Dockerfile to copy extracted server files; it currently copies only `server.js`.

Preserve Express static serving and development proxy behavior for the unchanged UI. Lovable preview code and its sample answers remain outside the change scope.

**Completion gate:** Server tests, production build, streaming, access checks, and development proxying pass with the existing UI submodule. No UI source or submodule pointer changes are present.

## Step 10: Run final verification and regression comparison

Repeat the exact selected experiments with the baseline dataset versions, item IDs, settings, evaluators, and cache policy.

Compare each question as well as per-dataset/provider aggregates:

- Correctness and citation support.
- Abstentions and missing answer parts.
- Errors, budget exits, and unexpected tool behavior.
- Trace completeness and experiment completion.
- Latency, tool calls, and usage.

Investigate every quality drop. Repeat affected baseline/refactored cases when necessary to distinguish model variability from a refactor regression. Exact answer text need not match, but deterministic contracts must match. Do not accept an aggregate improvement as a reason to ignore an individual regression.

Run the complete relevant Python and Express server suites, frontend compatibility tests/builds against the unchanged UI, application startup checks, and focused live checks for both providers. Exercise the API-to-UI path, streaming, feedback, and trace viewing. Confirm the UI source and submodule pointer are unchanged.

**Completion gate:** No unexplained behavior changes or regressions remain in the selected sample. Document the sample's limits; it does not prove equivalence across every question.

## Step 11: Finish documentation and remove transitional code

Update the README, technical guide, commands, and code map. Explain how a question moves through the system and where a developer should change search, tools, prompts, evidence handling, evaluation, and Express server behavior. Identify the unchanged UI submodule as a separate consumer.

Remove temporary wrappers once callers migrate. Record unrelated improvements in a separate backlog. Any pipeline diagram created or updated must visibly identify v2.16, aligned with `pipelines.md`.

Publish a verification report recording test results, baseline/final experiment references, identity comparisons, investigated differences, and remaining limitations. Preserve historical reports unchanged.

**Completion gate:** The repository is navigable without reading a large coordinating module, documented commands match the code, and the verification evidence is reviewable.

## Execution safeguards

Run repository commands from the repository root. Use separate one-off containers for Python verification and experiments, leaving the live app container untouched.

Follow the root AGENTS.md container instructions, including the mounted Git binary and Git safe-directory variables. Isolate test locks/data with `EXPERIMENT_DATA_DIR` pointing to a test-specific temporary location. Keep intended new verification runs separately labeled; do not overwrite historical experiment artifacts or scores.

Run focused checks after each extraction and full relevant suites at integration milestones. Do not repeat paid/live experiments after every mechanical move; use deterministic checks during implementation and repeat the pinned question selection for final verification, with targeted reruns when failures require them.
