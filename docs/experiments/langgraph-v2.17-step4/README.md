# v2.17 Step 4 — execution boundaries and explicit state

Completed 2026-11-26. Starting revision: `fc7608f`, after Step 3. Scope: [roadmap Step 4](../../langgraph-implementation-roadmap.md) only. LangGraph is not wired, the target is not registered in the catalog, and the live application still selects the released v2.16 entry point. No live model generation, experiment, publication or deployment was performed.

## Extracted work

[execution.py](../../../app/agent/execution.py) provides callable boundaries and a small imperative driver for testing them before graph wiring:

| Boundary | Responsibility |
|---|---|
| `prepare_question` | Normalize; execute connection, initial scene, true-account, sequence, moment and premise checks in their existing order; retain message placement. |
| `decide_next_turn` | Apply existing turn/time limits, including incrementing the timeout turn counter before checking elapsed time. |
| `select_model_turn` | Make one model-selection request, parse structured or text calls, and expose the pending reply and route. |
| `process_reply_tools` | Process one whole reply sequentially, count before dispatch, preserve feedback, conditional verification, rejected-answer continuation and ordinary budget exits. |
| `review_answer_text` | Preserve the text-answer rejection, minimum-investigation, coverage, verification and no-tool nudge order. |
| `draft_budget` | Draft once from the exact protected conversation handoff, without final preparation. |
| `finalize_answer` | Call final-answer preparation once, retain the result, attach the accepted submitted payload, and complete root observation output. |

[ExecutionState](../../../app/agent/state.py) inherits the existing in-memory evidence store and insertion order. It adds conversation messages, pending reply/content/calls, next tool index, candidate answer/IDs/raw answer, submitted payload, verification outcome, route, budget reason, completion flags and final result. Existing counters, rejection tracking and retrieval provenance remain intact. `AgentRuntime` holds the event callback, tool schemas and observation handle separately from that state. The existing provider adapters continue to manage their requests; no clients or observation handles are stored in execution state.

This is still process-local execution, not a durable checkpoint schema. No persistence or automatic retries were enabled. The completion flags prevent repeated successful budget drafting and final preparation within the run; they do not claim exactly-once external effects across crashes or restarts.

## Final preparation and version separation

The old `_finish` implementation is now named `prepare_final_answer` in [submission.py](../../../app/agent/submission.py). Its complete function-body AST is unchanged: sequence rewriting, synthesis, speech fallback, citation formatting and output packaging retain their current behavior. Ordinary helper tests now call its descriptive name.

`draft_budget_answer` contains only the existing handoff drafting work and returns answer text plus IDs. The extracted path routes that draft to the shared final preparation boundary. The legacy `_forced_answer` remains a compatibility composition of drafting plus `_finish`, and `_finish` is an alias of the renamed function, for the released v2.16 runner and its patch boundaries. The target does not call either legacy composition or alias, so a budget answer cannot be finalized twice by accidentally chaining them.

`TargetAgentSettings` contains the shared typed configuration without `premise_early_stop`. The released `AgentSettings` schema retains that field as a v2.16-only extension. The target rejects legacy settings objects and has no direct premise-resolution branch, while still executing the premise evidence probe before normal model selection. There is no new resolver version or settings override surface in this step.

The released [runner.py](../../../app/agent/runner.py), catalog, release checksum file, protected handoff file and public answering integration are byte-for-byte unchanged from Step 3. Both providers still resolve v2.16 with unchanged settings and pipeline IDs. This deliberate version separation prevents relocated message builders from being silently represented as the old released execution path.

The [instruction manifest](../../../app/agent/instructions.py) now has separate target manifest/fingerprint functions covering the relocated preparation, selection, tool-processing and text-review builders, plus budget drafting and final preparation. Existing system/synthesis prompts, tools and shared builders remain covered. The v2.16 fingerprint is unchanged; the unregistered target fingerprint is distinct, and a tampering test proves edits to a relocated instruction change the target identity without changing the released one. Candidate catalog registration remains Step 7.

## Verification

- After splitting drafting from final preparation, all **199** existing Python tests passed. [Log](finalization-split-tests.log).
- All **16** captured execution-contract methods now also run against the extracted driver, with their assertions unchanged. Only the harness was generalized to select the runner, settings type and final-preparation patch point.
- New direct tests cover explicit state/runtime separation, target early-stop removal, retained premise evidence, standalone boundary routing, pending tool position, candidate state before finalization, successful draft/final completion guards and relocated instruction protection.
- Four differential scenarios compare the released and extracted paths under a deterministic clock: multiple retrieval calls and a text answer; rejected submission followed by another submission; empty-ID submission followed by synthesis; and recoverable tool failure followed by investigation. They compare full model-call inputs/purposes, events, tool calls, evidence/provenance and final result fields, including timing values.
- The inherited contracts additionally cover all three budget exits, structured/text calls, tool-level rejection versus verification/repeated-answer rejection, feedback order, shared nudge limits, preparation order, focus selection, conditional verification, final rewriting and provider-specific error propagation.
- Final full Python suite: **222/222 passed**, no failures or errors. Generated settings documentation also passes `--check`. [Final log](full-tests.log).

The initial direct-boundary test used a process start timestamp of zero, so the timeout check correctly routed it to a budget answer. The fixture was corrected to use the current process clock and an explicit investigation minimum; no application behavior was changed to satisfy it. [The targeted run](extraction-tests.log) records 22 passing methods before the additional real-premise-probe test; the final full run includes all 23 target tests.

[verification.json](verification.json) records the implementation revision, release/handoff comparisons, instruction identities, unchanged final-preparation AST, unchanged captured contract assertions and evidence hashes. Model calls and retrieval are mocked; these tests do not establish live quality, latency, or Langfuse hierarchy acceptance. Existing observation names and model-call purposes remain present; graph/node span hierarchy and live trace review remain later steps.

No unresolved Step 4 blocker remains. The generated settings reference was refreshed to identify the retained early-stop field as v2.16 compatibility only.

## Reproduction and stopping point

Use the Step 2 isolated verification image and Compose override described in [its record](../langgraph-v2.17-step2/README.md). From the repository root:

```bash
docker compose -f compose.yaml -f /tmp/millenium-langgraph-step2-compose.yaml run --no-deps --rm -T \
  -v "$PWD:/workspace" \
  -v "$(command -v git):/usr/local/bin/git:ro" \
  -w /workspace \
  -e GIT_CONFIG_COUNT=1 \
  -e GIT_CONFIG_KEY_0=safe.directory \
  -e GIT_CONFIG_VALUE_0=/workspace \
  -e LANGFUSE_TRACING_ENABLED=false \
  app python -m unittest discover -s tests -v
```

For the extracted contracts alone, replace the command after `app` with `python -m unittest discover -s tests -p test_agent_extraction.py -v`. To check the generated reference, use `python -m app.settings_reference --check`.

Step 4 completion gate is satisfied. Stop before constructing the LangGraph graph, configuring its transition limit, or changing application routing in Step 5.
