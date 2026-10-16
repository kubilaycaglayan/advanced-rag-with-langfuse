# Subplan: scene path for "a detail at a specific moment" questions

Parent plan: [Additional Questions recall](2026-10-16-additional-questions-recall.md).
Status: step 2 done for the T-shirt question as opt-in `scene_moment` (see `IMPROVEMENTS.md`, 2026-10-16); steps
0, 3–5 and the QA.csv regression check not started. Prepared: 2026-10-16.

## Root cause (T-shirt question)

"What t-shirt was Salander wearing when they first met with Mikael in her house?" asks for two things: **what to
find** (the T-shirt) and **which moment** (their first face-to-face meeting at her apartment). The book splits them:
the moment is in *Dragon Tattoo* ch. 18 ¶8–14 ("We don't even know each other", "Never had she met one of her
subjects face to face"), and the T-shirt is in ¶18, which never names Blomkvist and never says "first", "meet" or
"house". The pipeline matches the whole question against one passage at a time, so the "which moment" part drags
every stage away from the gold passage.

Measured with `data/tuning/scripts-2026-10-16-recall/diag_tshirt.py` and `diag_tshirt2.py` (run of 2026-10-16,
`7d83909e`; gold passage rank out of 5,594):

| Test | Result |
|---|---|
| Vector search: question, alternatives, HyDE | rank 566–784 (pool is top 30) |
| Vector search: "Salander T-shirt slogan" | rank 140 |
| BM25: question / "Salander T-shirt" | rank 30 / 9 |
| Reranker: question vs gold | −2.5 (top evidence 3.8) |
| Reranker: "Salander put on jeans and a T-shirt" vs gold | 4.1 |
| Wider chunk ¶12–21 (2,473 chars) | cosine 0.43 vs 0.46, rerank −0.5, exceeds MiniLM's 512 tokens |
| Scene search: question | rank 104 (top 10 used) |
| Scene search: "Blomkvist comes to Salander's apartment for the first time" | rank 1 |

Scene search ran on 6 of the 7 questions and added nothing every time (on "no compromises" it was skipped because
the question went down the low-confidence path). It's blocked three ways:

- It's queried with the whole question, so the right scene ranks 104th and only the top 10 count.
- The summary omits the T-shirt and the "first meeting".
- Admitted scene passages are reranked against the whole question, which marks the gold passage down.

Bigger chunks alone won't fix it.

## Steps

0. **Diagnose which block each failure hits (offline, no LLM).** Extend the diagnostic scripts to all 6 failures and
   the QA.csv questions with gold passages marked. Per question, report the gold scene's rank in summary search, its
   reranker score against the scenes covering current evidence plus `scene_margin`, and which block stopped it
   (outside the top 10, lost the margin, or skipped as low confidence).
1. **Deeper scene search (config only).** Raise `scene_search_hits` from 10 to 30–100 and let the cross-encoder pick
   the best summary (1,809 summaries; well under a second). Measure gold-scene recall and how often a scene now gets
   in on QA.csv, since admitted scenes can crowd the answer.
2. **Search for the moment and the detail separately (main change).** One LLM call splits the question into a "which
   moment" query and a "what to find" query. The "which moment" query searches scenes and decides whether a scene
   gets in. The "what to find" query reranks that scene's passages and the next window, so a detail just past the
   window edge isn't missed. Questions that don't split this way fall back to the whole question. It adds an LLM
   request, so comparisons use the fixed-query replay (qwen3:8b order sensitivity).
3. **Richer summaries (only if 1–2 aren't enough).** The summary prompt also lists concrete details (clothes, objects,
   places, short exact quotes) and turning points the text itself states ("they had never met"). That means a full
   rebuild of 1,809 summaries with gemma4:26b, so first test it on the gold scenes plus a random sample and compare
   their ranks.
4. **Low-confidence path.** Decide whether scene search should also run when confidence is low, with a cap on how
   many passages it adds (it was kept off there because extra scenes crowd the answer).
5. **Measure and check for regressions.** Recall harness on Additional Questions and QA.csv gold, then end-to-end on
   Additional Questions in `millenium-tuning` (reading the answers), then full QA.csv per item vs exp100 with a
   controlled replay; log in `IMPROVEMENTS.md`.

## Outcome (T-shirt question only)

- Step 1 alone does not help: the gold scene is not in the top 100 for the whole question, and the scene of the
  current evidence (Martin Vanger's crash) outscores everything found.
- Step 2 as planned (cross-encoder on the moment, margin over the covering scenes) is not robust: with the moment
  query the gold scene is in the top 3–7, but the cross-encoder cannot tell the first meeting from other home visits.
  What works is letting the generation model pick the scene from the summaries found for the moment, in reading
  order, and adding that window plus the one that continues it (the T-shirt is just past the chosen window's end).
  The DETAIL line is requested only to keep the detail out of the moment; it is not used for reranking.
- Target 0 → 1.0 in two judged runs (exp104, exp105). Default stays off until the step-5 regression check.

## Rules

- The diagnostic scripts find gold passages by question-specific text (for example "ARMAGEDDON"). They are
  measurement tools only and stay in `data/tuning`; neither they nor any question-specific text go into the pipeline.
- Every change must be general: the question split, summary prompt and settings must work for any question, not just
  these seven.

## Out of scope for now

"First" is a question about order across the whole story, and summaries only capture it when the text says so. If
Step 0 shows ordinal questions ("first", "last", "after") failing, a later idea is to prefer the earliest matching
scene using book and chapter position.
