# Current pipeline settings reference

Review reference for v2.17, based on current v2.16; values below are defaults, and resolved run overrides must be checked when comparing experiments.

There is no single runtime globals file: defaults live in [AgentSettings](../app/agent/state.py), released settings in [the catalog](../pipelines.md), and request/compaction limits in the helpers linked below.

| Setting | Current value | Human meaning | Source |
|---|---:|---|---|
| `timeout_seconds` | 900 seconds | Time allowance from run start, checked before each model turn; preparation counts and in-flight calls can exceed it. | [runner](../app/agent/runner.py) |
| `max_turns` | 10 | Maximum model-selection turns; verification and synthesis are separate model calls. | [settings](../app/agent/state.py) |
| `max_tool_calls` | 16 | Ordinary tool-call exit threshold; incremented before dispatch, with rejection branches that can skip checking. | [runner](../app/agent/runner.py) |
| `min_tool_calls` | 4 | Investigation minimum used by nudges and submission checks; speech-hint submission can use one. | [submission tool](../app/agent/tools/submission.py) |
| `context_length` | 16,384 tokens | Local agent request window sent as Ollama `num_ctx`; not sent as an OpenAI context override. | [adapter](../app/models/agent.py) |
| `num_predict` | 1,600 tokens | Maximum requested model output; OpenAI maps it to its output-limit parameter. | [adapter](../app/models/agent.py) |
| Nudge allowance | 2 | Shared count for minimum-investigation and no-tool nudges. | [runner](../app/agent/runner.py) |
| Recent tool results kept | 6 | Latest tool messages remain intact during ordinary compaction. | [compaction](../app/context/conversation.py) |
| Compaction trigger | Roughly 5,500 tokens | Approximate content-size trigger, not a guaranteed tokenizer budget. | [compaction](../app/context/conversation.py) |
| Tool-result clipping | Roughly 2,250 tokens | Approximate maximum displayed tool payload, not a tokenizer count. | [protocol](../app/agent/protocol.py) |
| Ollama HTTP timeouts | 10 / 900 seconds | Connection / read timeout for a model request. | [adapter](../app/models/agent.py) |
| OpenAI HTTP timeouts | 10 / 180 or 300 seconds | Connection / read timeout: Chat Completions or Responses respectively. | [adapter](../app/models/agent.py) |

Approximate token figures use four source characters per token only to explain existing limits; actual token counts vary with text and tokenizer.

The requested consolidated runtime constants file belongs to the migration scope; this reference documents current values without changing application code during review.

## Agreed single source for code and readers

Use a Python module with typed settings, units, brief explanations, and source references as the canonical definition; runtime code consumes these definitions and generates the Markdown reference from their metadata.

| Concern | Required treatment |
|---|---|
| Released values | Keep version-specific values in the released catalog; the shared definition describes settings and validates resolved values, rather than replacing released values with current defaults. |
| Runtime overrides | Show the distinction between defaults, released values, and effective run values; the existing resolver already applies explicit overrides. |
| Embedded limits | Bring nudge, HTTP timeout, compaction, and clipping definitions into the shared source while preserving their current values and behavior. |
| Units | Preserve the actual runtime units for compaction and clipping; token estimates remain display-only approximations, so centralization does not change truncation behavior. |
| Human descriptions | Store the brief explanation and code reference alongside each definition; generate this reference from that metadata. |
| Reproducibility | Record effective settings in run identity and manifests as applicable; preserve released catalog and instruction/handoff protection. |

The current [resolver](../app/pipelines/resolver.py) loads released values from [the catalog](../pipelines.md), whose [validator](../app/pipelines/catalog.py) enforces release fingerprints; one current global value must not silently replace versioned settings.

Centralization must preserve current values, runtime overrides, and versioned behavior; implementation is part of the v2.17 migration.
