# Plan: keep chapter tails with their chunk, and give each chunk its scene's context

Status: done, on by default (2026-10-17). Prepared: 2026-10-17. Diagnosis: `data/tuning/LOG.md` (2026-10-17, gun at Gosseberga),
scripts in `data/tuning/scripts-2026-10-17-gun/`.

## Why

"When Mikael Blomkvist found Lisbeth Salander severely wounded on the kitchen bench at the Gosseberga farmhouse ...
what Salander said to him?" (Additional Questions 45d561b9) abstains in all 8 runs. The answer never reaches the
candidates, but the answer model gets it right once it reads it in one passage, so the fault is in chunking and retrieval:

- **Chunking.** The answer is the last lines of *The Girl Who Played with Fire*. `_merge` emits a section's remainder
  as its own passage, so it is a 160-char chunk ("Kalle Fucking Blomkvist . She closed her eyes and let go of the
  gun ...") cut off from its setup (¶188-189, "carefully loosened the gun from her grip ... heard her mutter").
  81 of 110 sections end in a passage under 400 chars (130 such passages in all).
- **Retrieval.** Neither half matches on its own: the setup has the question's words but not the answer (dense rank
  504-1399, MiniLM rerank -5.51), the tail has the answer but names no scene (dense 520-1591, rerank -3.48).
- **Generation is fine** when the two are one passage: replaying exp121's evidence with setup+tail joined in front gives
  "Kalle Fucking Blomkvist" [E1]. As two separate passages (E11, E12) the model still abstains or says "muttered".
- **The context exists.** The scene summary says "Salander opens her eyes, mutters 'Kalle Fucking Blomkvist'". With it
  prefixed, the setup chunk ranks 1-22 in dense search (4, 1, 22, 2, 3, 13 per query) and reranks at 4.91, above all
  of today's evidence (best 4.13).

## Changes

### 1. Chapter tails join the previous chunk (index time)

In `_merge`, when a section ends with a remainder shorter than `min_passage_chars`, join it to the section's previous
passage instead of emitting it alone, if the result fits in `passage_chars` (700 + 160 here, limit 1200). If it
does not fit, the tail starts from the previous passage's last units instead (like `passage_overlap`, but only for
the tail) so it never stands alone. A section that is short as a whole is unchanged.

- Unit tests in `tests/test_chunking.py`: tail joined, tail too big for joining gets the previous units, a short
  section left alone, and no joining across sections.
- Changing `_merge` changes `merge_fingerprint`, so the passage collection gets a new name and is re-embedded
  (MiniLM, minutes). Passage IDs change only for the chunks that changed.

### 2. Scene context for each chunk (index time, used for search and reranking only)

Each passage gets a `context` field: the summary of the scene window that best covers it. A passage is in up to two
windows (window 6, stride 3), so the window where it sits nearest the middle is used. If no window holds it, there is
no context.

- **Search.** A second vector per passage, of `context + "\n" + text`, in a new collection (or a named vector) built
  after the scene index, because the summaries are made from the passages. The pipeline searches it instead of the
  plain vectors when `scene_context` is on (opt-in setting, default off until step 6).
- **Reranking.** The cross-encoder scores `(question, context + text)` for every row that has a context (fused, wider,
  keyword, scene and entity rows alike, so the bars stay comparable).
- **Evidence.** The answer model still reads and cites only the book text, never the summary (summaries are written by
  gemma4:26b and can be wrong). Showing the summary as a separate "Scene:" line is a later, separate experiment.
- No new LLM calls: the summaries are already in `data/scene-summaries.jsonl`.

### Cache cost of change 1

Scene summaries and entity windows are cached by their member passage IDs, so windows that hold a changed chunk are
re-summarised (gemma4:26b) and re-extracted. Windows start at each section's beginning, so only the last one to three
windows of the 81 changed sections are new: about 150-250 of 3,618 summaries, plus the matching entity windows. Step 1
counts the misses exactly before anything runs.

## Steps

1. **Dry run, no LLM.** Build the new chunk list in memory: count changed passages, scene and entity windows that
   would miss the caches, and list ten changed tails to read by hand.
2. **Offline ranks for change 2 on today's index** (no reindex, no LLM). Embed `context + text` for every passage, then
   replay the recorded queries of the latest Additional Questions and QA.csv runs. Per question: the gold passage's
   fused and reranked rank (45d561b9 and the gold passages already marked for Additional Questions), and how many
   QA.csv items change their top 10. Also measure crowding: how often more than three of the top 10 come from one
   scene window, since neighbours share a summary.
