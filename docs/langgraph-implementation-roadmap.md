# LangGraph v2.17 implementation roadmap

Date: 2026-11-26

Status: Roadmap for review; implementation has not started.

All steps deliver one v2.17 migration. The governing documents are the [assessment](langgraph-refactor-assessment.md), [agent graph proposal](langgraph-agent-graph-proposal.md), and [settings reference](langgraph-pipeline-settings.md).

## Working rules

- Preserve current prompts, provider requests, evidence selection, compaction, exact conversation handoff, sequential tool execution, and answer contracts, except for the agreed removal of the unused early-stop option.
- Keep one answering agent, existing Ollama/OpenAI adapters, in-memory evidence, and the existing Qdrant source.
- Validate live questions individually: fix an error or correctness regression before advancing; do not launch whole datasets as a smoke test.
- Preserve and extend Langfuse instrumentation as each execution boundary is migrated.
- Record important unresolved blockers, evidence, and the required decision in `HUMANS.md`, notify the developer, and continue independent work where possible.
- Commit reviewable changes with their relevant verification; do not publish or deploy as part of a test run.

## Step 1 — Freeze the comparison inputs

1. Record the starting Git revision, resolved v2.16 configuration, corpus/index identity, provider model identities, and evaluator versions.
2. Select exactly 10 fixed questions across QA.csv, set3, right-set-3, and Additional Questions; include broad narrative, false-premise, name, sequence, and direct-fact coverage where available.
3. Retrieve existing item-level correctness and latency from the experiment references in the assessment, using its provider-specific fallback rule; do not generate a new baseline.
4. Save a comparison manifest containing dataset/item IDs, question text or stable reference, recorded experiment/run IDs, evaluator identity, scores, latency, and model/configuration differences.
5. Choose one question with recorded results for the first live smoke check; use the same 10 questions for both providers where historical coverage permits, and document missing historical item results before proceeding.

**Completion gate:** Every selected question has an identifiable recorded comparison result for each provider being assessed; missing data is resolved rather than replaced with whole-dataset averages. The local QA.csv fallback's different model remains explicitly identified.

**Outputs:** Fixed acceptance manifest and provider-specific comparison inputs; no baseline generation calls.

## Step 2 — Verify dependencies and capture execution contracts

1. Resolve and pin a compatible LangGraph version against Python 3.12 and the current requirements in an isolated app image/environment.
2. Verify dependency installation, imports, and a minimal graph invocation without loading live models or changing the live container.
3. Run the existing agent, current-contract, pipeline, and settings tests; record failures before changing execution code.
4. Add meaningful mocked execution tests for uncovered migration-sensitive behavior: multiple calls in one reply, text-form calls, rejected submissions followed by further calls, empty-ID submission, all budget exits, final rewriting, and provider failure propagation.
5. Capture expected message order, model-call purpose, tool order, evidence order, counters, stop reasons, and result fields; use the existing runner as the executable reference.

**Completion gate:** The candidate dependency works in the app environment and execution-contract tests distinguish the documented branches without making live model calls.

**Primary files:** `app/requirements.txt`, `Dockerfile`, `tests/test_agent.py`, `tests/test_current_contract.py`, `tests/test_pipelines.py`, and relevant settings tests.

## Step 3 — Centralize settings and generate their reference

1. Introduce a typed settings-definition module containing units, brief explanations, validation, and source references.
2. Retain released values in the versioned catalog and explicit overrides in the resolver; the shared definitions must not replace historical values with current defaults.
3. Move embedded nudge, HTTP timeout, compaction, and clipping definitions into that source while preserving exact values and effective behavior.
4. Keep current runtime units for compaction and clipping; token estimates are display-only and must not change request contents.
5. Generate the human-readable settings table from definition metadata, clearly distinguishing defaults, released settings, and effective run settings.
6. Ensure effective behavioral settings are represented in run manifests and identity where needed to prevent reuse of incompatible cached answers.

**Completion gate:** Resolved settings and mocked model requests match the captured contracts; generated documentation is reproducible and contains no independently maintained copies of definitions.

