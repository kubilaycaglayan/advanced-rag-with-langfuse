# Code organization refactor verification

Date: 2026-11-25. Status: complete.

The Python backend and Express server are organized around the responsibilities
in the [code map](../code-map.md). The agent runner is 287 lines and `main.py` is
a two-line ASGI entry point. The UI submodule is unchanged at
`33cb103b31b0ce12bf6e9488b19aa406a0a3f5a6`. v2.16, its released catalog, protected
instructions, handoff bytes, settings, tool schemas, and index identities remain
unchanged. No index rebuild, deployment, push, publication, or live-container
restart occurred. No step was skipped for reindexing.

## Automated and contract checks

| Check | Result |
| --- | --- |
| Python suite | 172 passed |
| Express suite | 14 passed |
| Unchanged UI suite | 22 passed |
| Production UI build and separate frontend Docker build | Passed |
| Import every application module | 99 imported |
| OpenAPI comparison with original 7febbf7 | Exactly equal |
| Multi-module instruction manifest and tampering checks | Passed; baseline fingerprint retained |
| Protected handoff and budget exits | Passed |
| Existing Millennium and Alienist indexes | Passage, scene, and entity validation passed |
| Cache, rate limit, admission lock, retries, queue, trace upload | Existing focused suites passed |
| Dependency boundaries | Retrieval imports no agent/context/API; context imports no provider client |
| Development startup and proxy | UI 200; proxied invalid trace 400 |
| UI source, submodule pointer, catalog and release pins | Unchanged |

A source comparison checked 85 original agent functions: 84 bodies match after
accounting for public helper renames; only multi-module instruction collection
intentionally differs. Another 35 API/experiment functions have three intentional
differences: shared cache identity construction and use, and relocated fingerprint
resource paths. All 11 judge function bodies match the original. Evidence-state
storage moved to context; generation instructions were not tuned. The original
argument-count diagnostic is retained behind the public scene-search interface.

## Pinned regression sample

The [selection manifest](2026-11-25-organization-comparison.json) records 12 exact
item IDs across four datasets and their historical versions. Both providers ran
the same sample before and after the refactor: 48 question attempts, 44 successful
answers, and four occurrences of the same pre-existing kitchen-bench failure.
There were no new item failures, evaluator failures, or telemetry failures.
Answer and intermediate caches were bypassed. Every dataset/provider pair has
its own labeled run; the manifest retains baseline execution references and the
[per-question report](2026-11-25-organization-results.json) retains both phases'
run URLs, answers, evaluations, latency, tool calls, and usage.

Correctness and citation values below are means over successful answers. The
Additional Questions mean covers two answers in each phase; its third item fails
before answering in both providers.

| Dataset | Provider | Answers per phase | Correctness: before → after | Citation: before → after |
| --- | --- | --- | --- | --- |
| QA.csv | ollama | 3/3 | 0.8167 → 0.8167 | 0.3333 → 0.3333 |
| QA.csv | openai | 3/3 | 0.7833 → 0.7833 | 0.5000 → 0.5000 |
| Additional Questions | ollama | 2/3 | 0.2500 → 0.2500 | 0.7500 → 0.7500 |
| Additional Questions | openai | 2/3 | 0.4917 → 0.5000 | 1.0000 → 1.0000 |
| set3 | ollama | 3/3 | 0.6667 → 0.6667 | 0.8333 → 0.8333 |
| set3 | openai | 3/3 | 0.8250 → 0.8000 | 0.8333 → 0.8333 |
| right-set-3 | ollama | 3/3 | 0.9250 → 0.9250 | 1.0000 → 1.0000 |
| right-set-3 | openai | 3/3 | 0.8111 → 0.8278 | 1.0000 → 0.8333 |

## Every observed score decline

Three OpenAI questions had four lower metric values. Six targeted repeat
executions used the original archived 7febbf7 source and the refactored source,
with the same items, dataset versions, settings, evaluator definitions, indexes,
and bypass policy. No scores or rubrics were rewritten.

Cells below show correctness / citation support. Exact IDs and trace/run links
are in the [investigation evidence](2026-11-25-organization-investigations.json).

| Item | Before | After | Original-code repeat | Refactored repeat |
| --- | --- | --- | --- | --- |
| cf527045 | 0.9750 / 1.0 | 0.9500 / 0.5 | 0.9750 / 0.5 | 0.9625 / 0.5 |
| 63be7c48 | 1.0000 / 1.0 | 0.9500 / 1.0 | 1.0000 / 0.5 | 0.9500 / 1.0 |
| 58f31047 | 0.5000 / 1.0 | 0.5500 / 0.5 | 0.5500 / 0.5 | 0.5000 / 1.0 |

- Gottfried's death: the answers vary in how explicitly they describe the assault
  and official accident account. The citation judge also discounts Harriet's
  confession after acknowledging that it supports the drowning. Citation 0.5
  occurs with the original code as well as the refactor.
