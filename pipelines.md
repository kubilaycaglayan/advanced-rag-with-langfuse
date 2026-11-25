# Pipeline catalog

Only v2.16 is supported. Historical definitions remain in Git history.

```json
{
  "default": "v2.16"
}
```

## Version 2.16 — conversation handoff

```json
{
  "id": "v2.16",
  "status": "released",
  "engine": "agent",
  "flow": [
    {
      "name": "connection pre-check",
      "when": "always checks the question; gathers facts for a connection cue"
    },
    {
      "name": "true account pre-check",
      "when": "always checks the question; gathers facts for a death or crime cue"
    },
    {
      "name": "premise probe",
      "when": "for questions that presume a killing, retrieves direct survival evidence"
    },
    {
      "name": "direct premise resolution",
      "when": "premise_early_stop is enabled and a passage directly confirms the supposed victim is alive"
    },
    {
      "name": "sequence pre-check",
      "when": "always checks the question; gathers sequence facts for a place event"
    },
    {
      "name": "moment pre-check",
      "when": "always checks the question; gathers moment facts for a detail cue"
    },
    {
      "name": "minimum tool nudge",
      "when": "reply has no tool calls and tool count is below minimum"
    },
    {
      "name": "coverage check",
      "when": "reply has no tool calls and evidence exists"
    },
    {
      "name": "submission verification",
      "when": "cited or submitted answer has passage ids; v2.11 verifies each submission"
    },
    {
      "name": "no tool nudge",
      "when": "reply has no usable citation ids and fewer than two nudges ran"
    },
    {
      "name": "name check message",
      "when": "find_names returns a likely spelling not yet resolved"
    },
    {
      "name": "forced answer",
      "when": "timeout, turn budget, or tool budget is reached; answer from the compacted agent conversation without tools"
    },
    {
      "name": "search progress check",
      "when": "a search repeats a hypothesis with little new evidence"
    },
    {
      "name": "coverage rewrite",
      "when": "sequence answer lacks confrontation or three sequence stages"
    },
    {
      "name": "abstention synthesis",
      "when": "answer lacks citations, abstains, or has no passage ids while evidence exists"
    },
    {
      "name": "query-aware evidence reranking",
      "when": "reranks synthesis evidence using question and retrieval queries attached to evidence"
    }
  ],
  "agent": {
    "model": "qwen3.6:35b",
    "tools": [
      "semantic_search",
      "keyword_search",
      "expand_query",
      "search_scenes",
      "read_scene",
      "scene_moment",
      "true_account",
      "entity_card",
      "find_connections",
      "find_names",
      "read_passage",
      "read_chapter",
      "submit_answer"
    ],
    "max_turns": 10,
    "max_tool_calls": 16,
    "min_tool_calls": 4,
    "timeout_seconds": 900.0,
    "context_length": 16384,
    "num_predict": 1600,
    "think": false,
    "snippet_chars": 300,
    "instruction_fingerprint": "8509364e19da56c20f5df1215a2884a76e05763e1fceeb9b778c86fd7436cebc",
    "query_aware_reranking": true,
    "provider": "ollama",
    "scene_candidate_count": 30,
    "initial_scene_probe": true,
    "progress_control": true,
    "premise_early_stop": false,
    "conversation_handoff": true,
    "conversation_handoff_fingerprint": "c418d9c241c3e7c049465c1de926ca911c810af96a2082e8077bce0c4b4123e6"
  },
  "settings": {
    "retrieval_mode": "full",
    "hyde": true,
    "expansion_count": 3,
    "name_completion": true,
    "scene_search_hits": 10,
    "scene_window": 6,
    "scene_stride": 3,
    "passage_chars": 1200,
    "min_passage_chars": 400,
    "passage_overlap": 0,
    "generation": {
      "temperature": 0.0,
      "context_length": 8192,
      "output_budgets": [
        4096,
        8192
      ]
    },
    "parallel_transformations": false,
    "scene_thinking": false
  },
  "prompts": {},
  "index": {
    "collection": null,
    "corpus_checksum": null
  },
  "models": {
    "embedding_model": {
      "name": "sentence-transformers/multi-qa-MiniLM-L6-cos-v1",
      "revision": "b207367332321f8e44f96e224ef15bc607f4dbf0"
    },
    "reranker_model": {
      "name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
      "revision": "233902d25c440f23af6f7d6e94d2946bac0bee0a"
    },
    "generation_model": {
      "digest": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41",
      "name": "qwen3:8b",
      "revision": null
    },
    "scene_summary_model": {
      "digest": null,
      "name": "gemma4:26b",
      "revision": null
    }
  },
  "notes": "Released based on v2.15. On timeout, turn budget, or tool budget, generate the answer from the compacted agent conversation instead of a separately selected evidence digest. Earlier tool results may still be compacted."
}
```

## Maintenance identity

The November 2026 cleanup retains v2.16 behavior and migrates its instruction
protection from all source-file string literals to an explicit instruction
manifest: current system/synthesis prompts, tool schemas, transformation
templates, and named message-building helpers. The instruction and catalog
checksums change deliberately; historical manifests are not rewritten.
Source fingerprints and Git revisions distinguish maintenance revisions.
Conversation handoff retains its separate byte-level fingerprint.
