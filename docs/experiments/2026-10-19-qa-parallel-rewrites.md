# Full QA.csv A/B: parallel query rewrites (2026-10-19)

Status: completed. Result: **not adopted as the default**; `parallel_transformations` stays off and is available as
an explicit experiment. This is the backtracking record for the run.

## Setup

| Item | Value |
|---|---|
| Dataset | `QA.csv`, 36 items |
| Dataset version | `2026-10-19T11:21:42.206000+00:00` |
| Prompt label | `production` |
| Prompts | `rag-answer` v1, `rag-hyde` v3, `rag-query-expansion` v4, `rag-grammar-correction` v1, `rag-query-translation` v2, `rag-scene-moment` v1, `rag-scene-select` v1 |
| Correctness judge | `answer_correctness_v2` |
| Citation judge | `citation_support_v1` |
| Index collection | `millennium_books_a7ebc5a988df037cd2ee` (5,522 passages; 1,786 scenes; entity cards) |
| Generation model | `qwen3:8b` |
| Embedding model | `sentence-transformers/multi-qa-MiniLM-L6-cos-v1` @ `b207367332321f8e44f96e224ef15bc607f4dbf0` |
| Reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` @ `233902d25c440f23af6f7d6e94d2946bac0bee0a` |
| Ollama context | `OLLAMA_CONTEXT_LENGTH=8192` on the host for both runs |
| Ollama parallelism | baseline: default (`1`); parallel: `OLLAMA_NUM_PARALLEL=3` |
| Pipeline difference | only `parallel_transformations: false` vs `true` |

The app/frontend were redeployed by another agent at 13:07 UTC. The first baseline attempt
(`1a226c46-3093-427c-871b-c7558cdd2fb8`) was marked failed by the app restart and its timings were contaminated;
it is excluded. The baseline below was rerun after deployment, and the parallel run followed it.

## Runs

| Run | Execution | Started → finished | Pipeline ID | Langfuse dataset run | Correctness | Citation |
|---|---|---|---|---:|---:|---:|
| Baseline (`parallel_transformations: false`) | `d39a54ec-f72e-4354-9f4e-0cdf115ae5db` | 2026-10-19 13:10:01 → 13:31:57 UTC | `pipeline-37e82a622b93a40a` | [cdd6063974887522](http://127.0.0.1:28420/project/millenium/datasets/cmv7zo6nw0007pa7t55mno068/runs/cdd6063974887522) | 0.7275 (n=36) | 0.8429 (n=35) |
| Parallel (`parallel_transformations: true`, np=3) | `30a9c2f4-c082-46ca-923d-ee7d9b745929` | 2026-10-19 13:32:16 → 13:51:16 UTC | `pipeline-52a93bbe4961d59e` | [64b40f55eea53996](http://127.0.0.1:28420/project/millenium/datasets/cmv7zo6nw0007pa7t55mno068/runs/64b40f55eea53996) | 0.7442 (n=36) | 0.8472 (n=36) |

Both runs completed 36/36 with **zero failed items, evaluation failures, or telemetry failures**.

## Aggregate result

| Metric | Baseline | Parallel | Delta |
|---|---:|---:|---:|
| Correctness mean | 0.7275 | 0.7442 | **+0.0167** (SE 0.033) |
| Correctness median | 0.9292 | 0.9416 | +0.0124 |
| Citation mean, paired n=35 | 0.8429 | 0.8429 | **0.0** |
| Latency mean, all 36 | 22.29 s | 18.15 s | −4.14 s |
| Latency mean, warm 35 | 19.27 s | 18.05 s | **−1.21 s (−6.3%)** |
| Latency median, warm 35 | 16.12 s | 14.95 s | −1.17 s (−7.3%) |
| Transformation mean, warm 35 | 5.17 s | 4.03 s | **−1.14 s (−22%)** |
| Generation mean, warm 35 | 10.48 s | 10.30 s | −0.18 s |
| Wall clock | 21m56s | 19m00s | −2m56s (−13%) |

The all-item latency and wall-clock deltas are inflated by the baseline's first-item cold start: 128.0 s
(114.70 s transformation) versus 21.3 s (7.77 s) in the parallel run. Warm per-item total latency fell by
**42.4 s across 35 items**. Per-item warm latency: 24 faster, 11 slower, median delta −1.16 s.

## Correctness and citation movement

| Change | Count |
|---|---:|
| Correctness improved | 6 |
| Correctness regressed | 4 |
| Correctness unchanged | 26 |
| Improved by >0.2 | 4 |
| Regressed by >0.2 | 2 |
| Citation improved | 1 |
| Citation regressed | 1 |
| Citation unchanged | 33 |

Material correctness changes:

| Item | Question | Baseline | Parallel | Delta |
|---|---|---:|---:|---:|
| `a6ee3143…` | Who killed Harriet? | 0.550 | 1.000 | **+0.450** |
| `5491526c…` | Does Mikael have savior complex? | 0.550 | 1.000 | **+0.450** |
| `87adacdf…` | Who murdered Dag Svensson and Mia Johansson? | 0.000 | 0.500 | **+0.500** |
| `1f2db2c5…` | Why does Salander first go to Bjurman for money? | 0.500 | 0.750 | +0.250 |
| `360a9ab2…` | Berger holds what position at Millennium? | 0.450 | 0.050 | **−0.400** |
| `72d2d675…` | What does Salander ultimately demand from Bjurman? | 0.967 | 0.275 | **−0.692** |

Evidence changed on **21/36** items and answers changed on **30/36**; this is not a neutral speed-only change.

## Per-item results

| # | Session | Item ID | Correctness base → par | Δ | Citation base → par | Latency base → par | Transform base → par | Evidence / answer |
|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | QA1-did-salander-and-mikael-have-affair | `785e319a-89a1-5950-96cf-f99a23162a87` | 0.933 → 0.933 | +0.000 | 1.000 → 1.000 | 128.0 → 21.3 | 114.70 → 7.77 | same / changed |
| 2 | QA2-who-tried-to-shoot-mikael | `f59e5c80-b58e-5639-add4-ac587c7a368a` | 0.500 → 0.500 | +0.000 | 1.000 → 1.000 | 13.0 → 13.1 | 4.77 → 4.50 | changed / changed |
| 3 | QA3-what-salander-used-when-she-was-digging-herse | `fb5b6f9d-2a37-5f3b-9f40-e8dd97ca7952` | 0.950 → 0.950 | +0.000 | 1.000 → 1.000 | 13.6 → 12.7 | 5.69 → 4.49 | changed / same |
| 4 | QA4-who-gave-the-cigarette-case-to-salander | `c51aa2b1-bc66-5f9b-a323-23138d35675f` | 0.950 → 0.950 | +0.000 | 1.000 → 1.000 | 11.6 → 11.3 | 5.45 → 4.97 | same / same |
| 5 | QA5-what-is-the-importance-of-the-ciggarrete-case | `09543843-b857-5bcd-ac6c-428ac4eb6501` | 0.450 → 0.450 | +0.000 | 0.500 → 0.500 | 29.7 → 41.5 | 6.62 → 4.02 | changed / changed |
| 6 | QA6-what-is-armageddon | `276fb010-6f69-5aef-9593-de095b841537` | 0.900 → 0.900 | +0.000 | 0.000 → 0.000 | 24.2 → 24.3 | 5.97 → 6.82 | same / changed |
| 7 | QA7-when-was-she-wearing-the-armageddon-shirt | `9cec0dd1-4ede-5f14-8162-8de3c76938a8` | 0.000 → 0.000 | +0.000 | 1.000 → 1.000 | 32.0 → 26.4 | 4.83 → 3.13 | changed / changed |
| 8 | QA8-what-happened-to-martin-vanger-who-killed-hi | `2e5eecdb-66bc-5c47-b700-f3f46a6f169d` | 0.925 → 0.925 | +0.000 | 0.500 → 0.500 | 16.8 → 15.0 | 5.54 → 3.90 | changed / changed |
| 9 | QA9-who-killed-harriet | `a6ee3143-428c-5d8e-8d8e-d131dc92ac54` | 0.550 → 1.000 | +0.450 | 1.000 → 1.000 | 13.8 → 12.3 | 5.79 → 4.49 | same / changed |
| 10 | QA10-does-mikael-have-savior-complex | `5491526c-fa73-57bc-98c7-9bfc36fbf9a7` | 0.550 → 1.000 | +0.450 | 1.000 → 1.000 | 34.2 → 35.8 | 5.89 → 5.51 | changed / changed |
| 11 | QA11-for-what-crime-is-blomkvist-tried-and-convict | `c8154831-38ea-5acb-80fb-726086886e91` | 0.900 → 0.900 | +0.000 | 1.000 → 1.000 | 10.7 → 8.9 | 4.58 → 2.74 | changed / same |
| 12 | QA12-how-does-gottfried-vanger-die | `60f9103e-ea08-57f5-983a-3b6ae7069feb` | 0.500 → 0.500 | +0.000 | 1.000 → 1.000 | 12.2 → 11.1 | 5.06 → 3.82 | changed / changed |
| 13 | QA13-why-does-salander-first-go-to-bjurman-for-mon | `1f2db2c5-b52c-5442-907a-c2d64e3372e2` | 0.500 → 0.750 | +0.250 | 0.500 → 0.500 | 15.0 → 14.1 | 5.03 → 4.29 | changed / changed |
| 14 | QA14-henrik-hires-blomkvist-for-what-purpose | `b6e2949b-a8e6-579a-a278-eef587eb89c8` | 1.000 → 1.000 | +0.000 | 1.000 → 1.000 | 11.9 → 10.6 | 2.46 → 1.55 | same / changed |
| 15 | QA15-harriet-flees-to-what-country | `f5ac54db-aea2-522f-a5b6-2c2823abae2b` | 1.000 → 1.000 | +0.000 | 1.000 → 1.000 | 15.7 → 16.5 | 3.25 → 2.70 | same / same |
| 16 | QA16-berger-holds-what-position-at-millennium | `360a9ab2-e684-597d-97b7-fb7d239f02d9` | 0.450 → 0.050 | -0.400 | 1.000 → 1.000 | 8.9 → 7.8 | 1.67 → 1.18 | changed / changed |
| 17 | QA17-blomkvist-is-sentenced-to-how-many-months-in | `b24bb936-5f63-5762-9c38-b3a0e0dc1862` | 1.000 → 1.000 | +0.000 | 1.000 → 1.000 | 8.8 → 9.3 | 2.54 → 1.79 | changed / changed |
| 18 | QA18-what-does-salander-ultimately-demand-from-bju | `72d2d675-3064-51e5-afb2-47bb226b49f2` | 0.967 → 0.275 | -0.692 | 1.000 → 1.000 | 14.8 → 12.6 | 4.22 → 3.71 | changed / changed |
| 19 | QA19-how-does-henrik-vanger-describe-his-own-famil | `d25ea938-52e0-5462-9bf8-c0150771c11a` | 0.000 → 0.000 | +0.000 | 1.000 → 1.000 | 12.6 → 11.4 | 5.02 → 3.85 | same / changed |
| 20 | QA20-according-to-cecilia-what-event-changed-harr | `a65a73f6-d521-5670-acee-7269c2799314` | 0.000 → 0.000 | +0.000 | 1.000 → 1.000 | 46.1 → 39.9 | 5.19 → 3.89 | changed / changed |
| 21 | QA21-why-does-salander-decide-not-to-go-to-the-pol | `3206cb57-2291-5a0f-9a6e-cb2317dfc8db` | 0.975 → 0.950 | -0.025 | 1.000 → 1.000 | 19.1 → 17.0 | 7.01 → 5.29 | changed / changed |
| 22 | QA22-what-media-nickname-is-given-to-mikael-blomkv | `a1915174-dbfd-530b-87d5-cc9795361340` | 1.000 → 1.000 | +0.000 | 1.000 → 1.000 | 11.6 → 11.2 | 4.27 → 3.57 | changed / same |
| 23 | QA23-what-medical-condition-leaves-lisbeth-salande | `e6604c3c-f0f8-59a9-aaa5-08af5cfc4c32` | 1.000 → 1.000 | +0.000 | 1.000 → 1.000 | 16.1 → 14.3 | 6.34 → 4.05 | same / changed |
| 24 | QA24-what-is-the-name-of-lisbeth-salander-s-estran | `e02a591d-9ecc-53ff-9885-807890ade4bb` | 1.000 → 1.000 | +0.000 | 1.000 → 1.000 | 14.8 → 12.3 | 8.16 → 5.18 | same / changed |
| 25 | QA25-who-murdered-journalist-dag-svensson-and-his | `87adacdf-5695-5e07-9cf3-253888a777f8` | 0.000 → 0.500 | +0.500 | 0.500 → 0.500 | 13.4 → 13.9 | 7.04 → 5.44 | same / changed |
| 26 | QA26-why-is-ronald-niedermann-unable-to-feel-physi | `ef0f75d1-1894-5c3e-810d-7fe27a5e4845` | 0.950 → 0.950 | +0.000 | 1.000 → 1.000 | 13.5 → 12.1 | 6.80 → 5.38 | same / same |
| 27 | QA27-what-is-the-name-of-the-secret-rogue-unit-wit | `e23fcfc0-fc13-5abc-b7d3-9d91ae09cc49` | 0.000 → 0.000 | +0.000 | 1.000 → 1.000 | 19.8 → 20.0 | 6.93 → 4.33 | changed / changed |
| 28 | QA28-how-does-lisbeth-salander-acquire-her-massive | `2b47ac9a-3e55-56e4-b0d2-58dbd9bbf6ee` | 0.925 → 0.925 | +0.000 | 1.000 → 0.500 | 58.5 → 33.4 | 5.86 → 5.29 | same / changed |
| 29 | QA29-who-shoots-and-kills-alexander-zalachenko-in | `ad6aba37-9261-56da-bf3b-713f0cf07851` | 1.000 → 0.950 | -0.050 | 0.500 → 0.500 | 19.9 → 16.9 | 8.50 → 7.43 | changed / changed |
| 30 | QA30-what-false-name-appears-on-the-doorplate-of-l | `8e6b2339-a71e-56d2-9d02-1e079e40f3e4` | 0.950 → 0.950 | +0.000 | 1.000 → 1.000 | 16.3 → 14.9 | 5.45 → 3.89 | changed / changed |
| 31 | QA31-what-academic-mathematics-book-does-lisbeth-s | `02ad392b-b200-58ce-a96d-f7cd57a5a252` | 1.000 → 1.000 | +0.000 | 1.000 → 1.000 | 20.5 → 19.8 | 5.94 → 5.07 | same / changed |
| 32 | QA32-why-did-amazon-women-allegedly-cut-off-one-of | `8becb9a1-f9bc-5dae-8068-628617294f1e` | 0.450 → 0.550 | +0.100 | 0.000 → 0.500 | 29.1 → 38.6 | 5.18 → 3.68 | changed / changed |
| 33 | QA33-what-causes-a-total-solar-eclipse | `b02fc4c3-53b3-5c8d-9e75-ee6c717bb165` | 1.000 → 1.000 | +0.000 | 0.000 → 0.000 | 23.1 → 21.3 | 5.30 → 4.88 | same / changed |
| 34 | QA34-who-painted-the-mona-lisa-and-during-which-c | `05939427-895d-5d1d-a1e8-a022cc60d2c7` | 1.000 → 1.000 | +0.000 | n/a → 1.000 | 16.2 → 16.4 | 2.93 → 2.04 | same / changed |
| 35 | QA35-what-is-the-standard-chemical-formula-for-tab | `08f5075a-61f3-531b-a483-0a11e4c86307` | 1.000 → 1.000 | +0.000 | 1.000 → 1.000 | 18.5 → 18.5 | 1.71 → 1.26 | changed / changed |
| 36 | QA36-what-was-the-nickname-of-mikael | `58343746-a482-480d-b6d4-3e86f468a95c` | 0.917 → 0.933 | +0.017 | 1.000 → 1.000 | 18.0 → 16.5 | 3.95 → 2.86 | changed / changed |

## Artifacts and reproduction

Local artifacts (git-ignored):

- `data/executions/d39a54ec-f72e-4354-9f4e-0cdf115ae5db/` — baseline `request.json`, `manifest.json`, `results.json`
- `data/executions/30a9c2f4-c082-46ca-923d-ee7d9b745929/` — parallel `request.json`, `manifest.json`, `results.json`
- `data/tuning/qa-baseline-clean.log`, `data/tuning/qa-parallel-np3.log`
- `data/tuning/qa-parallel-config.json` (`{"parallel_transformations": true}`)
- `data/tuning/qa_compare.py` — comparison script used for the tables above

Commands:

```bash
# Baseline (Ollama parallel default 1)
docker exec millenium-tuning sh -c 'cd /workspace && python app/experiments.py \
  --dataset QA.csv --variant qa-baseline-clean \
  --dataset-version "2026-10-19T11:21:42.206000+00:00" \
  --correctness-evaluator answer_correctness_v2 --prompt-label production'

# Parallel (systemd: OLLAMA_NUM_PARALLEL=3; context remains 8192)
docker exec millenium-tuning sh -c 'cd /workspace && python app/experiments.py \
  --dataset QA.csv --variant qa-parallel-np3 \
  --dataset-version "2026-10-19T11:21:42.206000+00:00" \
  --correctness-evaluator answer_correctness_v2 --prompt-label production \
  --config /data/tuning/qa-parallel-config.json'
```

After the run, `OLLAMA_NUM_PARALLEL` was removed and Ollama restarted; `OLLAMA_CONTEXT_LENGTH=8192` remains.

## Decision

**Keep `parallel_transformations` off by default.** The mean correctness gain is small and not statistically
significant, and two items regress materially, so the project's zero-regression rule is not met. The toggle remains
available for explicit experiments. A future trial should repeat both arms to separate judge/model noise from the
effect of parallel rewrites.