- Mikael working for Henrik: the refactored answers omit the exact monthly salary
  while retaining the decisive Wennerström inducement, producing 0.95 rather than
  1.0. This small difference remained in the repeat and is retained in the report.
- Zala's relationship to Salander: the original-code repeat produces the same
  added twin-sister claim and 0.5 citation score as the initial refactored answer;
  the refactored repeat returns the shorter supported answer and citation 1.0.

For all three questions, all four runs sent **identical first-turn message input**
to OpenAI, as demonstrated by recorded hashes and trace reads. OpenAI returned
different tool choices or queries. Combined with unchanged model-visible
contracts, unchanged agent/judge bodies, and the original-code repeats, this
explains the differences as model and judge variability rather than an identified
refactor regression. The initial declines remain visible; aggregate results were
not used to dismiss them. These few repeats cannot establish statistical
quality equivalence across all questions.

Observed timing and usage for the initial sample follow. Each cell is median
successful-answer latency / total tool calls / total agent tokens, over 11
successful answers. These are observations, not a performance benchmark; model
choices, provider caching, and external scheduling vary.

| Provider | Before | After |
| --- | --- | --- |
| ollama | 35.6 s / 52 / 510,619 | 36.0 s / 52 / 510,619 |
| openai | 13.2 s / 78 / 605,147 | 14.3 s / 71 / 520,162 |

## Live compatibility checks

A separate backend and the newly built frontend image served the unchanged UI.
A headless browser asked the father question through the UI's OpenAI/high path,
received status/token/done events and a cited answer, submitted feedback, and
viewed 44 trace observations. The same trace returned 400 without a browser cookie
and 403 with another browser's cookie. The direct Ollama API check returned 200
with an answer and trace ID. These smoke checks verify transport and interaction;
they are not additional quality benchmarks. The unscored Ollama answer contained
unsupported extra detail, retained in its raw artifact rather than corrected here.

The browser emitted React error #418. It also occurs using the original Express
server with the **same built UI assets**, and both servers return identical HTML.
This is a pre-existing UI issue outside the refactor's scope. The UI source and
submodule pointer remain unchanged. Screenshots, responses, and comparison evidence
are preserved with the verification artifacts. Temporary backend, frontend,
Redis, development, and original-source verification servers were stopped.

## Persistence, identity, and limits

Index-manifest ownership moved to `indexing/manifests.py`; SQLite tables, rows,
and schema remain unchanged. Verification used isolated SQLite databases with
copies of existing index records, existing entity-card files, and read-only
index validation in place of experiment index preparation. The UI smoke check
used disposable Redis. Historical experiments, scores, traces, and reports were
not overwritten; only new verification executions/traces and feedback on a new
verification trace were added.

Source fingerprints change with file locations. Derived evaluator IDs also change
because evaluator source bytes include updated imports; managed evaluator
versions, definitions, settings, and all judge function bodies are unchanged.
No protected hash was silently refreshed. Baseline manifests pin the query/judge
model digest and embedding/reranker revisions. OpenAI's model alias is not an
immutable snapshot. The local agent tag's digest was captured after the runs;
its model modification timestamp predates verification, but that is not a
retrospectively pinned baseline digest. These identity limitations are explicit.

The detailed kitchen-bench question still fails because seven positional
arguments are supplied to a six-argument helper. This unrelated bug is recorded
in [the separate backlog](../IMPROVEMENTS.md). Existing missing answer parts,
unsupported model claims, and judge inconsistencies were not repaired as part of
an organization refactor. The selected sample does not prove equivalence across
every question.

## Reproduction and artifacts

The baseline source reference is 7febbf7, with a clean initial worktree. Per-run manifests record their actual
source fingerprints and revisions. The [verification JSON](2026-11-25-organization-verification.json)
records checks and artifact hashes. Raw artifacts are retained under
`data/millennium/comparisons/2026-11-25-organization/`, including isolated execution
directories, original/final contracts, repeats, model identities, check logs,
OpenAPI comparison, and browser screenshots. Historical reports remain intact.

Run repository commands from the root with the mounted Git binary and Git
safe-directory environment variables in AGENTS.md. The comparison runner also
requires an isolated manifest database containing the existing index records and
`ENTITY_CARDS_DIR=/workspace/data/millennium`; it validates existing indexes and
cannot build them. The recorded comparison files are evidence and must not be
overwritten to create a new verification round.

- `python -m unittest discover -s tests` in the documented one-off container.
- `npm --prefix frontends/millennium test` and `npm --prefix frontends/millennium run build`.
- `python -m scripts.verification.organization_comparison baseline` or `final`,
  against the intended source tree and isolated verification data.
- `python -m scripts.verification.organization_repeats ...` for a new, explicitly
  selected repeat; it refuses to overwrite existing repeat records.
- `python -m scripts.verification.organization_report` regenerates the tracked
  per-question comparison from preserved raw results without calling providers.

All eleven plan gates are covered by the baseline/selection manifests, code map,
contract tests, package/import checks, index checks, API and Express checks,
initial comparisons, targeted investigations, live browser checks, and this report.
