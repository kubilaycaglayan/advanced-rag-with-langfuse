# v2.17 Step 5 — LangGraph execution path

Completed 2026-11-26. Starting revision: `b915f91`, after Step 4. Scope: [roadmap Step 5](../../langgraph-implementation-roadmap.md) only. No Step 6 graph/node tracing integration or application routing changes were made. The catalog still supports only v2.16; v2.17 registration remains Step 7. No live model generation, baseline generation, experiment or deployment was performed.

## Implementation

The existing target entry point, `app.agent.execution.run_agent`, now invokes the custom graph in [graph.py](../../../app/agent/graph.py) instead of driving the boundaries with a Python routing loop. Its arguments and final result shape are unchanged. The released `app.agent.runner.run_agent` and public answering integration remain untouched, preserving the v2.16 release path while the candidate remains unregistered.

The compiled graph has seven work nodes: preparation, turn/budget decision, model selection, sequential reply tools, text review, budget drafting and final preparation. Conditional edges use the explicit route set by each extracted boundary. Continuation is an edge to the next budget decision, rather than an extra model call or feedback node.

The graph passes the existing `ExecutionState` in a single state channel. Nodes return that run object after executing their boundary. Every transition chooses one successor, so there is no concurrent evidence/message merge. The ordered in-memory evidence store, conversation dictionaries and pending tool calls remain intact; LangGraph does not convert the conversation to LangChain message objects or inject passages. `AgentRuntime` is supplied through the framework runtime context, keeping callbacks, tool schemas and the observation handle out of state.

The compiled topology is cached, but invocation state and runtime context are supplied per run. No checkpoint, persistent store, prebuilt agent, message reducer, node retry policy, parallel tool node or provider fallback is introduced. Model selection, verification, synthesis and budget drafting still call the existing adapters with their existing purposes and input construction.

The extracted node function ASTs are unchanged from Step 4. In particular, the tool node still processes an entire reply sequentially. Verification rejection and repeated-answer rejection retain their `continue` behavior, allowing later calls in the same reply and bypassing that call's ordinary budget check. An accepted submission stops the remaining calls immediately. Tool-level rejection still follows the ordinary budget check. Errors raised by the provider or graph propagate; existing recoverable tool errors remain observations.

The target root observation now surrounds graph invocation, including preparation. Existing observation names and generation purposes are retained. Adding and verifying Langfuse graph/node parentage, timing and context measurements is still Step 6; this step does not claim live trace acceptance.

## Application budgets and framework limit

For T allowed model-selection turns, the longest normal path is:

- One preparation node.
- T cycles of decision, model selection, and tools or text review: three nodes per turn.
- One final turn-budget decision.
- One budget draft and one final preparation.

That is `3*T + 4` work nodes. Invocation sets `recursion_limit = 3*T + 5`, allowing an additional framework halt step. The application chooses the timeout/turn/tool handoff; framework recursion exhaustion does not substitute for that behavior. Multiple calls in a single reply add no graph transitions because the tool node handles the whole reply.

Tests execute the complete longest path at 0, 1, 10 and 50 turns, observe every node and the expected model calls, and verify the handoff completes with one final preparation. A separate deliberately undersized limit raises `GraphRecursionError` without triggering an answer fallback. Another test processes 26 submissions with an application tool limit of one, preserving the rejection-continuation exception inside one tool node.

## Diagram and documentation

[The implemented graph reference](../../langgraph-execution-graph.md) is generated from `build_graph().get_graph()`. It shows the actual nodes/edges, a visible **v2.17 candidate — v2.16 released baseline** signature derived from the catalog default, and the execution-limit derivation. Tests verify it matches the compiled graph. The original proposal is marked as historical and links to this implemented reference.

Generate with `python -m app.agent.graph_reference`; check with `python -m app.agent.graph_reference --check`. The settings reference was also regenerated to remove its obsolete claim that the graph was not implemented; its released values are unchanged.

Graph construction and runtime context follow the [official Graph API documentation](https://docs.langchain.com/oss/python/langgraph/graph-api) and [runtime reference](https://reference.langchain.com/python/langgraph/runtime). Verification uses the already pinned LangGraph 1.2.24 in the isolated Step 2 Python 3.12 app image.

## Verification

| Check | Result |
|---|---|
| Existing extracted-target tests through the real graph | 23 passed, including the same 16 captured execution contracts and four complete differential transcript scenarios against v2.16 |
| New graph routing, limit, topology and context checks | 9 passed |
| Final full Python suite | **231 passed**, no failures or errors |
| Generated graph and settings references | Both `--check` commands passed |
| Extracted node implementations | Function ASTs unchanged from Step 4 |
| Target and legacy instruction fingerprints | Both unchanged from Step 4 |
| Released runner, catalog/checksums, protected handoff, answering integration, adapters and final-answer helpers | Byte-for-byte unchanged from Step 4 |

Evidence: [graph contracts](graph-contracts.log), [routing checks](routing-tests.log), [full suite](full-tests.log), and [verification audit](verification.json). The tests exercise real graph scheduling with mocked model/retrieval boundaries; they are not live quality or latency measurements. Live Langfuse inspection and acceptance questions remain later steps.

All checks passed without implementation regressions. No unresolved Step 5 blocker remains.

## Reproduction and stopping point

Use the Step 2 isolated verification image and temporary Compose override described in [its record](../langgraph-v2.17-step2/README.md). From the repository root:

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

For graph-specific checks, replace the command after `app` with `python -m unittest discover -s tests -p test_agent_graph.py -v`. For the captured target contracts, use `python -m unittest discover -s tests -p test_agent_extraction.py -v`. The live app container was neither restarted nor replaced.

Step 5 completion gate is satisfied. Stop before Step 6.
