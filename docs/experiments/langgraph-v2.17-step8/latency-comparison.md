# v2.17 latency comparison against prior pipelines

Compares selected, successfully completed v2.17 Step 8 runs with the frozen Step 1 baseline for the same 10 questions. Previous pipelines are v2.16 or earlier; each exact version and agent model is shown. Latency is recorded query-and-answer duration, excluding evaluator latency. 🛑 marks an increase.

The three Ollama baselines for Q1–Q3 used `qwen3:8b`; the Q4–Q10 baselines used `qwen3.6:35b`. All selected v2.17 Ollama runs used `qwen3.6:35b`. Thus the all-question Ollama mean includes a model change for Q1–Q3; the matched-model mean isolates Q4–Q10. The OpenAI baseline and v2.17 runs all used `gpt-6-luna`. A later qwen3:8b trial was canceled and is excluded.

## OpenAI

| Q | Question | Previous model | Previous pipeline | Before | v2.17 model | Attempt | After | Change |
|---:|---|---|---|---:|---|---|---:|---:|
| 1 | What academic mathematics book does Lisbeth Salander carry around and memorize? 🛑 | `gpt-6-luna` | `derived-v2.16-27074265` | 16.09s | `gpt-6-luna` | `openai-q01-a1` | 18.59s | +2.50s (+15.5%) |
| 2 | Who killed Harriet? | `gpt-6-luna` | `derived-v2.16-27074265` | 18.95s | `gpt-6-luna` | `openai-q02-a1` | 18.24s | -0.71s (-3.7%) |
| 3 | What was the nickname of Mikael? 🛑 | `gpt-6-luna` | `derived-v2.16-27074265` | 15.44s | `gpt-6-luna` | `openai-q03-a1` | 20.26s | +4.82s (+31.2%) |
| 4 | Who are the top 10 most important characters? | `gpt-6-luna` | `derived-v2.16-27074265` | 55.92s | `gpt-6-luna` | `openai-q04-a1` | 51.15s | -4.77s (-8.5%) |
| 5 | How Gottfried really died? | `gpt-6-luna` | `derived-v2.16-27074265` | 43.36s | `gpt-6-luna` | `openai-q05-a1` | 22.70s | -20.66s (-47.6%) |
| 6 | what is the sumary of the first book? 🛑 | `gpt-6-luna` | `derived-v2.16-27074265` | 41.45s | `gpt-6-luna` | `openai-q06-a1` | 49.82s | +8.37s (+20.2%) |
| 7 | What happened to Teleborian in the end of the court? | `gpt-6-luna` | `derived-v2.16-27074265` | 27.84s | `gpt-6-luna` | `openai-q07-a1` | 26.33s | -1.51s (-5.4%) |
| 8 | How Mikale knows that Salander is a hacker? 🛑 | `gpt-6-luna` | `derived-v2.16-27074265` | 19.78s | `gpt-6-luna` | `openai-q08-a3` | 32.95s | +13.17s (+66.6%) |
| 9 | What happened to Salander in the abandoned factory? 🛑 | `gpt-6-luna` | `derived-v2.16-27074265` | 40.53s | `gpt-6-luna` | `openai-q09-a1` | 41.12s | +0.59s (+1.5%) |
| 10 | When Mikael Blomkvist found Lisbeth Salander severely wounded on the kitchen bench at the Gosseberga farmhouse, he reached out to carefully loosen the gun from her hand. And then what Salander said to him? 🛑 | `gpt-6-luna` | `derived-v2.16-27074265` | 14.86s | `gpt-6-luna` | `openai-q10-a2` | 17.72s | +2.86s (+19.2%) |
| **All 10 mean** | **6/10 increased** | — | — | **29.42s** | — | — | **29.89s** | **+0.47s (+1.6%)** |
| **Same-model mean (10 Qs)** | — | — | — | **29.42s** | — | — | **29.89s** | **+0.47s (+1.6%)** |

