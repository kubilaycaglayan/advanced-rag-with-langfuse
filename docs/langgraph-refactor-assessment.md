# LangGraph adoption assessment

Finalized: 2026-11-26

Status: Finalized adoption assessment and agreed acceptance criteria; implementation has not started and dependency compatibility remains unverified.

## Recommendation

LangGraph is a feasible fit for this repository. Adopt it through a staged migration of the agent orchestration layer, keeping the existing retrieval tools, provider adapters, and answer contracts. A wholesale rewrite would add unnecessary risk.

The proposed v2.17 scope is agent orchestration with the existing local and OpenAI adapters, sequential tools, existing answer contracts, and preserved Langfuse instrumentation; this review defines scope and acceptance before an implementation plan is requested.

## Current architecture and fit

The current pipeline already behaves like a graph, but its transitions are encoded in a Python loop.

In [runner.py](../app/agent/runner.py), execution branches between prechecks, model calls, tool execution, coverage checks, submission verification, corrective nudges, and forced answers. LangGraph would make these transitions explicit and independently inspectable.

The repository has useful migration boundaries:

- [AgentState](../app/agent/state.py) already centralizes much of the execution state.
- Tools, prechecks, submission logic, and model adapters are separate modules.
- [execute_question](../app/answering/execution.py) provides a stable boundary between the agent and its consumers.
- Existing tests protect citations, verification, instruction identity, and budget-triggered conversation handoff.

