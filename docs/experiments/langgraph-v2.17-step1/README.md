# v2.17 Step 1 — frozen comparison inputs

Completed 2026-11-26. Scope: Step 1 of [the roadmap](../../langgraph-implementation-roadmap.md) only. No baseline generation, live answering, dependency installation, execution refactor, deployment, or Step 2 checks were performed.

## Starting identity

The implementation starting revision is `55a9980` (full revision in [starting-state.json](starting-state.json)); its worktree was clean at capture. This includes the roadmap commit and precedes all Step 1 artifacts. The earlier reading-only revision was `a8874d0`.

The starting-state artifact records resolved v2.16 configuration for Ollama and OpenAI, catalog/pipeline identities, corpus checksum, live Qdrant collection configuration and point count, installed local model digests, current evaluator specs, and protected handoff hash. OpenAI comparison settings explicitly select `gpt-6-luna` with high reasoning, matching the recorded references. Ollama selects `qwen3.6:35b`, thinking disabled, 16,384 context and 1,600 output tokens. Neither provider was called for generation.

All historical references and the current resolver identify passage collection `millennium_books_a7ebc5a988df037cd2ee`, with 5,522 indexed passages and corpus checksum `d5f87c43d9e3b5cc37e6b0ab2131eadc627450d2c2af6d0f508c6ab83275cf9b`. Historical manifests retain scene/entity index identities; the current live passage collection inspection is in the starting-state artifact.

## Fixed sample

[comparison-manifest.json](comparison-manifest.json) is the machine-readable acceptance input. Its order is the serial validation order for both providers. Questions were chosen for coverage and shared historical availability, rather than scores. The 3/2/3/2 dataset allocation gives exactly 10 equally weighted questions.

| # | Dataset | Question / coverage | OpenAI correctness | Ollama correctness | OpenAI seconds | Ollama seconds |
|---|---|---|---:|---:|---:|---:|
| 1 | QA.csv | Mathematics book; direct fact | 0.9000 | 1.0000 | 16.09 | 33.10 |
| 2 | QA.csv | Who killed Harriet?; false premise | 0.9750 | 1.0000 | 18.95 | 34.30 |
| 3 | QA.csv | Mikael's nickname; name | 0.9167 | 0.9500 | 15.44 | 18.79 |
| 4 | set3 | Top 10 characters; broad narrative | 0.5000 | 0.5000 | 55.92 | 45.45 |
| 5 | set3 | How Gottfried really died; true account | 0.9500 | 1.0000 | 43.36 | 35.39 |
| 6 | right-set-3 | First-book summary; broad narrative | 0.6333 | 0.9667 | 41.45 | 75.97 |
| 7 | right-set-3 | Teleborian court outcome; sequence/name | 0.9500 | 1.0000 | 27.84 | 51.06 |
| 8 | right-set-3 | How Mikale knows Salander is a hacker; name | 1.0000 | 1.0000 | 19.78 | 20.84 |
| 9 | Additional Questions | Abandoned factory; sequence | 1.0000 | 1.0000 | 40.53 | 97.15 |
| 10 | Additional Questions | Gosseberga kitchen quotation; speech | 1.0000 | 1.0000 | 14.86 | 53.69 |
| Mean | Same 10 items | Equal item weights | 0.88250 | 0.94167 | 29.422 | 46.574 |

These are selected-item means, not whole-dataset averages. The acceptance calculations will compare the final candidate against these inputs; no candidate acceptance claim is made here.

The first live smoke check, when Step 8 is authorized, is **OpenAI / QA.csv / `02ad392b-b200-58ce-a96d-f7cd57a5a252`**, “What academic mathematics book does Lisbeth Salander carry around and memorize?”, with fresh generation (`--cache-mode bypass`). No smoke check has been run.

## Provider-specific sources and differences

