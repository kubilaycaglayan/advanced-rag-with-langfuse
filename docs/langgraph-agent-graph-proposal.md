# Proposed agent graph

Date: 2026-11-25

**Status:** Design suggestion only. No implementation or new pipeline version is introduced.

**Behavioral baseline:** v2.16, the currently supported version in [the pipeline catalog](../pipelines.md). This graph proposes an orchestration structure around that behavior; it is not an exact executable specification.

See also the [adoption assessment](langgraph-refactor-assessment.md) for risks, alternatives, and preparation work.

## The idea in plain language

Keep one answering agent. Give it a clearly defined process: understand the question, gather initial evidence, choose what to investigate, use tools, review candidate answers, and apply the current finishing rules. Verification is conditional; the current pipeline does not verify every final answer. When investigation runs out of time or allowance, use the existing conversation handoff to produce a final answer.

The boxes below are steps in that process, not separate autonomous agents. Most reuse existing Python functions. Only steps that already call a model need model calls.

## Suggested graph

Rectangles represent work; diamonds represent decisions. The loop means the agent can investigate again when evidence is insufficient.

```mermaid
flowchart TD
    signature["Proposed orchestration — v2.16 behavioral baseline"]
    prepare["1. Prepare question and initial evidence"]
    early{"Verified early answer available?"}
    budget{"Another model turn allowed?"}
    think["2. Ask model for next action"]
    route{"Tool calls or answer text?"}
    tools["3. Process tool calls in order"]
    review["4. Review answer text"]
    outcome{"Tool processing outcome?"}
    accepted{"Answer accepted?"}
    feedback["5. Continue with updated conversation"]
    forced["6. Draft answer from conversation handoff"]
    finish["7. Repair or synthesize if needed; format result"]
    signature --> prepare
    prepare --> early
    early -->|"Yes"| finish
    early -->|"No; default configuration"| budget
    budget -->|"Yes"| think
    budget -->|"Timeout or turn limit"| forced
    think --> route
    route -->|"Tool calls"| tools
    route -->|"Answer text"| review
    tools --> outcome
    outcome -->|"Submission accepted; verification conditional"| finish
    outcome -->|"Tool budget exit"| forced
    outcome -->|"Continue investigation"| feedback
    review --> accepted
    accepted -->|"Yes"| finish
    accepted -->|"No"| feedback
    feedback --> budget
    forced --> finish
```

This diagram groups some decisions for readability. In particular, tool processing includes submission verification, and finalization includes existing answer repair or synthesis behavior. The exact ordering described below must be preserved during an initial migration.

## What each step does

| Step | Human meaning | Existing code to reuse |
|---|---|---|
| 1. Prepare | Correct recognized name issues and gather useful context before asking the model. | `app/agent/prechecks.py`, initial scene probe in `app/agent/tools/scenes.py` |
| 2. Ask model | Let the model choose a tool or propose an answer using the current conversation. | `app/models/agent.py`, `app/agent/protocol.py` |
| 3. Process tools | Run requested tools sequentially, remember evidence, and handle `submit_answer` specially. | `app/agent/tools/dispatch.py`, `app/agent/submission.py` |
| 4. Review answer | Check whether answer text can be accepted or needs more investigation. | Existing no-tool branch in `app/agent/runner.py` |
| 5. Continue | Route back with messages already updated by tool processing or answer review. This can be an edge rather than a work node. | Existing loop continuation |
| 6. Conversation handoff | Draft an answer without model-selected tools when a budget exit occurs. | Drafting portion of `_forced_answer` and `app/context/agent_final_handoff.py` |
| 7. Finalize | Apply current finishing behavior and return the established result contract. | `_finish` and `app/answering/execution.py` |

**Implementation boundary:** `_forced_answer` currently calls `_finish` itself. To implement the diagram literally, extract its drafting portion before routing to the shared finishing node. Alternatively, retain `_forced_answer` intact and route its completed result directly to the output. Never call `_finish` a second time on that result. Feedback is appended inside tool processing and text review, in its existing order; step 5 is only a continuation marker.

The early-answer decision preserves `premise_early_stop`. It is disabled in the released v2.16 configuration. When enabled, a proposed direct premise resolution still requires verification.

## Important routing rules

### Preparation order

Use the actual runner order as the migration baseline:

1. Normalize the question and record name notes.
2. Run the connection precheck.
3. Run the optional initial scene probe and assemble its message.
4. Append the connection precheck message when applicable.
5. Run the true-account precheck.
6. Run the sequence precheck.
7. Run the moment precheck.
8. Run the premise probe.
9. Consider verified direct premise resolution if enabled.

