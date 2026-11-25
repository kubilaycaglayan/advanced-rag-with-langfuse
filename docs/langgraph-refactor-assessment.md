# LangGraph adoption assessment

Date: 2026-11-25

Status: Research only; no implementation or experiments performed. Dependency compatibility remains unverified.

## Recommendation

LangGraph is a feasible fit for this repository. Adopt it through a staged migration of the agent orchestration layer, keeping the existing retrieval tools, provider adapters, and answer contracts. A wholesale rewrite would add unnecessary risk.

Complete the transition inventory and parity baseline first, then evaluate a small custom LangGraph implementation behind the existing `run_agent` interface. Keep sequential execution and existing model/tool behavior for the first comparison. Add persistence only after parity is established. If clearer code is the sole objective, compare the prototype against an explicit Python state machine before committing to the framework.

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

## Pre-work before refactoring

1. **Define the objective and acceptance criteria.** Decide whether the first milestone is clearer orchestration, resumability, human review, or parallel execution. Start with clearer orchestration and behavioral parity.
2. **Document the actual transition rules.** Include both submission paths, rejected answers, text-form tool calls, tool failures, all budget exits, and final-answer synthesis. Preserve current behavior initially, including unusual branch precedence.
3. **Establish a baseline.** Use the existing contract tests plus representative questions covering direct facts, sequence questions, name correction, false premises, insufficient evidence, and rejected submissions. Record answer support, citation validity, tool calls, model usage, and latency.
4. **Define state and runtime boundaries.** Put messages, pending tool calls, evidence order, counters, and routing decisions in explicit state. Keep callbacks, clients, and tracing handles outside persisted state. Test serialization round trips if checkpoints are in scope.
5. **Specify failure behavior.** Classify recoverable tool errors, provider failures, verification failures, timeouts, and cancellation. Preserve the existing fail-closed verification contract.
6. **Plan versioning and integration.** Cover pipeline identity, cache separation, experiment manifests, Langfuse traces, status events, and output fields. The current UI adapter emits answer words after generation; graph streaming should not silently change that interface.
7. **Validate dependencies in isolation.** Resolve and pin a candidate LangGraph version against the Python 3.12 image and current requirements. Dependency compatibility remains unverified.

For persistence, additionally decide checkpoint ownership, storage backend, retention, concurrent execution rules, and how old runs behave after graph updates.

## Alternatives

| Option | Best reason to choose it | Tradeoff |
|---|---|---|
| Explicit Python state machine | The main goal is readable transitions and better tests. | Lowest dependency overhead, but recovery and graph tooling remain your responsibility. |
| Pydantic Graph | Typed Python graph definitions and explicit state contracts are preferred. | Worth comparing with LangGraph; validate its execution and persistence model against project needs. |
| Temporal | The primary problem is durable background jobs, retries, and recovery across services. | A larger operational commitment; better considered at the job orchestration layer. |

Pydantic provides a dedicated graph library. Temporal provides workflows, activities, and workers for durable orchestration. See [Pydantic Graph documentation](https://ai.pydantic.dev/graph/) and [Temporal Python documentation](https://docs.temporal.io/develop/python).

Temporal is particularly relevant to [the experiment queue](../app/experiments/queue.py), which currently uses an in-process queue and daemon worker with persisted job records. That is a different concern from the agent's reasoning loop: adding LangGraph does not by itself replace job scheduling or worker management.
