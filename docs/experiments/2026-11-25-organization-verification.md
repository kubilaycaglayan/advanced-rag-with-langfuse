# Code organization verification

Implementation is in progress. This report records evidence as it becomes available.

Baseline backend: 7febbf7. Baseline UI: 33cb103b31b0ce12bf6e9488b19aa406a0a3f5a6.
The initial worktree was clean. Python baseline: 172 tests passed. Express baseline:
14 tests passed. Unchanged UI baseline: 22 tests passed. The production static UI
build passed. Contract identities, index inputs, entity-card checksum, and log
hashes are recorded in `2026-11-25-organization-baseline.json`. Existing passage
and scene collections and entity cards passed index validation without building.

The pinned sample is recorded in `2026-11-25-organization-comparison.json`.
It includes the known difficult shooting question, a false murder premise,
scene details, a discovery sequence, broad character coverage, and connections.
Each dataset retains its own version and run membership.

Verification uses a separate SQLite database containing copies of existing index
manifest rows only. Existing entity cards are read from the corpus data directory.
The verification runner replaces index preparation with validation of existing
passage, scene, and entity indexes: it cannot call an index builder. Answer and
intermediate caches are bypassed. Artifacts are kept under
`data/millennium/comparisons/2026-11-25-organization/`.

User decisions: paid comparisons approved; frequent small commits; never rebuild
indexes. Skip any step requiring a rebuild and report it for acknowledgment,
without blocking unrelated refactoring. No deployment or UI changes are authorized.

All eight baseline runs finished: 22 answers and two item failures. Both providers
fail the detailed kitchen-bench question with the pre-existing error
`TypeError: _moment_scene_hits() takes 6 positional arguments but 7 were given`.
This unrelated bug is preserved and will be compared after refactoring. No
evaluator or telemetry failures occurred. Baseline package startup passed on
port 18019: health 200, invalid empty question 422, clean shutdown.