The eight experiment IDs are exactly those in the assessment. OpenAI uses recorded v2.16 runs for all four datasets. The latest-listed local fallback is v2.2 for QA.csv, v2.13 for set3 and right-set-3, and v2.12 for Additional Questions. No new baseline was generated. Full execution IDs, dataset run URLs, snapshot versions, per-item expected outputs, settings, evaluator manifests, source revisions, index identities and source hashes are preserved in the JSON.

Keep these differences visible in later acceptance reporting:

- **Local QA is not model-matched:** its recorded answering model is `qwen3:8b`, versus current `qwen3.6:35b`. The legacy manifest lacks `agent_settings` and records Git revision `unknown`; its model attribution comes from the assessment/best-performing table, not a newly inferred runtime configuration. Its saved resolved configuration remains intact. Unrecorded legacy agent settings and immutable historical answering-model revisions are not invented.
- Local QA correctness uses `answer_correctness_v2`, evaluator version **1**, evaluator ID `d7c950e17ca08e4013c15f8af57c01de99a219856d1d0d4593d0504656e9d7f1`. Later local records use version **2**, ID `480b4184d2f1fddafc52f72c8144e4185cfbecabe0d796e879d34f8a899d2db9`; OpenAI records use version **2**, ID `295243b34dfa38c45b70500cc29f6db589992d8b446470c543848a95bf822300`. All use the recorded `qwen3:8b` correctness judge and managed evaluator `cmvf5zbot0007mj7ti62igkpt`. Per-item metadata and complete evaluator definitions are retained.
- OpenAI Additional Questions has accepted facts-v4 rescoring. The original `evaluations` list remains stale while `correctness_score` reflects the accepted result. The selected factory and speech items use the saved accepted rescore evaluations (both 1.0), retain original evaluations (0.55 and 0.95), and hash/link the rescore artifact. Its per-evaluation `evaluator_id` is null; the source execution's evaluator identity and managed evaluator/version are retained separately. The facts-v5 photo override is recorded at source level but affects no selected item.
- Dataset versions differ for QA.csv and Additional Questions. Every selected question has identical input text in both snapshots. Both original expected outputs and current scoring facts are retained so rubric evolution is visible. The later photo question is absent from the local Additional Questions run and was not selected; no selected item lacks historical coverage.
- The older local pipelines precede the v2.16 conversation handoff. Recorded manifests include older behavior flags (`progress_control`, `query_aware_reranking`, and, in v2.16, `conversation_handoff`) that are no longer fields in the current settings dataclass. These historical fields remain preserved, not treated as current overrides. OpenAI historical settings otherwise match the selected current provider settings on shared fields; local legacy configurations are fallback comparisons, not claims of behavioral equivalence.
- Current local digests are captured, but historical answering-model weight digests are not recorded, and OpenAI exposes a model alias rather than an immutable weight revision. These are provenance limits, not missing question scores or latencies.

## Verification and reproduction

The export script opens SQLite with `mode=ro`. It selects only the eight specified experiments, requires each selected item and numeric correctness/positive latency for each provider, checks identical question inputs, verifies accepted rescores against stored item scores, and enforces exactly 10 unique item IDs. It copies recorded answer latency, excluding evaluator latency, from the same historical answer as its correctness score. Manifest file hashes and canonical saved-result hashes identify the local evidence.

From the repository root, `python scripts/langgraph_freeze_comparison.py` regenerates the comparison JSON using the existing local database and execution artifacts. It requires no app dependencies or model access. `scripts/langgraph_freeze_starting_state.py` documents the separate read-only initial identity capture; rerunning it would replace the frozen starting state with current state, so do not rerun it during later steps. It was executed in a one-off app container with the repository/Git mounts, safe-directory variables and `PYTHONPATH=/workspace`; the live app container was untouched.

Step 1 gate: **20/20 selected question/provider results identified, all four datasets and required coverage represented, exactly 10 fixed shared questions, first smoke selected, comparison inputs and provenance committed.** No unresolved selected-item data blocker remains. Stop here; dependency compatibility and execution-contract tests belong to Step 2.
