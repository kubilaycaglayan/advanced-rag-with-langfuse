# v2.17 Ollama agent model comparison: qwen3:8b

Runs the same 10 fixed Step 1 question/provider items used for Step 8, with the answer agent explicitly set to `qwen3:8b`. The v2.17 pipeline, Ollama provider, fresh generation (`cache_mode=bypass`), dataset item IDs, and experiment container setup match Step 8. Runs are isolated from `langgraph-v2.17-step8` so those results remain unchanged.

Each item is run and reviewed serially. Retain all attempts; use up to three attempts per item when diagnosing a regression. Compare selected answers, correctness, and each selected run's own latency to the frozen Step 1 Ollama baseline and the selected `qwen3.6:35b` Step 8 result. No aggregate Step 9 acceptance or live-default change is part of this comparison.