3. **Implement change 1** with its tests, rebuild the index in the `millenium-tuning` container (summaries and entity
   windows for the missed windows only; nothing else uses Ollama meanwhile, unload afterwards).
4. **Implement change 2** behind `scene_context`, with tests (context choice per passage, rerank input, evidence text
   unchanged), and build the contextual vectors.
5. **Target first:** run 45d561b9 alone with `{"scene_context": true}` and without, and read the answers.
6. **Datasets:** Additional Questions, then QA.csv, compared per item against a fresh defaults control on the same
   new index (the old controls ran on the old chunks). Bar: no item gets worse because it lost the passage with its
   answer; check score drops by reading the answers (the judge is lenient and noisy). Turn `scene_context` on by
   default only if it passes, on approval.
7. **Wrap-up:** scripts to `data/tuning/scripts-2026-10-17-scene-context/`, a row and a section in `IMPROVEMENTS.md`
   in the same commit as each change, `data/tuning/LOG.md` notes. Deploy only on approval.

## Risks

- **Crowding:** passages of one scene share a summary, so a matching scene may fill the top 10 with its non-answer
  passages and push out other evidence. Step 2 measures this; the fix, if needed, is at most two passages per window
  before reranking.
- **Wrong summaries:** a summary that names the wrong person lifts the wrong passages. The answer model never sees it,
  but the evidence shifts.
- **The rerank bars** (`low_confidence_score` 2.0, `wide_trigger_score` 3.5, keyword and scene margins) were tuned on
  context-free scores and may need re-checking once scores rise.
- **Change 1 alone** does not fix the target (the joined chunk still reranks at -4.92); it makes change 2 work and
  stops answers being cut off at chapter ends.

## Progress notes

- 2026-10-17 step 1 (dry run, `dry_run.py`): 5,594 → 5,522 passages; 72 section tails join the passage before them
  (none needed the fallback); 58 short passages left are whole short sections. Cache misses: 72 scene windows and 72
  entity windows. The target becomes one 861-char passage, PwF ¶188-191.
- Step 2 (offline replay of exp121 Additional Questions and exp133 QA.csv queries, `ctx_sim.py`, `ctx_path.py`):
  swapping in contextual vectors and contextual reranking (the plan's first design) puts the target at rank 1 but keeps
  only ~1.8 of 10 QA.csv evidence passages, drops a cited passage on 18/36 items and lets one window fill more than
  three slots on 12/36. Adding contextual rankings to the fusion misses the target. **Design change:** a gated path
  like the wider-pool and keyword paths. Contextual search finds passages; everything (fused candidates too) is
  reranked with its summary in front; up to 2 passages that are not already in the evidence are added in front if
  they rank in the top 3 that way and score above `low_confidence_score`. Replay: target rank 1, no evidence lost
  (it only adds), fires on 26/36 QA.csv and 4/8 Additional Questions; "beat every candidate by a margin" never fires
  on the target (the summary lifts the scene's other passages too: 5.34 / 5.17 vs 4.91).
- Step 3: tail rule in `_merge` (+3 tests); real build gives the dry-run chunks (5,522, 58 short).
- Step 4: `scene_context` (opt-in), `scene_context_rank` 3, `scene_context_max_hits` 2; context collection
  `<scene collection>_context` (same IDs, payload `context`), built after the scene index; `_context_hits` in the
  pipeline after the keyword path (+3 tests). 74 tests pass.
- Step 5: on the new chunks the whole-summary context missed the target (it sits at the end of one window whose summary
  is mostly about other passages). Context is now the 2 summary sentences nearest the passage (`scene_context_sentences`).
  exp140 target 0 → 1.0.
- Step 6: hits in front shifted the answers and the scene path (QA 0.736 → 0.708, a wrong answer on the Dag Svensson
  item), so hits now go after the usual evidence and the later paths do not see them (+1 test, 76 pass). Final: Additional
  Questions 0.438 → 0.562 (target up, none down); QA.csv 0.736 → 0.708 (2 up, 3 down; no item lost a passage; one down is
  a judge error, two are answer drift from the added passages; reproducible). `scene_context` stays off by default.