**Primary files:** `app/agent/state.py`, `app/pipelines/resolver.py`, `app/models/agent.py`, `app/context/conversation.py`, `app/agent/protocol.py`, and `docs/langgraph-pipeline-settings.md`.

## Step 4 — Extract graph work and explicit state

1. Represent conversation messages, pending model reply/tool calls, candidate answer, routing outcome, counters, and final result explicitly alongside the existing evidence state.
2. Keep callbacks, clients, and observation handles in runtime context; retain the existing in-memory evidence records and their insertion order.
3. Extract callable boundaries for preparation, one model-selection turn, processing one reply's tools sequentially, reviewing answer text, drafting a budget answer, and preparing the final answer.
4. Preserve preparation order, feedback placement, conditional verification, and the different text-answer and `submit_answer` rules.
5. Rename the current `_finish` responsibility to `prepare_final_answer`, updating callers and tests while preserving its rewriting and synthesis behavior.
6. Ensure budget-answer drafting and final-answer preparation execute once each; the existing `_forced_answer` already calls `_finish`, so extraction must remove that double-call risk.
7. Remove the unused early-stop option from the v2.17 configuration and route while retaining the premise evidence probe.

**Completion gate:** Mocked execution matches the captured contracts, including evidence/messages and failure behavior; only the agreed early-stop removal changes supported target behavior.

**Primary files:** `app/agent/runner.py`, `app/agent/state.py`, `app/agent/submission.py`, `app/agent/prechecks.py`, and the instruction manifest.

## Step 5 — Wire the LangGraph execution path

1. Build a custom state graph from the extracted boundaries, keeping the existing `run_agent` entry point and result shape.
2. Route preparation to the turn/budget decision, then to model selection, sequential tool processing or text review, continuation, and final-answer preparation.
3. Preserve tool-loop `continue` semantics: rejected submissions may allow remaining calls and bypass that iteration's ordinary tool-budget check.
4. Preserve application turn and tool limits; configure the framework execution limit from the actual maximum graph transitions so its limit cannot preempt the existing budget handoff.
5. Preserve provider exception propagation and existing recoverable tool errors; introduce no automatic retry or universal fallback.
6. Keep exact handoff messages and compaction; do not inject stored passages into the final handoff or add new evidence-selection rules.

**Completion gate:** Branch tests pass through the graph, finalization occurs once, and graph control limits do not replace application budget behavior. Main model calls, verification, synthesis, and final drafting retain their existing purposes and order.

**Outputs:** Graph-backed agent entry point and routing tests; the human-readable graph matches implemented nodes and edges.

## Step 6 — Complete tracing and application integration

1. Preserve existing generation/tool observations, usage, cost fields, status events, and experiment associations while adding graph/node spans.
2. Ensure node spans surround actual execution and tool/model observations have the correct parents; avoid duplicated usage or double-counted durations.
3. Cover preparation, verification, rejected answers, tool errors, budget exits, and final-answer preparation, including existing unmeasured paths.
4. Record available prompt-token usage and context measurements against the exact model call without changing its input; label any estimates as estimates.
5. Verify interactive answering, API output, experiment execution, answer-cache identity, and intermediate-cache behavior with targeted tests.
6. Confirm telemetry failures retain the existing fail-open behavior and do not change answers or provider error handling.

**Completion gate:** Mocked trace and integration checks preserve result contracts and show the actual graph tree and timeline; live trace inspection follows in Step 8.

**Primary files:** `app/observability.py`, `app/models/agent.py`, `app/answering/execution.py`, `app/answering/cache_identity.py`, and experiment telemetry/metadata helpers.

## Step 7 — Register the v2.17 candidate and its identity

1. Add the v2.17 graph definition and its settings to the catalog, with instruction, source, settings, and cache identities that distinguish it from recorded v2.16 results.
2. Update instruction-manifest coverage for relocated message builders; compare model-visible strings and tool schemas against the captured contract rather than assuming equal source fingerprints.
3. Preserve the exact protected conversation-handoff file and its fingerprint.
4. Handle the existing catalog's release checks explicitly: `load_catalog` requires released entries and matching checksums, so candidate registration must be internally valid even before deployment acceptance.
5. Verify explicit v2.17 resolution for both providers, catalog integrity, override validation, cache separation, and the removal of the target early-stop option.
6. Preserve the v2.16 release record; do not rewrite its checksum or silently claim a changed instruction manifest is v2.16. Validate the old revision in its isolated checkout when needed; if same-checkout resolution is required, retain genuinely version-specific instruction and execution paths.

