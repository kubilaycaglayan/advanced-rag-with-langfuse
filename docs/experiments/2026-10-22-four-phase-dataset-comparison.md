# Four-phase dataset experiment comparison

Sixteen sequential runs: four datasets across the baseline, GPT-6 Luna API, entity-card prompt draft, and story-graph prompt draft. Each table cell links to its Langfuse dataset run.

## Decision

Do not promote the v2.13 entity-card or v2.14 story-graph pipelines. Keep both specifications in [pipelines.md](../../pipelines.md) as drafts; v2.12 remains the default. Draft prompts and the graph-search tool are scoped to their respective draft versions.

**Cell format:** mean correctness · mean per-item latency. Correctness ranges from 0 to 1. Bold marks the best correctness score or lowest latency within that row. The final row pools individual items across all four datasets.

| Dataset | Baseline · local · v2.12 | GPT-6 Luna · high · v2.12 | Entity cards · local · v2.13 draft | Story graph · local · v2.14 draft |
|---|---:|---:|---:|---:|
| QA.csv (n=36) | [0.84 · 40.06s](<http://127.0.0.1:28420/project/millenium/datasets/cmv7zo6nw0007pa7t55mno068/runs/f8011e249830f6cf>) | [**0.91** · **23.23s**](<http://127.0.0.1:28420/project/millenium/datasets/cmv7zo6nw0007pa7t55mno068/runs/764cc2418408a4ea>) | [0.86 · 40.08s](<http://127.0.0.1:28420/project/millenium/datasets/cmv7zo6nw0007pa7t55mno068/runs/40d6e7051ab5e40a>) | [0.87 · 42.33s](<http://127.0.0.1:28420/project/millenium/datasets/cmv7zo6nw0007pa7t55mno068/runs/9957eaa7b41ed87b>) |
| Additional Questions (n=8) | [**0.99** · 54.50s](<http://127.0.0.1:28420/project/millenium/datasets/cmv892lbn0005mj7u0q074bua/runs/b2e7fb1676745447>) | [0.79 · **26.13s**](<http://127.0.0.1:28420/project/millenium/datasets/cmv892lbn0005mj7u0q074bua/runs/41a4b7a39f99b90d>) | [0.78 · 43.22s](<http://127.0.0.1:28420/project/millenium/datasets/cmv892lbn0005mj7u0q074bua/runs/cf9703b255903555>) | [0.86 · 74.42s](<http://127.0.0.1:28420/project/millenium/datasets/cmv892lbn0005mj7u0q074bua/runs/d97ba1ac2f66173f>) |
| set3 (n=15) | [0.67 · 46.48s](<http://127.0.0.1:28420/project/millenium/datasets/cmvcgm11i0003mj7tbjygxtlr/runs/042a4df643ccc163>) | [**0.77** · **26.60s**](<http://127.0.0.1:28420/project/millenium/datasets/cmvcgm11i0003mj7tbjygxtlr/runs/8451bbff73197241>) | [0.72 · 47.47s](<http://127.0.0.1:28420/project/millenium/datasets/cmvcgm11i0003mj7tbjygxtlr/runs/163cfd81374ea8b8>) | [0.67 · 55.60s](<http://127.0.0.1:28420/project/millenium/datasets/cmvcgm11i0003mj7tbjygxtlr/runs/7b6a97afeaefa686>) |
| right-set-3 (n=28) | [0.84 · 38.10s](<http://127.0.0.1:28420/project/millenium/datasets/cmvcgsorw0005mj7tu0turtdo/runs/b247cd5d9ce9da1d>) | [0.80 · **26.25s**](<http://127.0.0.1:28420/project/millenium/datasets/cmvcgsorw0005mj7tu0turtdo/runs/9f4569c5a8c2f08c>) | [**0.91** · 47.71s](<http://127.0.0.1:28420/project/millenium/datasets/cmvcgsorw0005mj7tu0turtdo/runs/99b35b171b966af9>) | [0.84 · 44.21s](<http://127.0.0.1:28420/project/millenium/datasets/cmvcgsorw0005mj7tu0turtdo/runs/25790c44c054508a>) |
| **Experiment mean (n=87)** | 0.82 · 41.87s | 0.84 · **25.05s** | **0.84** · 44.10s | 0.83 · 48.17s |

## Notes

- **Mean per-item latency** is the arithmetic mean of `output.latency_seconds` across dataset items. The experiment-mean row is pooled across all items (weighted by the number of items in each dataset).
- Correctness is the mean `answer_correctness_v2` evaluation score.
- All 16 runs completed their dataset items and Langfuse trace verification reported zero missing traces. Five runs were marked partial because of evaluation failures: baseline QA.csv (1), baseline right-set-3 (1), GPT-6 Luna QA.csv (1), entity-card QA.csv (1), and story-graph QA.csv (2).
- Only the GPT-6 Luna phase used the OpenAI provider (`gpt-6-luna`, high reasoning). The other three phases used the local default model (`qwen3.6:35b`).
- The story-graph draft recorded 8 `graph_search` calls total: QA.csv (3), set3 (2), and right-set-3 (3). Additional Questions produced no graph calls.
