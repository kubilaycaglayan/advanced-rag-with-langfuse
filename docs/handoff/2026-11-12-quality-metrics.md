# Handoff — quality metrics for pipeline v2.12

Read this before acting. The user is measuring first; **do not optimize the pipeline** until they explicitly ask.

## Purpose and goal

We are adding per-question retrieval and answer-quality metrics to the Millennium RAG pipeline **v2.12 only**, using Langfuse for traces/scores.

Four metric families:

- **Retrieval precision** — relevant passages / retrieved passages.
- **Retrieval recall** — relevant passages retrieved / all relevant passages.
- **Generation faithfulness** — answer claims supported by retrieved context.
- **Generation answer relevancy** — answer addresses the question.

Start with `QA.csv`, one question at a time. The immediate goal is a trustworthy measurement loop, not better answers yet.

## Working principles

- **Measurement mode, not optimization.** Do not change v2.12, prompts, rankers, or query behavior.
- **Only v2.12.** Do not introduce or mention other pipeline versions.
- **Langfuse-first.** Read traces/scores from Langfuse; do not rely on local `results.json` when Langfuse has the data.
- **Step by step.** Wait for the user's explicit “go” before running a new stage. Do not bulk-map or bulk-write without approval.
- **User is learning.** Explain terms plainly and briefly; avoid long paragraphs; rhetorical questions may be about understanding, not tasks.
- **The user cannot review thousands of passages.** Do the labeling work; surface only critical exceptions, ideally 2–3 questions at a time.
- **Direct-only headline.** The headline precision/recall uses `direct` passages only. `support` passages are reported separately.
- **Do not confuse Precision@K with Hit@K.** Precision = relevant / K; Hit@K = 1 if any relevant passage is in top K. They are equal only at K=1.
- **Single-evidence questions use Hit@K, not Precision@K.**
- **Broad questions use answer-level metrics, not retrieval precision/recall.**
- **Qrels are evidence, not prompts.** Never feed them into retrieval or answer generation.
- Use `qwen3.6:35b` for faithfulness/relevancy judging. `qwen3:8b` gave a wrong 0.0 relevancy score on QA1.
- Preserve the user's Langfuse comments. They are part of the labeling record.

## Current artifacts

| Artifact | Purpose |
|---|---|
| `corpora/millennium/retrieval-qrels.json` | Qrels for 8 questions, 60 passage rows. Exact passage UUID, short ID, location, `direct`/`support`, supported claims, exact quote. |
| `app/quality_metrics.py` | Extracts search calls/context from Langfuse, computes metrics, judges faithfulness/relevancy, writes `qm_*` scores and a `retrieval metrics` span. |
| `app/quality_review.py` | Generates the HTML review page with notes, labels, dark mode, JSON export. |
| `tests/test_quality_metrics.py` | Unit tests for extraction, precision, full-text preference. |
| `data/millennium/quality-reviews/qa1-qa6.html` | Self-contained review page (currently 8 questions; filename is stale). |

Current index: `millennium_books_a7ebc5a988df037cd2ee` (5,522 passages, v2.12 1,200/400 config).

## Langfuse setup

- Project: `millenium`; dataset: `QA.csv` (36 items).
- Best v2.12 run: execution `d5e9c5ad-b7a3-4870-ba85-72e66705fc39`, Langfuse dataset run `764cc2418408a4ea`.
- This run used OpenAI GPT-6 Luna high reasoning. It is the best-scoring run, but not the local default. If measuring local v2.12 behavior, note the difference.
- Langfuse is v4 `events_only`. The SDK `scores.get_many` and `trace.get` endpoints return 404. Verify scores in ClickHouse: `default.scores` (use `FINAL`). Comments live in Postgres `public.comments`.
- Observations API needs `fields="core,basic,io,metadata"` or output/input are null.

QA traces:

| Label | Item ID | Trace ID |
|---|---|---|
| QA1 | `785e319a-89a1-5950-96cf-f99a23162a87` | `a18f003e157b35c8c10e455e5a7b6551` |
| QA2 | `f59e5c80-b58e-5639-add4-ac587c7a368a` | `71822c72bf05f7261aca3d1e60793272` |
| QA3 | `fb5b6f9d-2a37-5f3b-9f40-e8dd97ca7952` | `475ad49e1cf38a0d39b463615bec94d6` |
| QA4 | `c51aa2b1-bc66-5f9b-a323-23138d35675f` | `f76878c7f7100617066bfd2d0378480d` |
| QA5 | `09543843-b857-5bcd-ac6c-428ac4eb6501` | `681a40df59b7ffc609e9cc0254a29f92` |
| QA6 | `276fb010-6f69-5aef-9593-de095b841537` | `960fbf6b3221fe0a6fc5d313c6e41aa2` |
| QA7 | `9cec0dd1-4ede-5f14-8162-8de3c76938a8` | `092d4c3b31447e53d7ca9a3e83605f08` |
| QA10 | `5491526c-fa73-57bc-98c7-9bfc36fbf9a7` | `d2f777675a2311f6f2d7b7439e05e559` |

## Metric names

Convention: `qm_<category>_<stage>[_variant]`.

- `qm_precision_retrieval_at_5`
- `qm_precision_retrieval_at_10`
- `qm_precision_retrieval_scene_at_5`
- `qm_precision_retrieval_set`
- `qm_precision_retrieval_fact`
- `qm_recall_retrieval_at_5`
- `qm_recall_retrieval_at_10`
- `qm_recall_retrieval_scene_at_5`
- `qm_recall_retrieval_context`
- `qm_faithfulness_generation`
- `qm_relevancy_generation`

