# Best-performing pipeline versions

Ranked by mean answer correctness score for each regular Millennium dataset. Citation-support scores are not included.

## Method

- Included runs covering at least 80% of the items in that run's pinned dataset snapshot.
- Excluded single-item runs.
- Coverage is completed result items over the pinned snapshot size. Dataset snapshots can differ in size across runs.
- Scores are the mean of `answer_correctness_v2` scores for the run. All 20 ranked runs used the local `qwen3:8b` judge; none of these scores came from `answer_correctness_codex_v1`. Names containing `openai` or `gpt-6-luna` identify the answer pipeline's query agent, not the evaluator.

## QA.csv

| Rank | Experiment | Pipeline version | Correctness (`qwen3:8b`) | Codex correctness (`gpt-5.6-luna`) | Coverage | Experiment ID | Execution ID |
|---:|---|---|---:|---:|---:|---|---|
| 1 | `openai-gpt-6-luna-high-QA` | v2.12 | 0.9086 | 0.8141 | 36/36 | `764cc2418408a4ea` | `d5e9c5ad` |
| 2 | `v2.1-query-aware-rerank-only` | v2.1 | 0.8824 | — | 36/36 | `40346a8d399ed2c7` | `1693c551` |
| 3 | `kubilay` | v2.2 | 0.8748 | — | 36/36 | `4ff5ebd1a66dbfb8` | `33c78788` |
| 4 | `2026-10-22-v2.13-luna-high-QA.csv` | v2.13 | 0.8745 | — | 36/36 | `fd52e12721de3536` | `8dc3ef0b` |
| 5 | `story-graph-reasoning-v2.14-QA` | v2.14 | 0.8727 | — | 36/36 | `9957eaa7b41ed87b` | `61b3467c` |

## set3

| Rank | Experiment | Pipeline version | Correctness (`qwen3:8b`) | Codex correctness (`gpt-5.6-luna`) | Coverage | Experiment ID | Execution ID |
|---:|---|---|---:|---:|---:|---|---|
| 1 | `openai-gpt-6-luna-high-set3` | v2.12 | 0.7675 | — | 15/15 | `8451bbff73197241` | `77f54b4d` |
| 2 | `entity-cards-reasoning-v2.13-set3` | v2.13 | 0.7239 | — | 15/15 | `163cfd81374ea8b8` | `436795ab` |
| 3 | `v2.3-gpt-6-luna-set3` | v2.3 | 0.7158 | — | 15/15 | `ee483532e4d14912` | `a46dbdf5` |
| 4 | `kubilay` | v2.2 | 0.6763 | — | 15/15 | `9dd9500d0dcb8588` | `9eb12349` |
| 5 | `v2.12` | v2.12 | 0.6742 | — | 15/15 | `71198828c3c0c970` | `039abfb9` |

## right-set-3

| Rank | Experiment | Pipeline version | Correctness (`qwen3:8b`) | Codex correctness (`gpt-5.6-luna`) | Coverage | Experiment ID | Execution ID |
|---:|---|---|---:|---:|---:|---|---|
| 1 | `entity-cards-reasoning-v2.13-right-set-3` | v2.13 | 0.9135 | — | 28/28 | `99b35b171b966af9` | `3d8897b7` |
| 2 | `v2.3-gpt-6-luna-right-set-3` | v2.3 | 0.8920 | — | 28/28 | `833fe4ec4d1f8528` | `7e6ac174` |
| 3 | `v2.12` | v2.12 | 0.8539 | — | 28/28 | `3ceb0071bf8d62a4` | `c07f1c5b` |
| 4 | `baseline-v2.12-default-right-set-3` | v2.12 | 0.8405 | — | 28/28 | `b247cd5d9ce9da1d` | `8b30a2d7` |
| 5 | `story-graph-reasoning-v2.14-right-set-3` | v2.14 | 0.8388 | — | 28/28 | `25790c44c054508a` | `25b489d9` |

## Additional Questions

| Rank | Experiment | Pipeline version | Correctness (`qwen3:8b`) | Codex correctness (`gpt-5.6-luna`) | Coverage | Experiment ID | Execution ID |
|---:|---|---|---:|---:|---:|---|---|
| 1 | `baseline-v2.12-default-Additional-Questions` | v2.12 | 0.9875 | — | 8/8 | `b2e7fb1676745447` | `090606b4` |
| 2 | `kubilay` | v2.2 | 0.9792 | — | 8/8 | `4a467771e91507c9` | `a684db5d` |
| 3 | `v2.3-gpt-6-luna-Additional-Questions` | v2.3 | 0.9500 | — | 8/8 | `49f6f90f2223667a` | `6494f50f` |
| 4 | `2026-10-22-v2.13-luna-high-Additional-Questions` | v2.13 | 0.9021 | — | 8/8 | `96ab190ac570dbe8` | `98e9df42` |
| 5 | `story-graph-reasoning-v2.14-Additional-Questions` | v2.14 | 0.8563 | — | 8/8 | `d97ba1ac2f66173f` | `6914235c` |

The Additional Questions runs used pinned snapshots of eight items. Some QA.csv runs have a `partial` overall execution status because a non-correctness evaluator failed; correctness scores were available for all 36 items and were included here.
