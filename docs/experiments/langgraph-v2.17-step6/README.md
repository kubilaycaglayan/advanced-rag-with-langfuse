# v2.17 Step 6 — tracing and application integration

Completed 2026-11-26. Starting revision: `ae0ae57`, after Step 5. Scope: [roadmap Step 6](../../langgraph-implementation-roadmap.md) only. The default remains v2.16 and `resolve('v2.17')` still fails: candidate registration is Step 7. No live models, live experiments, Langfuse trace uploads or deployment were used for this verification.

## Execution visibility

The graph now has an `agent graph` observation around invocation and `graph node: NAME` observations around each actual boundary execution. Existing agent, turn, tool, precheck, verification, synthesis and forced-answer observation names remain intact. Callbacks and observation handles stay in runtime context; state, messages and evidence still follow the existing contracts.

Node input/output summaries record routing, turn/tool counts, evidence/rejection counts, verification outcome, budget reason, draft/final completion and stop reason. They do not record usage or cost. Generations remain the only observations receiving usage/cost fields, so graph/node instrumentation does not duplicate inference accounting. Span durations are inclusive wall time from actual context entry/exit; ancestor and descendant durations must not be summed as independent costs.

Recovered tool errors are marked ERROR on their tool observation. Failed verification is WARNING with the actual verdict/reason. Repeated rejected text and submissions have WARNING observations around the feedback work, without additional verification or model calls. Preparation is inside its node span, including work previously outside the agent root; budget drafting and final preparation have separate node spans. Existing final rewriting and synthesis observations remain children of final preparation.

[The mocked trace artifact](mock-traces.json) contains observed trees and timelines from the real graph and provider adapter with an in-memory SDK and mocked HTTP/retrieval. Cases cover tool failure and rejected submissions, budget synthesis, sequence rewriting, provider failure, and telemetry entry outage. It is explicitly **not live Langfuse evidence**. `scripts/capture_graph_telemetry.py` reproduces it with `PYTHONPATH=/workspace:/workspace/tests` in the verification container.

## Exact call measurements

[agent_context.py](../../../app/models/agent_context.py) observes each already-constructed provider request immediately before transport, after compaction and provider conversion. It does not compact again, select passages, truncate, or alter the request.

Generation metadata includes the canonical JSON payload hash and character size, serialized message/schema sizes, message count, compacted result count, output allowance, local configured context window where applicable, and available provider prompt-token usage with an availability flag. Request token estimates are explicitly labeled **serialized request characters / 4**, not tokenizer or provider chat-template measurements. A test intentionally exceeds the local planning window through a long precheck and large recent results: measurement observes that input without adding truncation rules.

Generation input remains a JSON message list for the existing faithfulness evaluator. It is updated to the actual post-compaction conversation instead of retaining the earlier pre-compaction snapshot. The payload hash identifies the fully converted provider request; character counts describe canonical JSON, not HTTP framing or tokenizer counts. Ollama, OpenAI Chat Completions and OpenAI Responses all have request/usage tests; cached-input costs remain counted once. The six frozen Step 2 request payload/timeout contracts still match exactly.

## Application and identity boundaries

`ResolvedRun` has an explicit `execution_backend`, defaulting to `legacy`. The answering boundary can select the graph only for an explicitly identified v2.17 run with target settings. It rejects graph execution labeled v2.16 and target settings sent to the legacy backend. No new public settings override or catalog entry is exposed. Tests inject synthetic candidate resolutions at the preparation/resolution boundary; actual public v2.17 resolution remains unsupported until Step 7.

Interactive answering, `/ask`, streaming, experiment execution and their output/status contracts have targeted tests using the actual graph. A streaming test follows the observation and trace attributes across the API worker thread. An experiment test runs a synthetic item through task execution, writes its local manifest/results and checks graph provenance, including when telemetry scope entry fails. These tests use temporary storage and fake clients rather than creating external experiment records.

Graph answer/intermediate cache identities add backend, target instruction fingerprint and current source fingerprint. Experiment manifests record the same execution identity, using the run's already captured source fingerprint. Existing execution/dataset/item/session/provider/evaluator associations are retained, with backend metadata added. Early-stop metadata is emitted only for the legacy schema that actually contains it.

An approved graph answer-cache hit skips generation and preserves a fresh serving trace plus source-trace link. Intermediate-cache reuse works inside actual graph invocation context. Source/instruction changes separate graph answers and intermediates. Both providers' complete v2.16 answer-cache identities were captured from the isolated Step 5 checkout and match the new implementation exactly; the new backend dimension is omitted for legacy execution. [Recorded identities](legacy-cache-identities.json).

## Fail-open correction

A pre-existing telemetry context bug was reproduced before production changes: failed context entry could skip answering with “generator didn't yield,” failed exit could replace a provider exception, and SDK suppression could hide that exception. The disabled scope path could also mishandle an exception from its body.

Commit `6f4b5ec` records the failing regression tests. Commit `171f85f` fixes context entry/exit independently from application work: work executes once after telemetry entry failure, success survives exit failure, and original provider exceptions are re-raised even if telemetry exit fails or requests suppression. Observation update failures also remain fail-open. The focused regression and full 235-test suite passed before the broader Step 6 additions.

Experiment task/session propagation now uses this same safe scope, including the SDK item hook. An additional regression verifies scope failure cannot skip the entire SDK item. Existing required-trace API policy is retained; this work does not bypass that application's explicit trace-admission guard.

Evidence: [failing regression run](fail-open-before.log), [initial passing regression](fail-open-after.log), [post-fix suite](fail-open-suite.log), and final full suite below. Intermediate integration failures exposed a remaining legacy-only early-stop metadata access and fixture mistakes in cache approval/fake SDK metadata merging; those were corrected without relaxing cache approval or changing answering policy. A circular import introduced during integration was removed by loading the target instruction fingerprint lazily.

## Verification and stopping gate

- Final full Python suite: **250/250 passed**, no failures or errors. [Log](full-tests.log).
- Five fail-open regression methods, six tracing/context methods and eight integration methods are included in that final run, alongside all previously captured contracts and graph routes.
- Actual pinned Langfuse update signatures accept the status, metadata, usage and cost fields used here. [SDK signatures](sdk-signatures.log).
- Protected v2.16 runner, catalog/checksums, handoff, compaction/clipping, prechecks, final-answer helpers and dependencies are byte-for-byte unchanged from Step 5. Legacy instruction identity and both providers' cache identities are preserved.
- The graph reference and settings reference both pass their generation checks. The graph topology and application budget limit remain unchanged.
- Both providers' mocked request payloads/timeouts still match the frozen contracts. Telemetry setup, entry, exit and update failures preserve successful answers, inference counts and provider failures.

[verification.json](verification.json) records revisions, identities, protected files and artifact hashes. No unresolved Step 6 blocker remains. Live tree/timeline inspection, real prompt pressure, quality and latency acceptance remain Step 8; mock traces do not establish them.

Reproduce the final suite using the Step 2 isolated image and Compose override:

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

Run from the repository root. The live app container was untouched. Step 6 is complete; stop before candidate catalog registration in Step 7.