K belongs in the name. Per-call precision is attached to the `tool: semantic_search` / `tool: keyword_search` observation; the question-level mean is attached to the trace.

Definitions used now:

- **Precision@K** = direct gold passages in top K / K. Only if the call returned at least K. `semantic_search`/`keyword_search` only.
- **Set precision** = direct gold in deduplicated union / union size.
- **Context recall** = direct gold found in union / all direct gold.
- **Faithfulness** = supported answer claims / all answer claims.
- **Relevancy** = judge score for whether the answer addresses the question, ignoring factual correctness.

## Current qrels state

8 questions, 60 passage rows.

| Label | Question | Direct | Support | Flag |
|---|---|---:|---:|---|
| QA1 | Did Salander and Mikael have affair? | 12 | 2 | — |
| QA2 | Who tried to shoot Mikael? | 5 | 6 | Martin evidence is an inferred chain |
| QA3 | What Salander used when she was digging herself up? | 4 | 1 | — |
| QA4 | Who gave the cigarette case to Salander? | 3 | 2 | — |
| QA5 | What is the importance of the ciggarrete case? | 3 | 4 | — |
| QA6 | What is armageddon? | 1 | 0 | **single evidence** |
| QA7 | when was she wearing the armageddon shirt? | 1 | 7 | **single evidence** |
| QA10 | Does Mikael have savior complex? | 6 | 3 | **broad** |

Important labeling rule: **QA2 C1 is not a direct statement.** No sentence names Martin as the shooter. The chain is Martin had a rifle + shots fired at Mikael; keep the inference explicit. Do not present it as direct proof.

**QA7:** single evidence is the shirt passage `a1dd6e66`; recruitment passages `141c0304` and `b40dede4` are support only. Its old P@K/recall scores are stale and should be ignored; **Hit@5 = 1.0**.

**QA6:** the only direct passage is the T-shirt slogan `a1dd6e66`.

**QA10:** broad question. Many passages can support “savior tendencies”; a short gold list makes P@K/recall misleading. Use answer-level metrics.

## Current scores (written to Langfuse)

| Q | P@5 | Set P | Context recall | Faithfulness | Relevancy |
|---|---:|---:|---:|---:|---:|
| QA1 | 0.400 | 0.2222 | 0.3333 | 1.0 | 1.0 |
| QA2 | 0.200 | 0.1200 | 0.6000 | 1.0 | 1.0 |
| QA3 | 0.400 | 0.2353 | 1.0 | 1.0 | 1.0 |
| QA4 | 0.200 | 0.1579 | 1.0 | 1.0 | 1.0 |
| QA5 | 0.400 | 0.1071 | 1.0 | 0.75 | 1.0 |
| QA6 | 0.200 | 0.0169 | 1.0 | 1.0 | 0.5 |
| QA7 | 0.100 (stale) | 0.0208 (stale) | 0.3333 (stale) | 1.0 | 1.0 |
| QA10 | 0.200 (not meaningful) | 0.0351 (not meaningful) | 0.3333 (not meaningful) | 1.0 | 1.0 |

Interpretation:

- QA7 low P@K was retrieval noise (query “wearing a T-shirt” returned other clothing scenes). It is single-evidence; use Hit@5.
- QA10 low precision/recall is mostly qrels incompleteness and direct-only strictness, not necessarily retrieval failure. It is broad; do not optimize from these numbers.
- QA5 faithfulness is 0.75 because one answer claim (“linked her escape to the burial site”) is an inference, not stated.

## Next steps

1. **Make the scorer respect question type.**
   - `single_evidence: true`: compute `qm_hit_retrieval_at_5` (and Hit@10 when available) per call/trace; do not use P@K/context recall as the headline.
   - `question_type: "broad"`: skip retrieval precision/recall; keep per-call diagnostics if useful, but headline uses answer-level metrics.
   - Hit@K = 1 if any direct gold is in the top K, else 0. Question-level = mean across calls. Hit@5 is primary.
2. **Re-score QA6, QA7, QA10** with the new behavior. Be careful with duplicate scores; use stable score IDs or update existing score IDs where possible.
3. **Do not trust stale QA6/QA7/QA10 retrieval scores** after this change. Clean or clearly supersede them.
4. **Continue qrels in small batches.** Next lowest questions are around 0.9 correctness (e.g. QA27 Dag Svensson murder, QA16 Berger position); confirm with the user before starting.
5. **Wait for the user's explicit “go”** before starting step 1 or the next batch.

## Notes for the next agent

- User will keep leaving Langfuse comments; read them before changing qrels. One comment “single score” is on QA6 trace `960fbf6b…`, observation `cache refreshed: search`.
- The user has explicitly confirmed QA7 is single evidence and QA10 is broad.
- Do not add qrels to the Langfuse dataset item yet; the source of truth is `corpora/millennium/retrieval-qrels.json`.
- Worktree has uncommitted changes in `quality_metrics.py`, qrels, tests, and an untracked `quality_review.py`. Recent commit `7fbbe37` contains an earlier version.
- The review page is a convenience for the user, not the scoring source. It autosaves notes in browser localStorage and exports JSON; notes are not applied automatically.