These steps can initially remain inside one preparation node. Splitting them into individual nodes later is useful if separate inspection or recovery boundaries are needed. Do not parallelize them as part of the first migration.

### A model reply containing tools

- Preserve support for both structured calls and the existing parser for tool calls written as text.
- Assign missing call IDs as today and preserve message order.
- Execute calls one at a time. A model reply can contain more than one call. Increment `tool_calls` before dispatch, including for `submit_answer` and failed calls.
- Treat recoverable tool failures as observations the model can use.
- Preserve name-correction messages and search-progress hints. Append tool results and hints before checking the ordinary tool-budget exit, so the forced-answer handoff sees the latest result.
- A submission can finish the run immediately; do not execute remaining calls after an accepted submission.
- Preserve rejected-answer and verification branches before applying the existing tool-budget exit rule.

**Submission-specific conditions:** `_tool_submit_answer` rejects empty answers, missing evidence, insufficient tool calls, unknown IDs, and a coverage gap. Its minimum is one tool call when a speech hint exists; otherwise it uses `min_tool_calls`. If evidence already exists, an empty `passage_ids` list is not itself rejected. The runner only calls `_verify_submission` when that list is nonempty. Therefore an accepted submission is not necessarily a verified submission.

A rejected prior answer or failed verification uses `continue` inside the tool loop: remaining calls in the same model reply can still run, and that iteration skips the ordinary tool-budget check. This is existing behavior, not a recommended new policy.

For the first implementation, process a whole reply's tool calls within one node. Persisting a cursor and splitting execution into one node invocation per tool is a later option if recovery between calls becomes a requirement.

### A model reply containing answer text

Preserve the current review sequence:

1. Extract citation IDs that refer to collected evidence.
2. Reject a previously rejected central answer.
3. Apply the minimum-tool nudge when the count is below the minimum and the shared nudge count is below two.
4. If evidence exists, check coverage and request further investigation if needed. `_coverage_gap` applies only to matching sequence questions and issues at most one gap rejection per run; it may retrieve and remember additional evidence.
5. Verify the submission when citation IDs exist; reject unsupported claims.
6. When citations are absent, apply the no-tool nudge if the shared nudge count is below two; otherwise append the supported-answer request and continue. This path cannot accept uncited text directly.
7. Accept eligible answer text and finalize it.

The text-answer path and `submit_answer` path are not identical today. Keep their distinct rules initially instead of forcing both through a newly invented common policy.

### Budget exits

The diagram's budget decision summarizes the current turn-loop behavior. It does not propose a new universal guard before every operation.

- Timeout is checked at the start of a model turn.
- Turn exhaustion leads to conversation handoff.
- Tool-budget checking occurs within tool processing, after specific branches that can return or continue first.
- All three existing budget exits must retain the v2.16 conversation handoff.

A strict deadline before every tool, or uniform tool-limit enforcement across all branches, could be useful later. Those would be behavior changes and should be evaluated separately.

### Finishing is active work, not just formatting

`_finish` can change an accepted candidate:

1. For matching sequence questions with evidence, if the answer lacks confrontation or has fewer than three stages, gather a coverage hint and try synthesis. Adopt the rewrite only if it contains confrontation and increases the number of covered stages.
2. If IDs are missing, the answer looks like abstention, or recognized citation syntax is absent, try evidence-based synthesis when evidence exists.
3. If the answer still looks like abstention and a speech hint exists, substitute the hinted quotation and its passage ID.
4. `_final` converts passage citations to labels and packages evidence, usage, trace, counts, and latency.

These rewrites are not sent through `_verify_submission` again. Budget handoff drafts also reach `_finish` without submission verification. Finishing may retrieve evidence and make additional model calls, even after a loop budget exit. Thus “no tools” in the handoff means no model-selected tool calls, not that finalization performs no retrieval.

### Failures that leave the normal graph

The main diagram shows normal control flow, not exception edges. Exceptions raised inside `_run_tool` are converted into tool error payloads. Main model-call failures can propagate. The verifier rejects malformed verdicts; local-provider call failures are treated as failed verification, while OpenAI provider failures are re-raised. Some operations outside those exception handlers can also fail. Do not replace these distinctions with automatic retry or a universal forced-answer fallback during a parity migration.

## What the graph needs to remember

The current `AgentState` is a starting point, but the conversation and local runner decisions also need explicit representation.

