# v2.17 Step 8 — serial live validation

**Status: complete.** All 20 fixed-sample provider/question pairs have a selected completed run, and every attempt is retained. Step 8 did not change the live default pipeline. Step 9 has not started. The per-question Ollama historical/current answer and score comparison is in [ollama-answer-comparison.md](ollama-answer-comparison.md); `progress.json` is the machine-readable selection record.

Runs used one-item filters, explicit v2.17, fresh generation (`cache_mode=bypass`), and the isolated Python 3.12 app image. The Git bind mount and safe-directory variables followed repository `AGENTS.md`. Correctness and latency always refer to the same selected attempt. Reproduce the structural evidence audit with `python scripts/langgraph_audit_live_evidence.py`; its output is saved as `evidence-audit.json`.

## Escalated answer and evaluator findings

The user authorized recording substantive failures and finishing the remaining pairs. These are preserved without scorer changes except the separately approved OpenAI factory-item rubric correction:

- Ollama Q2: all three attempts contain unsupported fabricated claims about Harriet's captivity despite high correctness scores. Attempt 1 remains the numeric selection; correctness is not treated as evidence of answer validity.
- Ollama Q5: selected score 0.9625 vs. 1.0 baseline. The answer correctly identifies Gottfried's killer but adds a questionable Martin witness/blackmail claim; citation support is 0.5.
- Ollama Q6: selected attempt 3 scores 0.6167 vs. 1.0 baseline and falsely says Harriet's remains were found. Another attempt abstained despite a 1.0 correctness score.
- Ollama Q8: all three attempts score 0.55 vs. 1.0 baseline and omit the private-document discovery on Mikael's computer. Attempt 3 is the earliest best-score tie.
- Ollama Q9: all three attempts are exhausted; attempt 1 is selected at 0.5 vs. 1.0 baseline. Attempt 3 scored 0.0 on correctness and 1.0 on citation support while evaluators contradicted each other about the farmhouse/brickworks interpretation. The answer confusion remains recorded.
- Ollama Q1: the score difference was reviewed as evaluator variance under the user's authorization; no rubric was changed.

OpenAI Q2 and Q6 evaluator differences were similarly recorded without changing historical baselines. For OpenAI Q9, the user approved a question-specific correction to item `36c50723-3b65-49f6-9d9b-70574cc9471c`. Only that item rubric changed; the original live results remain immutable and `factory-rubric-rescore-v2.json` records the effective correctness values. Its selected answer retains its original 41.12-second latency. No other scorer or item was modified.

## Source and execution record

The final executable source fingerprint is `69bede90a72a381c3c25cb3e1d4a8e3f78b4c06330058d3b37189328d80521df`. OpenAI Q10 exposed an obsolete seventh argument to `scene_moment`; the signature-aware regression test preceded the fix, and the successful retry verified the exact response with 1.0 correctness/citation support. `moment-fix-impact.json` and the evidence audit document compatibility of selected earlier runs: only `app/agent/tools/scenes.py` changed, and selected earlier items did not call the changed helper. The failed attempt remains archived.

The audit checks completed attempts for single-item selection, bypass mode, item/trace/execution identity, source compatibility, review of rejected tool submissions, trace parent timing, and one graph finalization. It also records selection status and per-attempt hashes. It does not calculate Step 9 aggregate acceptance, run release checks, or authorize deployment. Documented answer regressions remain open for follow-up; this completion closes only Step 8 evidence collection.
