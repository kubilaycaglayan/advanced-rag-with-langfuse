# v2.17 Step 8 — serial live validation

In progress. Starting revision: c107e224fe310218c4c726f2798a1104b30694cd.

Uses the frozen Step 1 sample and provider-specific recorded item results. OpenAI settings select high reasoning as frozen; Ollama retains the catalog settings. Every invocation selects exactly one item, explicit v2.17 and cache bypass in the Step 2 isolated Python 3.12 app image. The repository/Git mounts and safe-directory configuration follow AGENTS.md. The live application and default pipeline remain unchanged.

The first run is OpenAI question 1, the frozen mathematics-book smoke check. Each completed run must be reviewed before advancing; retain all attempts and allow at most two additional diagnostic attempts for a regressed item. Correctness and latency must refer to the same selected attempt. Step 9 aggregate acceptance and release are outside this work.