| State group | Contents | Why it matters |
|---|---|---|
| Run identity | Original and normalized question, corpus, collection, pipeline and configuration identity | Prevents mixing evidence or results from different runs |
| Conversation | Ordered messages, tool-call IDs and compacted results | Preserves what the model sees and the final handoff |
| Evidence | Passage records, insertion order, deliberate focus and retrieval queries | Preserves citation meaning and provenance |
| Progress | Turns, tool count, nudges, coverage checks and resolved names | Keeps loop decisions consistent |
| Review | Rejected answers, candidate answer and verification outcome | Prevents accepting unsupported answers on a later pass |
| Pending work | Model reply, requested calls and explicit next action | Makes routing understandable and testable |
| Result and telemetry | Final result, stop reason, trace and usage | Preserves API, experiment and observability contracts |
| Time budget | Explicit elapsed-time or deadline policy | Supports a future restart-safe budget model |

Keep network clients, callbacks, tracing handles, and other runtime resources outside persisted state. If persistence is enabled, define serialization and schema-version rules before storing checkpoints. A process-local `perf_counter()` value cannot serve as the cross-process deadline contract.

## Boundaries outside the graph

- **API and UI:** Continue calling the existing answering boundary and receiving its result shape and status events.
- **Retrieval and indexing:** Keep their current implementations; graph nodes call them through existing tools.
- **Provider adapters:** Keep current Ollama and OpenAI request formatting and response normalization.
- **Experiment scheduling:** Keep job scheduling separate from the graph for a single question.
- **Caching and identity:** Distinguish any experimental graph implementation from baseline results so cached answers cannot conceal behavioral differences.
- **Observability:** Preserve existing Langfuse observations and usage accounting while adding node-level visibility where useful.

## Suggested implementation sequence for later approval

1. Capture baseline transition tests and representative experiment results.
2. Extract preparation, one model turn, tool processing, text-answer review, and finalization into callable boundaries without changing their behavior.
3. Connect those boundaries with a custom graph and explicit routing decisions.
4. Compare the graph against the existing runner using the same inputs and mocked model/tool responses; then compare real evaluation results.
5. Only after parity, decide whether checkpointing, smaller nodes, human review, or parallel work justifies additional complexity.

Acceptance should cover citation validity, verification failures, name correction, tool errors, multiple calls in one reply, all budget exits, conversation handoff, output fields, and usage reporting. Real-model comparisons should also assess answer quality, latency, and cost; exact textual equality is not sufficient or always realistic.

**Recommended first milestone:** a graph that makes v2.16's decisions visible while preserving existing behavior. Multi-agent delegation, new reasoning strategies, parallel tool execution, and durable recovery remain separate follow-up decisions.


## Validation record

Validated on 2026-11-25 against the actual runner and its submission, tool-submission, coverage, state, model, and answering helpers. The catalog remains the version signature; executable branch order comes from the code.

Existing tests executed from the repository root:

| Command | Result |
|---|---|
| `python -m unittest discover -s tests -p 'test_current_contract.py'` | 11 passed |
| `python -m unittest discover -s tests -p 'test_agent.py'` | 45 passed |

The contract suite exercises all three budget exits, optional premise early resolution, malformed verification, provider failure behavior, and instruction identity. The agent suite covers tool parsing, citation handling, submission constraints, evidence ordering, compaction, and other helper behavior.

Corrections from validation: conditional submission verification, post-verification rewriting, internal finalization inside `_forced_answer`, feedback placement before budget exits, shared nudge limits, and tool-loop continuation semantics.

This is source-level validation supported by existing tests. No LangGraph implementation exists to test for parity, no live model experiment was run, and these tests do not establish exhaustive branch coverage. The proposed node boundaries remain design choices. Future parity tests should specifically cover empty-ID submission, rewritten answers, rejected submissions followed by additional calls, and failure propagation.


## Context-window assessment and required design addition

Measured on 2026-11-25. The earlier proposal preserved compaction but did not establish that prompts fit the local model. Context budgeting must be a separate acceptance requirement; adopting a graph does not solve it automatically.

### Corpus size

Counts use the official `Qwen/Qwen3.6-35B-A3B` tokenizer, revision `345d467b117d1fd5eda9b879a5988de9ae5f47a7`, with special tokens disabled. Text stays local; only the tokenizer was downloaded. These are exact counts for the described extraction and tokenizer, not verified Ollama chat-template counts.

| Book | EPUB reading-order text tokens | Repository extraction source tokens |
|---|---:|---:|
| The Girl with the Dragon Tattoo | 215,499 | 211,483 |
| The Girl Who Played with Fire | 236,329 | 239,999 |
| The Girl Who Kicked the Hornet's Nest | 271,820 | 275,855 |
| **Total** | **723,648** | **727,337** |

