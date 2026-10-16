# Plan: better recall for the Additional Questions

Status: proposed, not started. Prepared: 2026-10-16.

## Why

Run `7d83909e` (Additional Questions, 7 items, defaults) scored 0.214 answer correctness. The answers that failed
were retrieval misses: every gold passage is in the corpus, but only about 1 of 7 reached the top 10 evidence, so
the model abstained or answered from the wrong scene. The misses fall into three groups:

- **Wording mismatch:** "abandoned factory" vs "brickworks", "in her house" vs the Lundagatan apartment.
- **Exact phrases:** "No compromises" appears three times in *Hornet's Nest*, but dense search scores it about −10.
  All retrieval is dense (`query_points`); there is no keyword search.
- **Misspelled names:** "Mikhail" got past name completion and grammar correction.

Already tried and rejected (see `IMPROVEMENTS.md`): HyDE off (exp98/exp99), and `candidate_count` 40–100 on its own,
which changed the evidence on 28–34 of 35 items.

## Strategy

Recall first: get the passage with the answer into the evidence, then improve the answer. Measure each change cheaply
and deterministically, without the answer LLM, and send only winners to the full QA.csv regression check.

## Steps

1. **Mark gold passages (measurement only).** Record the passage IDs that hold each Additional Question's answer
   (Armageddon shirt, "Kalle Fucking Blomkvist" at Gosseberga, the brickworks/nail gun scene, the three "No
   compromises" passages, the Milton/Frode background check, Agneta). Do the same for QA.csv where it's easy. The IDs
   score retrieval only and never go into prompts or code.
2. **Recall harness.** An offline script that runs retrieval only and reports, per question, the gold passage's rank in
   the fused candidates and in the reranked top 10. It replays recorded queries (HyDE, alternatives, grammar fix) so
   results are deterministic and avoid qwen3:8b's order sensitivity. Baseline: run `7d83909e` and exp100.
3. **Changes, one at a time, measured in the harness:**
   - a. **Name fix scoped to the corpus:** extend `_complete_names` so a capitalized word that never appears in the
     books maps to the closest-spelled frequent name (Mikhail/Michael → Mikael). Check every QA.csv name for false
     fixes.
   - b. **BM25 keyword search:** an in-memory BM25 index over the passages, added as another ranking in the existing
     RRF fusion, with extra weight for quoted phrases. No Qdrant reindex is needed for the experiment.
   - c. **Deeper rerank pool:** feed 50/100 candidates to the cross-encoder; measure recall and how much the top 10
     changes.
   - d. **Combinations** of the changes that help.
4. **End-to-end on Additional Questions:** run the best one or two variants in the separate `millenium-tuning`
   container and read the answers, not just the scores (the judge is lenient, e.g. 0.5 for a wrong café answer).
5. **QA.csv regression check:** full run with the winner, compared per item against the exp100 control
   (0.764 / 0.861), plus a controlled fixed-query replay (as in exp99) to separate real regressions from model noise.
   Bar: no item gets worse because it lost the passage with the answer.
6. **Wrap-up:** unload Ollama between runs and never overlap runs; copy the scripts to
   `data/tuning/scripts-2026-10-16-recall/`; add a table row and a section to `IMPROVEMENTS.md` in the same commit
   as the change. Deploy only on approval.

## Subplans

- [Scene path for "a detail at a specific moment" questions](2026-10-16-additional-questions-recall-scene-path.md):
  root cause of the T-shirt miss and a plan for the scene index.

## Risks

BM25 and the deeper pool will change evidence on many QA.csv items, so step 5 is the main gate for them. The name fix
is the safest and most targeted change.