LangGraph checkpointing offers a path to resuming interrupted work, which is separate from representing the pipeline as a graph. Its persistence model distinguishes execution checkpoints from longer-lived shared memory. See the [official persistence documentation](https://docs.langchain.com/oss/python/langgraph/persistence).

Expected benefits are clearer control flow, easier branch testing, better execution inspection, and optional resumability. Better answer quality or lower latency would need to be demonstrated; changing orchestration alone does not establish either.

## Recommended migration scope

Use a custom graph with coarse nodes initially:

| Responsibility | Initial treatment |
|---|---|
| Normalization and prechecks | Preserve existing order and helper functions |
| Model turn | Call the existing provider adapter |
| Tool execution | Preserve sequential execution and existing error handling |
| Answer acceptance | Preserve nudges, coverage checks, and verification |
| Budget exhaustion | Preserve v2.16 conversation handoff |
| Final result | Preserve the current output contract |

Do not start by replacing this with a generic prebuilt agent. The loop has substantial domain-specific behavior that would still need to be reintroduced.

Wrapping the entire current runner in one graph node would establish integration but deliver little orchestration value.

## Main risks

| Risk | Why it matters here | Mitigation |
|---|---|---|
| Behavior drift | The ordering of nudges, verification, tool limits, and early returns affects answers. | Capture representative execution traces and compare transitions before changing behavior. |
| Incomplete checkpoint state | Conversation messages currently live outside `AgentState`; pending calls and loop position are also local. | Define a complete resumable state schema before enabling persistence. |
| Mutation and ordering | Evidence, focus, messages, counters, and traces are mutated in place. Evidence order affects citations. | Use explicit state updates; keep tools sequential initially. Define merge rules before any parallelism. |
| Repeated work on retry | Model calls, usage accounting, trace writes, and other effects could repeat. | Define retry boundaries and idempotency; distinguish attempts from completed steps. |
| Budget semantics | `started` uses `perf_counter()`, which is unsuitable as a persisted cross-process deadline. HTTP calls also have their own timeouts. | Specify whether downtime counts toward the budget and propagate remaining time into calls. |
| Identity and cache contamination | Pipeline fingerprints and answer-cache identity protect reproducibility. | Give the graph implementation a distinct identity and isolate comparison runs from cached answers. |
| Operational scope creep | Checkpointing introduces storage, retention, concurrency, and deployment compatibility decisions. | Separate graph adoption from durable execution rollout. |

LangGraph warns that affected nodes can restart from the beginning after retries or interrupts. Node boundaries therefore need careful design; checkpointing is not an exactly-once guarantee for external effects. See the [official Graph API documentation](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/graph-api.mdx).

The catalog's listed flow is not the exact execution order. For example, the runner performs sequence and moment prechecks before the premise probe, whereas [pipelines.md](../pipelines.md) lists the premise probe earlier. Establish the intended semantics from code and tests before turning that list into graph edges.

## Agreed acceptance criteria

- Select 10 fixed questions spanning all four Millennium datasets: QA.csv, set3, right-set-3, and Additional Questions.
- Quality has priority over latency: mean correctness may decrease by no more than 0.10 absolute score points against the selected questions' recorded baseline scores.
- Mean latency may increase by at most 10%; investigate and reduce increases above this tolerance, and reduce latency wherever possible without sacrificing quality.
- A regressed question may be rerun up to twice; use its best attempt for acceptance and retain all attempts for inspection.
- Reuse recorded experiments from [best-performing versions](best-performing-versions.md); do not generate a new baseline.
- For each provider, use the best recorded v2.16 result; if absent, use the latest listed pipeline version for that provider and the best correctness result within that version.
- Retrieve the selected item IDs, recorded scores, evaluator identity, configuration, and latency before calculating sample acceptance; whole-dataset means cannot substitute for item-level values.

## Migration requirements

| Area | Requirement |
|---|---|
| Version | Target v2.17; the current catalog remains v2.16 during review. |
| Providers | Support the existing Ollama and OpenAI adapters, including their distinct error behavior. |
| Transitions | Document both submission paths, rejected answers, text-form tool calls, tool failures, budget exits, and final synthesis from the executable pipeline. |
| State | Represent messages, pending calls, evidence order, counters, and routing decisions explicitly; keep clients, callbacks, and tracing handles outside persisted state. |
| Failures | Preserve existing tool-error recovery, provider failures, verification, and budget behavior. |
| Integration | Preserve answer contracts, status events, experiment metadata, pipeline identity, and cache separation. |
| Observability | Preserve traces, metrics, usage, and observations; Langfuse hierarchy and timing must reflect actual nodes, tools, errors, verification, synthesis, and stop reasons, including currently unmeasured paths. |
| Dependencies | Validate and pin LangGraph against the Python 3.12 image and current requirements; compatibility remains unverified. |

This assessment defines migration scope and acceptance; the step-by-step implementation plan will be written after the document review is complete.

## Alternatives

| Option | Best reason to choose it | Tradeoff |
|---|---|---|
| Explicit Python state machine | The main goal is readable transitions and better tests. | Lowest dependency overhead, but recovery and graph tooling remain your responsibility. |
| Pydantic Graph | Typed Python graph definitions and explicit state contracts are preferred. | Worth comparing with LangGraph; validate its execution and persistence model against project needs. |
| Temporal | The primary problem is durable background jobs, retries, and recovery across services. | A larger operational commitment; better considered at the job orchestration layer. |

Pydantic provides a dedicated graph library. Temporal provides workflows, activities, and workers for durable orchestration. See [Pydantic Graph documentation](https://ai.pydantic.dev/graph/) and [Temporal Python documentation](https://docs.temporal.io/develop/python).

Temporal is particularly relevant to [the experiment queue](../app/experiments/queue.py), which currently uses an in-process queue and daemon worker with persisted job records. That is a different concern from the agent's reasoning loop: adding LangGraph does not by itself replace job scheduling or worker management.

## Recorded v2.16 baseline references

Source: [best-performing versions](best-performing-versions.md); these are recorded whole-dataset means, not the mean of the still-unselected 10-question sample.

| Millennium dataset | Agent model | Correctness | Latency (s) | Recorded experiment ID |
|---|---|---:|---:|---|
| QA.csv | gpt-6-luna | 0.90 | 22.40 | `4dc5a0a71e072c74` |
| set3 | gpt-6-luna | 0.90 | 29.97 | `37ebe85de2796617` |
| right-set-3 | gpt-6-luna | 0.88 | 27.47 | `c2cde1e05faa6f40` |
| Additional Questions | gpt-6-luna | 1.00 | 28.71 | `4411d1a1728f4990` |

### Local-provider fallback references

The source lists no local v2.16 result for these four datasets; applying the agreed latest-listed-version fallback gives:

| Millennium dataset | Agent model | Pipeline | Correctness | Latency (s) | Recorded experiment ID |
|---|---|---|---:|---:|---|
| QA.csv | qwen3:8b | v2.2 | 0.87 | 30.87 | `4ff5ebd1a66dbfb8` |
| set3 | qwen3.6:35b | v2.13 | 0.72 | 47.47 | `163cfd81374ea8b8` |
| right-set-3 | qwen3.6:35b | v2.13 | 0.91 | 47.71 | `99b35b171b966af9` |
| Additional Questions | qwen3.6:35b | v2.12 | 0.99 | 54.50 | `b2e7fb1676745447` |

The QA.csv fallback uses a different local model from the current agent; record that difference in comparisons rather than treating it as a model-matched baseline.
