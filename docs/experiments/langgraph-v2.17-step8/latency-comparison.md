# v2.17 latency comparison against prior pipelines

Compares the selected, successfully completed v2.17 Step 8 run for each of the same 10 questions with its frozen Step 1 baseline. Previous pipelines are all v2.16 or earlier; their exact version is shown per question. Latency is the recorded query-and-answer duration for the same question, excluding evaluator latency. 🛑 marks an increase.

The v2.17 Ollama results below use `qwen3.6:35b`; OpenAI uses the Step 8 OpenAI settings. A later qwen3:8b trial was canceled and is not included. There are 10 completed selected question runs per provider.

## OpenAI

| Q | Question | Previous pipeline | Before | v2.17 attempt | After | Change |
|---:|---|---|---:|---|---:|---:|
| 1 | What academic mathematics book does Lisbeth Salander carry around and memorize? 🛑 | `derived-v2.16-27074265` | 16.09s | `openai-q01-a1` | 18.59s | +2.50s (+15.5%) |
| 2 | Who killed Harriet? | `derived-v2.16-27074265` | 18.95s | `openai-q02-a1` | 18.24s | -0.71s (-3.7%) |
| 3 | What was the nickname of Mikael? 🛑 | `derived-v2.16-27074265` | 15.44s | `openai-q03-a1` | 20.26s | +4.82s (+31.2%) |
| 4 | Who are the top 10 most important characters? | `derived-v2.16-27074265` | 55.92s | `openai-q04-a1` | 51.15s | -4.77s (-8.5%) |
| 5 | How Gottfried really died? | `derived-v2.16-27074265` | 43.36s | `openai-q05-a1` | 22.70s | -20.66s (-47.6%) |
| 6 | what is the sumary of the first book? 🛑 | `derived-v2.16-27074265` | 41.45s | `openai-q06-a1` | 49.82s | +8.37s (+20.2%) |
| 7 | What happened to Teleborian in the end of the court? | `derived-v2.16-27074265` | 27.84s | `openai-q07-a1` | 26.33s | -1.51s (-5.4%) |
| 8 | How Mikale knows that Salander is a hacker? 🛑 | `derived-v2.16-27074265` | 19.78s | `openai-q08-a3` | 32.95s | +13.17s (+66.6%) |
| 9 | What happened to Salander in the abandoned factory? 🛑 | `derived-v2.16-27074265` | 40.53s | `openai-q09-a1` | 41.12s | +0.59s (+1.5%) |
| 10 | When Mikael Blomkvist found Lisbeth Salander severely wounded on the kitchen bench at the Gosseberga farmhouse, he reached out to carefully loosen the gun from her hand. And then what Salander said to him? 🛑 | `derived-v2.16-27074265` | 14.86s | `openai-q10-a2` | 17.72s | +2.86s (+19.2%) |
| **Mean** | **6/10 increased** | — | **29.42s** | — | **29.89s** | **+0.47s (+1.6%)** |

## Ollama

| Q | Question | Model | Previous pipeline | Before | v2.17 attempt | After | Change |
|---:|---|---|---|---:|---|---:|---:|
| 1 | What academic mathematics book does Lisbeth Salander carry around and memorize? 🛑 | `qwen3.6:35b` | `pipeline-v2.2-27213d82` | 33.10s | `ollama-q01-a2` | 33.21s | +0.11s (+0.3%) |
| 2 | Who killed Harriet? 🛑 | `qwen3.6:35b` | `pipeline-v2.2-27213d82` | 34.30s | `ollama-q02-a1` | 59.88s | +25.58s (+74.6%) |
| 3 | What was the nickname of Mikael? 🛑 | `qwen3.6:35b` | `pipeline-v2.2-27213d82` | 18.79s | `ollama-q03-a1` | 40.64s | +21.85s (+116.3%) |
| 4 | Who are the top 10 most important characters? 🛑 | `qwen3.6:35b` | `draft-v2.13-8c73b46f` | 45.45s | `ollama-q04-a3` | 106.15s | +60.70s (+133.6%) |
| 5 | How Gottfried really died? | `qwen3.6:35b` | `draft-v2.13-8c73b46f` | 35.39s | `ollama-q05-a1` | 32.78s | -2.61s (-7.4%) |
| 6 | what is the sumary of the first book? 🛑 | `qwen3.6:35b` | `draft-v2.13-8c73b46f` | 75.97s | `ollama-q06-a3` | 153.23s | +77.26s (+101.7%) |
| 7 | What happened to Teleborian in the end of the court? 🛑 | `qwen3.6:35b` | `draft-v2.13-8c73b46f` | 51.06s | `ollama-q07-a1` | 53.35s | +2.29s (+4.5%) |
| 8 | How Mikale knows that Salander is a hacker? 🛑 | `qwen3.6:35b` | `draft-v2.13-8c73b46f` | 20.84s | `ollama-q08-a3` | 21.77s | +0.93s (+4.5%) |
| 9 | What happened to Salander in the abandoned factory? | `qwen3.6:35b` | `pipeline-v2.12-62d121f0` | 97.15s | `ollama-q09-a1` | 72.46s | -24.69s (-25.4%) |
| 10 | When Mikael Blomkvist found Lisbeth Salander severely wounded on the kitchen bench at the Gosseberga farmhouse, he reached out to carefully loosen the gun from her hand. And then what Salander said to him? 🛑 | `qwen3.6:35b` | `pipeline-v2.12-62d121f0` | 53.69s | `ollama-q10-a1` | 54.93s | +1.24s (+2.3%) |
| **Mean** | **8/10 increased** | — | — | **46.57s** | — | **62.84s** | **+16.27s (+34.9%)** |

## Summary

| Provider | Questions with higher latency | Previous mean | v2.17 mean | Mean change |
|---|---:|---:|---:|---:|
| OpenAI | 6/10 | 29.42s | 29.89s | +0.47s (+1.6%) |
| Ollama | 8/10 | 46.57s | 62.84s | +16.27s (+34.9%) |

Means are arithmetic averages across the 10 matching completed questions, calculated separately for each provider. This is latency only; it does not imply a correctness comparison or an acceptance result.
