# v2.17 Step 2 — dependency compatibility and execution contracts

Completed 2026-11-26. Scope: [roadmap Step 2](../../langgraph-implementation-roadmap.md) only. Starting revision: `738ad5523735a83e553a90bea1e3bb331969bf84`, after the frozen Step 1 inputs. No agent execution, settings, catalog, handoff, provider request, or deployment changes were made. Step 3 has not started.

## Dependency result

Pinned `langgraph==1.2.24` in `app/requirements.txt`. Package requirements and the StateGraph interface were checked against [PyPI metadata](https://pypi.org/project/langgraph/1.2.24/) and the [official Graph API documentation](https://docs.langchain.com/oss/python/langgraph/graph-api). Installation was then verified against the repository's complete requirements in a separate app image, rather than relying on declared compatibility alone.

The isolated image `millenium-langgraph-step2` derives from the existing app image, whose immutable ID is in [base-image.txt](base-image.txt). Its build installed `app/requirements.txt` and ran `pip check` successfully. The source worktree was mounted for the probes and tests. The live app was neither rebuilt nor restarted; its container still uses the recorded base image. No live models were loaded or called.

The [probe](../../../scripts/langgraph_dependency_probe.py) imported the application, runner, provider adapter, resolver and LangGraph, then compiled and invoked a minimal START → increment → END graph, yielding `{"count": 1}`. Python is 3.12.16. Resolved versions include LangGraph 1.2.24, langchain-core 1.8.5, checkpoint 4.3.2, prebuilt 1.1.3, SDK 0.4.14, Pydantic 2.14.3, Langfuse 4.17.0 and FastAPI 0.120.0. No Dockerfile change was needed: it already uses Python 3.12 and installs the requirements file.

Evidence: [build log](dependency-build.log), [pip resolution report](pip-install-report.json), [full installed versions](resolved-requirements.txt), [probe results](dependency-probe.json), and [verification summary](verification.json). The direct LangGraph dependency is pinned; the resolved transitive environment is captured here, not imposed as a new application-wide lockfile.

The first probe attempt installed dependencies and passed `pip check`, but failed to import `app` because it was launched as a script from `scripts/`. [The initial log](initial-probe-path-error.log) preserves this harness error. Running `python -m scripts.langgraph_dependency_probe` from the repository root resolved it. The final compatibility evidence comes from the successful isolated-image run.

## Existing and new contracts

Before changing the dependency or execution tests, the existing agent, current-contract, pipeline, and answer-settings suites passed **75/75**, with no failures or errors. See [before-tests.log](before-tests.log).

Added [test_agent_execution_contract.py](../../../tests/test_agent_execution_contract.py) with **16 test methods**, including parameterized budget/provider cases. The harness executes the actual runner, submission validation, verification prompt builder, handoff, synthesis and final packaging. It supplies finite mocked model replies and retrieval results; unexpected HTTP requests fail. Telemetry is mocked, so this captures execution behavior without claiming live Langfuse validation.

| Contract | Assertions captured |
|---|---|
| Multiple calls in one reply | Dispatch is sequential; counters increment before dispatch; JSON-string arguments normalize; evidence is deduplicated in insertion order; accepted submission stops remaining calls. |
| Message/tool IDs | Missing IDs become `agent_T_I`; supplied IDs survive; assistant request precedes ordered, linked tool messages; the next model turn sees those exact results. |
| Text-form calls | Fenced JSON is parsed, dispatched, counted, and represented as a tool request while preserving the assistant content. |
| Rejected submissions | Failed verification and repeated central answers can skip that iteration's budget check and continue within the same reply; tool-level minimum-investigation rejection follows the ordinary budget exit. Rejection feedback precedes later results in the handoff. |
| Empty-ID submission | Existing evidence permits acceptance; verification is skipped; absent citations may trigger final synthesis; submitted payload remains distinct from synthesized output. |
| All budget exits | Deterministic clock covers timeout, tool and turn limits; handoff has no model-selected tools, retains the latest conversation results, does not inject stored passage text, emits the budget-specific event, and finalizes once. Current final stop reason remains `budget`. |
| Final rewriting | An accepted and verified sequence draft may be synthesized into a better sequence; the rewritten final answer is not verified again. Synthesis purpose and result IDs are checked. |
| Recoverable tool errors | Error payload, trace, linked tool message and counter survive; later calls continue. |
| Provider failure propagation | Main/forced model failures propagate for both providers without finalization. Verifier exceptions reject locally but propagate for OpenAI. No universal fallback or retry is introduced. |
| Preparation | Prechecks execute in actual runner order; initial scene message precedes connection message even though connection work runs first. |
| Nudges and feedback | Minimum-investigation and no-tool nudges share an allowance of two; name and progress feedback appear before budget handoff. |
| Verification context | Cited evidence precedes ordered, deduplicated premise/focus extras, capped at six. |
| Results | Answer/citation relabeling, raw answer, evidence order, counts, question identity, trace, model, usage field, latency type, stop reason and submitted payload are checked. |

The pre-existing suites continue to cover prompts/tool schemas, protected handoff fingerprint, catalog/override identity, malformed verification, adapter requests, compaction and helper contracts. The harness mocks tracked model calls and therefore does not measure real token usage, latency, quality, or telemetry parentage; later steps own those checks.

The first new-test run exposed an incorrect test expectation for rejected-answer normalization: removing a citation leaves a space before the terminal period (`ada wrote it .`). The assertion was corrected to capture the existing executable behavior; application code was not changed.

Final combined run under the pinned candidate dependency: **91/91 passed**, no failures or errors. See [contract-tests.log](contract-tests.log) for the targeted run and [after-tests.log](after-tests.log) for the combined run. `git diff --check` also passed. No unresolved Step 2 blocker remains.

## Reproduction

Run from the repository root. Build the isolated verification image without altering the live service:

```bash
docker build -t millenium-langgraph-step2 -f - . <<'DOCKERFILE'
FROM millenium-app
COPY app/requirements.txt /tmp/langgraph-requirements.txt
RUN python -m pip install --no-cache-dir --report /tmp/langgraph-pip-report.json -r /tmp/langgraph-requirements.txt && python -m pip check
DOCKERFILE
```

To reproduce the captured environment exactly, use the base image ID and resolved versions recorded above; a future dependency resolution may choose different transitive versions.

Create a temporary Compose override selecting the isolated image:

```yaml
services:
  app:
    image: millenium-langgraph-step2
```

With that saved at `/tmp/millenium-langgraph-step2-compose.yaml`, invoke the probe as a module (replace the command after `app` with the test command below to run verification):

```bash
docker compose -f compose.yaml -f /tmp/millenium-langgraph-step2-compose.yaml run --no-deps --rm -T \
  -v "$PWD:/workspace" \
  -v "$(command -v git):/usr/local/bin/git:ro" \
  -w /workspace \
  -e GIT_CONFIG_COUNT=1 \
  -e GIT_CONFIG_KEY_0=safe.directory \
  -e GIT_CONFIG_VALUE_0=/workspace \
  -e LANGFUSE_TRACING_ENABLED=false \
  app python -m scripts.langgraph_dependency_probe
```

The combined suite command inside that same one-off environment is:

```bash
python -c 'import unittest,sys; suite=unittest.TestSuite(unittest.defaultTestLoader.discover("tests",pattern=p) for p in ("test_agent.py","test_current_contract.py","test_pipelines.py","test_answer_settings.py","test_agent_execution_contract.py")); result=unittest.TextTestRunner(verbosity=2).run(suite); sys.exit(not result.wasSuccessful())'
```

Step 2 gate is satisfied. Stop here: centralizing settings, extracting nodes and wiring the graph remain future work.
