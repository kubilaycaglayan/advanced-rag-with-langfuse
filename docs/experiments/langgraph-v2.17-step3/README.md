# v2.17 Step 3 — centralized settings and generated reference

Completed 2026-11-26, starting from `a72a66e` (Step 2 complete). Scope: [roadmap Step 3](../../langgraph-implementation-roadmap.md) only. No graph state or node extraction, early-stop removal, candidate catalog registration, live generation or deployment was performed.

## Delivered

[settings_definitions.py](../../../app/settings_definitions.py) now owns typed `AgentSettings` and `RuntimeLimits`. Each field has a default, units, explanation, source reference, and applicable type/range/choice validation. `app.agent.state.AgentSettings` remains a compatible import of the same class. Resolution consumes shared validation while retaining the existing override names and provider restrictions. There is no new runtime-limit override surface.

Released agent values still come from the unchanged catalog. The v2.16 catalog omits `reasoning_effort`; its historical implicit value is now an explicit version-specific resolver fallback, so changing current defaults cannot replace it. Tests simulate moving defaults and prove that catalog values and this historical omission still win. Retrieval/model configuration remains under the existing typed pipeline config and released catalog; it is not replaced by current agent defaults.

Nudge allowance, answering-agent HTTP timeouts, recent-tool retention, compaction trigger/ID retention and tool-result clipping now consume the shared runtime definitions. Character counts and existing serialization/compaction behavior are preserved. Display-only token estimates in documentation do not affect model input.

[The settings reference](../../langgraph-pipeline-settings.md) is generated in full by `python -m app.settings_reference`. It distinguishes current defaults, released values, and the effective resolved example, identifies the legacy omitted setting, and explicitly labels embedded limits as not catalog-pinned. `--settings-json` generates a provider/override example; `--output` can save that separately. `--check` detects stale documentation. Table values, descriptions, units and source links come from runtime metadata rather than separately maintained Markdown definitions.

Effective embedded limits are now recorded as `runtime_settings` in the experiment pipeline manifest and exact-answer cache identity. Both interactive and experiment answering already use this common identity boundary. A change to these values changes the answer-cache key; old entries without the new dimension cannot be adopted by the legacy case-insensitive lookup. This conservatively makes the answer cache cold for the new identity without deleting any entries or altering historical manifests. Pipeline release IDs/checksums and intermediate retrieval-cache behavior remain unchanged.

## Verification

- The initial centralization passed all 91 existing agent, current-contract, pipeline, settings and execution-contract tests. [Log](centralization-tests.log).
- Added 11 settings tests covering metadata completeness, typed validation, released values versus moving defaults, existing overrides, exact provider request parity, character boundaries, ID/retention limits, runtime-limit consumption, HTTP timeouts, cache separation, experiment provenance, generated documentation and protected identities. [Targeted log](settings-tests.log).
- Final full Python suite passed **199/199**, no failures or errors, in the isolated Python 3.12 LangGraph verification image from Step 2. [Full log](full-tests.log). The final suite includes the additional explicit runtime-value assertions added after the targeted run.
- Resolved agent settings, pipeline config and pipeline IDs for Ollama and OpenAI match the frozen Step 1 inputs. The generated reference matches its generator byte for byte.
- `pipelines.md`, `pipelines.sha256` and the protected conversation-handoff file match the Step 2 revision byte for byte. The instruction fingerprint still matches the released catalog. No v2.16 release checksum was rewritten.

[verification.json](verification.json) records the implementation revision, effective provider settings, checks and log hashes. There is no unresolved Step 3 blocker.

## Request-contract provenance

The six entries in [v2_16_request_contract.json](../../../tests/fixtures/v2_16_request_contract.json) were captured by [capture_agent_request_contract.py](../../../scripts/capture_agent_request_contract.py) against an isolated worktree at **`a72a66e`**, before centralization. Requests were intercepted with mocked `requests.post`; no provider was contacted. The temporary worktree was removed after capture.

The fixture covers Ollama, OpenAI Chat Completions and OpenAI Responses, each with and without tools. It uses a deterministic synthetic conversation large enough to exercise compaction, and records the canonical outgoing JSON hash/byte length, URL, HTTP timeout pair and number of compacted tool results. All six outgoing payloads and timeout pairs match after centralization. Separate tests exercise clipping boundaries and show that changing only HTTP limits changes timeouts without changing payload bytes. These are mocked request contracts, not new quality/latency baselines.

## Reproduction

Use the Step 2 isolated image and temporary Compose override described in [its verification record](../langgraph-v2.17-step2/README.md). From the repository root:

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

Replace the command after `app` with `python -m app.settings_reference --check` to verify generated documentation, or `python -m app.settings_reference` to regenerate it. These checks require the repository corpus files available through the existing Compose volume configuration; they do not load live models. The live app container was untouched.

Step 3 completion gate is satisfied. Stop before Step 4.
