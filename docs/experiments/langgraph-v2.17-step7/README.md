# v2.17 Step 7 — candidate registration and identity

Completed 2026-11-26. Starting revision and rollback checkout: `75d8659` (full revision in verification.json). Implementation: `79d0f46`; additional parity checks: `b557d86`. Scope is roadmap Step 7 only. No live inference, experiments, deployment, or default-version change occurred.

Explicit `resolve('v2.17')` selects the LangGraph backend and TargetAgentSettings for Ollama and OpenAI. The default remains v2.16 with its legacy execution path. Both paths coexist in this checkout with their own instruction manifests. The target pins reasoning effort explicitly and rejects every supplied early-stop override, including false and null; premise evidence probing remains in preparation.

The catalog requires released status and a checksum for every entry. v2.17 therefore registers an immutable definition with that status while its notes and generated graph identify it as a candidate awaiting live acceptance. Registration does not establish acceptance or authorize deployment. Only the v2.17 checksum line was appended; v2.16's definition and checksum are unchanged.

The target manifest covers relocated preparation, selection, tool processing, text review, budget drafting, and final preparation builders. Its fingerprint differs from the legacy source manifest. Direct transcript tests compare actual messages, model-call purposes, tool schemas, answers, citations and stop reasons; existing full-transcript parity checks additionally cover rejected submissions, empty-ID submission, multiple calls and recoverable tool failures. Source fingerprint equality is not used as a substitute for behavioral parity.

Graph run identity includes the distinct catalog checksum, pipeline version/ID, target instruction fingerprint, effective settings/runtime limits and source fingerprint. Tests verify provider resolution, target instruction tamper rejection, answer-cache separation, application dispatch, API and experiment boundaries, override validation and legacy defaults. The graph and settings references were regenerated and their checks pass.

Verification: all **252 tests passed** in the Python 3.12 Step 2 isolated image (`millenium-langgraph-step2`), with telemetry disabled and mocked model/retrieval boundaries. See full-tests.log. The host Python lacks LangGraph/FastAPI, so host-only integration checks were not used as completion evidence. The one-off container used the repository bind mount, Git executable mount and safe-directory variables from AGENTS.md; the live app container was untouched. Reproduce with the command recorded in the Step 6 README, using the same isolated image/Compose override.

verification.json records the unchanged protected source files, legacy instruction identity, handoff hash, candidate identity and rollback starting revision. Same-checkout v2.16 resolution and execution remain supported and tested. To inspect or restore the pre-registration source, create an isolated checkout of the recorded starting revision; no rollback or deployment was performed here.

Step 7 is complete. Step 8 live question validation and Step 9 acceptance/release remain pending.