## Ollama

| Q | Question | Previous model | Previous pipeline | Before | v2.17 model | Attempt | After | Change |
|---:|---|---|---|---:|---|---|---:|---:|
| 1 | What academic mathematics book does Lisbeth Salander carry around and memorize? 🛑 | `qwen3:8b` | `pipeline-v2.2-27213d82` | 33.10s | `qwen3.6:35b` | `ollama-q01-a2` | 33.21s | +0.11s (+0.3%) |
| 2 | Who killed Harriet? 🛑 | `qwen3:8b` | `pipeline-v2.2-27213d82` | 34.30s | `qwen3.6:35b` | `ollama-q02-a1` | 59.88s | +25.58s (+74.6%) |
| 3 | What was the nickname of Mikael? 🛑 | `qwen3:8b` | `pipeline-v2.2-27213d82` | 18.79s | `qwen3.6:35b` | `ollama-q03-a1` | 40.64s | +21.85s (+116.3%) |
| 4 | Who are the top 10 most important characters? 🛑 | `qwen3.6:35b` | `draft-v2.13-8c73b46f` | 45.45s | `qwen3.6:35b` | `ollama-q04-a3` | 106.15s | +60.70s (+133.6%) |
| 5 | How Gottfried really died? | `qwen3.6:35b` | `draft-v2.13-8c73b46f` | 35.39s | `qwen3.6:35b` | `ollama-q05-a1` | 32.78s | -2.61s (-7.4%) |
| 6 | what is the sumary of the first book? 🛑 | `qwen3.6:35b` | `draft-v2.13-8c73b46f` | 75.97s | `qwen3.6:35b` | `ollama-q06-a3` | 153.23s | +77.26s (+101.7%) |
| 7 | What happened to Teleborian in the end of the court? 🛑 | `qwen3.6:35b` | `draft-v2.13-8c73b46f` | 51.06s | `qwen3.6:35b` | `ollama-q07-a1` | 53.35s | +2.29s (+4.5%) |
| 8 | How Mikale knows that Salander is a hacker? 🛑 | `qwen3.6:35b` | `draft-v2.13-8c73b46f` | 20.84s | `qwen3.6:35b` | `ollama-q08-a3` | 21.77s | +0.93s (+4.5%) |
| 9 | What happened to Salander in the abandoned factory? | `qwen3.6:35b` | `pipeline-v2.12-62d121f0` | 97.15s | `qwen3.6:35b` | `ollama-q09-a1` | 72.46s | -24.69s (-25.4%) |
| 10 | When Mikael Blomkvist found Lisbeth Salander severely wounded on the kitchen bench at the Gosseberga farmhouse, he reached out to carefully loosen the gun from her hand. And then what Salander said to him? 🛑 | `qwen3.6:35b` | `pipeline-v2.12-62d121f0` | 53.69s | `qwen3.6:35b` | `ollama-q10-a1` | 54.93s | +1.24s (+2.3%) |
| **All 10 mean** | **8/10 increased** | — | — | **46.57s** | — | — | **62.84s** | **+16.27s (+34.9%)** |
| **Same-model mean (7 Qs)** | — | — | — | **54.22s** | — | — | **70.67s** | **+16.45s (+30.3%)** |

## Summary

| Provider | Same-model questions | All 10 previous → v2.17 mean | Same-model previous → v2.17 mean |
|---|---:|---:|---:|
| OpenAI | 10/10 | 29.42s → 29.89s (+0.47s, +1.6%) | 29.42s → 29.89s (+0.47s, +1.6%) |
| Ollama | 7/10 | 46.57s → 62.84s (+16.27s, +34.9%) | 54.22s → 70.67s (+16.45s, +30.3%) |

Means are arithmetic averages. The all-question comparison answers what happened across the fixed sample; the same-model comparison excludes rows where the baseline and v2.17 used different agent models. This is latency only, not a correctness or release-acceptance assessment.
