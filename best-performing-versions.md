# Best-performing pipeline versions

Ranked by mean answer correctness score for each regular Millennium dataset. Citation-support scores are not included.

## Method

- Included runs covering at least 80% of the items in that run's pinned dataset snapshot.
- Excluded single-item runs.
- Coverage is completed result items over the pinned snapshot size. Dataset snapshots can differ in size across runs.
- Scores are the mean of available `answer_correctness_*` evaluator scores for the run.

## QA.csv

| Rank | Experiment | Pipeline version | Correctness | Coverage |
|---:|---|---|---:|---:|
| 1 | `openai-gpt-6-luna-high-QA` | v2.12 | 0.9086 | 36/36 |
| 2 | `v2.1-query-aware-rerank-only` | v2.1 | 0.8824 | 36/36 |
| 3 | `kubilay` | v2.2 | 0.8748 | 36/36 |
| 4 | `2026-10-22-v2.13-luna-high-QA.csv` | v2.13 | 0.8745 | 36/36 |
| 5 | `story-graph-reasoning-v2.14-QA` | v2.14 | 0.8727 | 36/36 |

## set3

| Rank | Experiment | Pipeline version | Correctness | Coverage |
|---:|---|---|---:|---:|
| 1 | `openai-gpt-6-luna-high-set3` | v2.12 | 0.7675 | 15/15 |
| 2 | `entity-cards-reasoning-v2.13-set3` | v2.13 | 0.7239 | 15/15 |
| 3 | `v2.3-gpt-6-luna-set3` | v2.3 | 0.7158 | 15/15 |
| 4 | `kubilay` | v2.2 | 0.6763 | 15/15 |
| 5 | `v2.12` | v2.12 | 0.6742 | 15/15 |

## right-set-3

| Rank | Experiment | Pipeline version | Correctness | Coverage |
|---:|---|---|---:|---:|
| 1 | `entity-cards-reasoning-v2.13-right-set-3` | v2.13 | 0.9135 | 28/28 |
| 2 | `v2.3-gpt-6-luna-right-set-3` | v2.3 | 0.8920 | 28/28 |
| 3 | `v2.12` | v2.12 | 0.8539 | 28/28 |
| 4 | `baseline-v2.12-default-right-set-3` | v2.12 | 0.8405 | 28/28 |
| 5 | `story-graph-reasoning-v2.14-right-set-3` | v2.14 | 0.8388 | 28/28 |

## Additional Questions

| Rank | Experiment | Pipeline version | Correctness | Coverage |
|---:|---|---|---:|---:|
| 1 | `baseline-v2.12-default-Additional-Questions` | v2.12 | 0.9875 | 8/8 |
| 2 | `kubilay` | v2.2 | 0.9792 | 8/8 |
| 3 | `v2.3-gpt-6-luna-Additional-Questions` | v2.3 | 0.9500 | 8/8 |
| 4 | `2026-10-22-v2.13-luna-high-Additional-Questions` | v2.13 | 0.9021 | 8/8 |
| 5 | `story-graph-reasoning-v2.14-Additional-Questions` | v2.14 | 0.8563 | 8/8 |

The Additional Questions runs used pinned snapshots of eight items. Some QA.csv runs have a `partial` overall execution status because a non-correctness evaluator failed; correctness scores were available for all 36 items and were included here.