**Completion gate:** The v2.17 candidate resolves explicitly with truthful identities; existing release metadata is unmodified and there is a known starting revision for rollback. Candidate registration does not itself authorize live deployment.

**Primary files:** `pipelines.md`, `pipelines.sha256`, `app/pipelines/catalog.py`, `app/pipelines/resolver.py`, `app/agent/instructions.py`, and pipeline/contract tests.

## Step 8 — Validate live execution one question at a time

1. Run the chosen first question on the candidate with one provider and fresh generation; use the experiment CLI's single-item filter and explicit cache mode.
2. Check the answer, evaluator score, citations, tool errors, stop reason, prompt usage, result metadata, and Langfuse tree/timeline before advancing.
3. If the question regresses, inspect the trace, fix implementation errors, and use at most two additional attempts for regression diagnosis; retain all attempts and select the best correctness attempt as agreed.
4. Advance to the next question only after the previous question has no unresolved execution error or correctness regression; repeat serially across the fixed sample and both providers.
5. Compare latency using the same selected attempt as correctness, so metrics describe one actual run; retain all attempt latencies for inspection.
6. If code changes invalidate already collected results, mark them as superseded and rerun only affected items serially; final acceptance must describe one final code revision and configuration.

Use one-off containers from the repository root with the Git mount and safe-directory variables required by [AGENTS.md](../AGENTS.md):

```bash
docker compose run --no-deps --rm -T \
  -v "$PWD:/workspace" \
  -v "$(command -v git):/usr/local/bin/git:ro" \
  -w /workspace \
  -e GIT_CONFIG_COUNT=1 \
  -e GIT_CONFIG_KEY_0=safe.directory \
  -e GIT_CONFIG_VALUE_0=/workspace \
  app python -m app.experiments --dataset DATASET --pipeline v2.17 --item-id ITEM_ID --cache-mode bypass
```

Replace dataset and item placeholders with one selected question; apply provider overrides using the actual CLI options verified during implementation.

**Completion gate:** All selected question/provider runs have complete comparable results, observable execution, and no unresolved migration error; important blockers are escalated rather than hidden by aggregate scores.

## Step 9 — Assess acceptance and prepare the release

For each provider, calculate equally weighted means across the same 10 selected questions:

- Correctness loss = mean recorded baseline correctness minus mean selected candidate correctness; it must be no greater than 0.10 absolute points.
- Latency increase = mean selected candidate latency divided by mean recorded baseline latency, minus one; it must be no greater than 10%.
- Use at most three attempts per regressed question, select its best correctness attempt, and preserve all attempt records; model/configuration differences in fallback baselines remain visible.
- Quality takes priority; investigate and reduce excessive latency without changing agreed evidence, verification, or handoff behavior.

1. Run the relevant full automated test suites after targeted checks pass, including catalog, agent, settings, cache, API, and experiment workflow coverage.
2. Produce an acceptance report linking item-level results, selected attempts, provider configurations, evaluator identities, final revision, Langfuse traces, and aggregate calculations.
3. Generate the final settings reference and update the graph/version signature and code references to match the implementation.
4. Prepare the default-version/deployment change and rollback instructions for review; apply live deployment only when authorized.

**Completion gate:** Both providers meet the agreed acceptance criteria, required checks pass, instrumentation is verified, and the release is concrete and reviewable.

## Definition of done

The v2.17 graph executes the agreed pipeline with one agent, sequential tools, both adapters, unchanged context/handoff behavior, centralized documented settings, truthful pipeline/cache identity, complete Langfuse visibility, and recorded acceptance evidence; the unused early-stop option is removed from the target pipeline.

This roadmap creates no implementation, live experiment, or deployment by itself. Dependency compatibility, selected question IDs, and item-level comparison data remain work in Steps 1–2 rather than assumed completed checks.