Reading-order text uses EPUB spine documents, BeautifulSoup text extraction, normalized whitespace, and blank lines between documents; it includes front/back matter present in the spine. Repository-source counts use `_extract` with a very large split limit and blank lines between extracted paragraphs, before chunk merging, metadata, or overlap. Paragraph separators and differing extraction rules explain why these counts differ. Neither total measures duplicated text across retrieval calls or actual indexed payload size.

Tokenizer source: [official tokenizer at the measured revision](https://huggingface.co/Qwen/Qwen3.6-35B-A3B/blob/345d467b117d1fd5eda9b879a5988de9ae5f47a7/tokenizer.json). Measurement metadata is in [the adjacent JSON file](langgraph-context-measurements.json).

### Actual configured budget

The v2.16 agent uses `qwen3.6:35b`, with `context_length=16384`, `num_predict=1600`, and thinking disabled. This is distinct from the `qwen3:8b` generation model used elsewhere. The whole corpus is approximately 44.2 configured context windows, so retrieval must supply only a small relevant subset per call.

A conservative planning envelope is:

- 16,384 total tokens.
- Reserve 1,600 for output and an initial 1,024-token safety margin.
- This leaves 13,760 for the complete input, including chat formatting and tools.
- The system prompt alone measures 1,460 tokens; serialized tool-schema JSON measures 1,713. Together these consume about 3,173 tokens before question, history, evidence, or actual provider template overhead.
- Approximately 10,587 tokens remain under that provisional allocation before accounting for those other inputs. This is not an evidence allowance or a measured final chat-template budget.

The margin is a proposed starting point, not a validated optimum. Measure the actual deployed tokenizer/template and compare provider prompt-token usage before fixing thresholds. A model's advertised maximum context is not the configured request window.

### Current limitations found in code

- `_compact` triggers above 22,000 **content characters**, not tokens. It excludes tool schemas and structured tool-call arguments from its size calculation.
- It replaces older tool messages but preserves the latest six regardless of their size. `_clip` permits about 9,000 characters per tool result: six recent results alone can approach 54,000 characters, before other prompt content.
- It does not enforce a final size bound, and precheck messages added as user messages are not compacted by this mechanism.
- Compaction retains only up to eight IDs matching its specific JSON pattern per old result. Other IDs or decisive supporting/contradicting text can disappear from the model-visible conversation, although evidence remains in application state.
- Main tool-selection calls compact history; verifier and synthesis calls build separate prompts and have no equivalent general token-budget guard.
- The final handoff compacts history and then appends its instruction. It disallows model-selected tools, so an ID-only reminder cannot recover an omitted decisive passage at that stage.

### Addition to the proposed architecture

Separate **full evidence storage** from **the bounded context shown to the model**. Full passages and provenance can remain in application state or referenced storage; they should not all be serialized into every model request or checkpoint unnecessarily.

Introduce a shared context-preparation boundary immediately before every model call: tool selection, verification, synthesis, and conversation handoff. It should:

1. Count the complete rendered input with the deployed model's tokenizer/template, including schemas and call arguments.
2. Reserve output space and a safety margin.
3. Preserve the original question, unresolved claims, selected supporting and contradicting passages, citation IDs, and valid tool-call/result relationships.
4. Deduplicate repeated evidence and reduce low-priority older content until the request fits. Bound individual and aggregate tool-result payloads by tokens.
5. Fail explicitly or choose a documented smaller evidence set if protected content cannot fit; do not rely on silent truncation.
6. Record token counts before/after selection, removed passage IDs, and provider-reported prompt usage for evaluation.

For a small local model, prefer a compact task-specific evidence set over merely filling the available window. Start with deterministic evidence selection and existing retrieval provenance; an additional summarizer agent is not required. Any generated summary must retain links to original passages and must not become the sole basis for citations.

**Migration boundary:** tokenize and measure first without changing requests. Enforcing new selection or inserting evidence into the v2.16 final handoff changes model-visible behavior and potentially the protected handoff fingerprint. Evaluate that as a separately identified pipeline change, after establishing orchestration parity; do not silently include it in a refactor labeled behavior-preserving.

Required future checks include six large recent tool results, long prechecks, repeated passages, large verification inputs, and budget handoff where decisive contradictory evidence is old. Assert prompt fit and evidence preservation, then measure answer quality on real questions. No live generation or runtime truncation test was performed for this assessment.
