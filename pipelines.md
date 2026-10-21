# Query pipeline catalog

```json
{
  "default": "v2.9"
}
```

## Version 1 — fixed RAG

Recorded pre-agent QA baseline flow.

```json
{
  "id": "v1",
  "status": "released",
  "engine": "fixed",
  "flow": [
    {
      "name": "query translation",
      "when": "query_translation enabled, non-baseline mode, and English share below english_word_share"
    },
    {
      "name": "HyDE transformation"
    },
    {
      "name": "query expansion"
    },
    {
      "name": "grammar correction"
    },
    {
      "name": "name completion",
      "when": "name_completion enabled; a matching bare name changes the query"
    },
    {
      "name": "candidate retrieval"
    },
    {
      "name": "RRF candidate merge"
    },
    {
      "name": "cross encoder reranking",
      "when": "always; wider-pool hits are admitted only by score margin"
    },
    {
      "name": "keyword search",
      "when": "keyword_hits enabled, admission threshold set, and non-baseline mode"
    },
    {
      "name": "scene context search",
      "when": "scene_context enabled, scene_margin set, and non-baseline mode"
    },
    {
      "name": "entity names",
      "when": "entity_names enabled and non-baseline mode"
    },
    {
      "name": "entity matrix",
      "when": "entity_matrix enabled, non-baseline mode, and no entity-name hit"
    },
    {
      "name": "scene search",
      "when": "scene_margin set, non-baseline mode, and confidence is sufficient"
    },
    {
      "name": "moment scene search",
      "when": "scene_moment enabled and scene search returned no hits"
    },
    {
      "name": "evidence formatting"
    },
    {
      "name": "answer generation"
    },
    {
      "name": "citation extraction"
    }
  ],
  "agent": null,
  "settings": {
    "answer_thinking": false,
    "candidate_count": 30,
    "english_word_share": 0.6,
    "entity_graph": false,
    "entity_graph_damping": 0.5,
    "entity_graph_facts": 0,
    "entity_graph_max_hits": 2,
    "entity_graph_pool": 30,
    "entity_matrix": true,
    "entity_matrix_max_hits": 8,
    "entity_matrix_similarity": 0.75,
    "entity_names": true,
    "expansion_count": 3,
    "generation": {
      "context_length": 8192,
      "output_budgets": [
        4096,
        8192
      ],
      "temperature": 0.0
    },
    "hyde": true,
    "keyword_hits": 30,
    "keyword_margin": 4.0,
    "keyword_max_hits": 5,
    "keyword_rare_share": null,
    "low_confidence_score": 2.0,
    "low_confidence_top_k": 15,
    "min_passage_chars": 400,
    "name_completion": true,
    "name_completion_hits": 300,
    "parallel_transformations": false,
    "passage_chars": 1200,
    "passage_overlap": 0,
    "query_translation": true,
    "retrieval_mode": "full",
    "rrf_constant": 60,
    "scene_context": true,
    "scene_context_max_hits": 2,
    "scene_context_rank": 3,
    "scene_context_sentences": 2,
    "scene_margin": 1.0,
    "scene_moment": true,
    "scene_search_hits": 10,
    "scene_stride": 3,
    "scene_thinking": false,
    "scene_window": 6,
    "top_k": 10,
    "wide_candidate_count": 100,
    "wide_max_hits": 3,
    "wide_override_margin": 2.0,
    "wide_trigger_score": 3.5
  },
  "prompts": {
    "rag-answer": 1,
    "rag-grammar-correction": 1,
    "rag-hyde": 3,
    "rag-query-expansion": 4,
    "rag-query-translation": 2,
    "rag-scene-moment": 1,
    "rag-scene-select": 1
  },
  "index": {
    "collection": "millennium_books_a7ebc5a988df037cd2ee",
    "corpus_checksum": "d5f87c43d9e3b5cc37e6b0ab2131eadc627450d2c2af6d0f508c6ab83275cf9b"
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
  "notes": "Reference: last default QA baseline 2026-10-19, execution d39a54ec-f72e-4354-9f4e-0cdf115ae5db. Code revision omitted because recorded revision predates these settings. Code-only rules: name completion thresholds, BM25 k1/b, word lists, English share definition, expansion count enforcement, passage join, evidence format, citation regex."
}
```

## Version 2 — agentic

Current agent flow used by the web UI.

```json
{
  "id": "v2",
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
      "when": "cited or submitted answer has passage ids and fewer than two verifications ran"
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
      "when": "timeout, turn budget, or tool budget is reached"
    },
    {
      "name": "coverage rewrite",
      "when": "sequence answer lacks confrontation or three sequence stages"
    },
    {
      "name": "abstention synthesis",
      "when": "answer lacks citations, abstains, or has no passage ids while evidence exists"
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
    "instruction_fingerprint": "e114bc0e9958ce609c6bdc9706eb46cbd00f54f4025a7b7acc77353dba42831d"
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
    "collection": "millennium_books_a7ebc5a988df037cd2ee",
    "corpus_checksum": "d5f87c43d9e3b5cc37e6b0ab2131eadc627450d2c2af6d0f508c6ab83275cf9b"
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
  "notes": "The agent reads listed query and index settings; fixed-flow candidate, RRF, wider pool, keyword admission, context, and entity matrix knobs are unused. Code-only rules: name normalization cutoffs, pre-check regexes, snippet sizes. The instruction fingerprint covers agent.py until an instruction-specific fingerprint is introduced."
}
```


## Version 2.2 — query-aware reranking

```json
{
  "id": "v2.2",
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
      "when": "cited or submitted answer has passage ids and fewer than two verifications ran"
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
      "when": "timeout, turn budget, or tool budget is reached"
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
    "instruction_fingerprint": "b457df458c964b4d225d82d784b73bae7232c68c1c124ac120299a209085ae86",
    "query_aware_reranking": true
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
    "collection": "millennium_books_a7ebc5a988df037cd2ee",
    "corpus_checksum": "d5f87c43d9e3b5cc37e6b0ab2131eadc627450d2c2af6d0f508c6ab83275cf9b"
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
  "notes": "Released reranking-only candidate derived from v2. The target question was How does Lisbeth Salander acquire her massive personal fortune? The change only orders already collected evidence using the question and the queries that retrieved each passage; it adds no searches, evidence expansion, answer injection, or prompt changes."
}
```

## Version 2.3 — OpenAI query agent

Selectable experiment variant; v2.2 remains the default.

```json
{
  "id": "v2.3",
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
      "when": "cited or submitted answer has passage ids and fewer than two verifications ran"
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
      "when": "timeout, turn budget, or tool budget is reached"
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
    "model": "gpt-6-luna",
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
    "instruction_fingerprint": "edfc2ec1fbd340498afc2b139dc14f151a74de825c2d95428fe108a6b77ac720",
    "query_aware_reranking": true,
    "provider": "openai"
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
    "collection": "millennium_books_a7ebc5a988df037cd2ee",
    "corpus_checksum": "d5f87c43d9e3b5cc37e6b0ab2131eadc627450d2c2af6d0f508c6ab83275cf9b"
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
  "notes": "Experimental OpenAI query-agent variant based on v2.2. Only the query agent model changes; v2.2 remains the catalog default. The agent uses GPT-6 Luna through OpenAI Chat Completions with reasoning_effort=none. OpenAI errors fail the run without local-model fallback. The configured local generation model remains responsible for expand_query transformations; the fixed pipeline, scene summaries, and evaluators remain local/configured. Token usage and estimated OpenAI API cost are recorded per generation and in experiment outputs. Experiment records: docs/experiments/2026-10-21-v2.3-gpt-6-luna-low-score-eval.md and docs/experiments/2026-10-21-v2.3-gpt-6-luna-four-datasets-comparison-experiment-results.md. Claude Haiku 5.5 (claude-haiku-5-5) is recorded as an Anthropic model to consider for future experiments."
}
```

## Version 2.4 — expanded agent scene search (draft)

```json
{
  "id": "v2.4",
  "status": "draft",
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
      "when": "cited or submitted answer has passage ids and fewer than two verifications ran"
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
      "when": "timeout, turn budget, or tool budget is reached"
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
    },
    {
      "name": "expanded scene candidate pool",
      "when": "search_scenes reranks 100 scene summaries before returning up to five"
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
    "instruction_fingerprint": "4f3c86b9ec0ebe2f76328df25168cc4900e9ad6ecb8626c67780df12163042a8",
    "query_aware_reranking": true,
    "scene_candidate_count": 100
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
    "collection": "millennium_books_a7ebc5a988df037cd2ee",
    "corpus_checksum": "d5f87c43d9e3b5cc37e6b0ab2131eadc627450d2c2af6d0f508c6ab83275cf9b"
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
  "notes": "Draft trial of the v2.2 default for item 3fc5cd25-8333-56d6-8c81-136571fc84fe. Only search_scenes candidate retrieval changes from 20 to 100 before cross-encoder reranking; the query agent, tools, returned scene count, models, index, and default remain v2.2 settings. One-item experiment f769560b-6913-460a-85ca-1a54fd149db2 scored 0.0: the agent made no search_scenes call, so this change was not exercised in that run."
}
```

## Version 2.5 — 30-candidate automatic scene probe (draft)

```json
{
  "id": "v2.5",
  "status": "draft",
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
      "name": "sequence pre-check",
      "when": "always checks the question; gathers sequence facts for a place event"
    },
    {
      "name": "moment pre-check",
      "when": "always checks the question; gathers moment facts for a detail cue"
    },
    {
      "name": "initial scene probe",
      "when": "before the agent starts, rerank 30 scene summaries for the original question and show the best scene source passages"
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
      "when": "cited or submitted answer has passage ids and fewer than two verifications ran"
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
      "when": "timeout, turn budget, or tool budget is reached"
    },
    {
      "name": "coverage rewrite",
      "when": "sequence answer lacks confrontation or three sequence stages"
    },
    {
      "name": "abstention synthesis",
      "when": "answer lacks citations, abstains, or has no passage ids while evidence exists"
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
    "instruction_fingerprint": "4f3c86b9ec0ebe2f76328df25168cc4900e9ad6ecb8626c67780df12163042a8",
    "scene_candidate_count": 30,
    "initial_scene_probe": true
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
    "collection": "millennium_books_a7ebc5a988df037cd2ee",
    "corpus_checksum": "d5f87c43d9e3b5cc37e6b0ab2131eadc627450d2c2af6d0f508c6ab83275cf9b"
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
  "notes": "Current draft based on released v2.2: automatically search scene summaries for the original normalized question, rerank 30 candidates, and supply the best scene source passages to the agent. The same 30-candidate pool applies to agent-initiated search_scenes. v2.2 remains the default. Earlier v2.5 draft trials used 100 candidates; their manifests preserve that setting and fingerprint: gift execution 32e6b973-9497-4f4e-a403-6be9292eae76, three-item execution 7ab4c409-ce32-454d-8cf3-8381fd68ab3c, and 15-item execution ec0c242f-2a9a-4024-90ad-cace3b5ab660. The 30-candidate trials were recorded under temporary draft id v2.51: gift execution 1fb043fd-3b33-42b6-8059-c2aa2c06b920 answered correctly in 19.87 seconds; three-item execution 8bf0d63a-5950-41f4-99ee-e705d2dd7d56 scored mean answer_correctness_v2=0.6667 and mean agent latency=34.66 seconds, versus 100-candidate v2.5 at 0.9917 and 32.37 seconds. All three probes selected the same scene. The Zalachenko question regressed to an incorrect abstention after answer synthesis replaced a draft that named Gullberg. These are single-run comparisons and do not establish a latency gain from the smaller pool."
}
```

## Version 2.6 — selectable OpenAI agent and automatic scene probe

```json
{
  "id": "v2.6",
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
      "when": "cited or submitted answer has passage ids and fewer than two verifications ran"
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
      "when": "timeout, turn budget, or tool budget is reached"
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
    "instruction_fingerprint": "4f3c86b9ec0ebe2f76328df25168cc4900e9ad6ecb8626c67780df12163042a8",
    "query_aware_reranking": true,
    "provider": "ollama",
    "scene_candidate_count": 20,
    "initial_scene_probe": false
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
    "collection": "millennium_books_a7ebc5a988df037cd2ee",
    "corpus_checksum": "d5f87c43d9e3b5cc37e6b0ab2131eadc627450d2c2af6d0f508c6ab83275cf9b"
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
  "notes": "Behavior matches v2.2 by default: local qwen3.6:35b query agent, automatic_scene_search disabled, 20 scene candidates, and the same flow, tools, retrieval settings, index and configured local answer generation. For a derived run, settings may set agent_provider to openai (GPT-6 Luna) and/or automatic_scene_search to true. Enabling automatic_scene_search uses 30 scene candidates by default, matching the successful v2.5 automatic-probe trials; scene_candidate_count can be set explicitly from 1 to 100. OpenAI query-agent errors fail the run without local fallback; the answer generation model remains local/configured."
}
```

## Version 2.7 — corpus-portable agent flow

The v2.6 agent flow and shared settings, resolved against the active corpus profile and index.

```json
{
  "id": "v2.7",
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
      "when": "cited or submitted answer has passage ids and fewer than two verifications ran"
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
      "when": "timeout, turn budget, or tool budget is reached"
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
    "instruction_fingerprint": "4f3c86b9ec0ebe2f76328df25168cc4900e9ad6ecb8626c67780df12163042a8",
    "query_aware_reranking": true,
    "provider": "ollama",
    "scene_candidate_count": 20,
    "initial_scene_probe": false
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
  "notes": "Corpus-portable release based on v2.6. It uses the active corpus profile and index; the resolved corpus checksum, profile identity, prompt identity and isolated collection are recorded per run."
}
```


## Version 2.8 — traced intermediate cache layers

```json
{
  "id": "v2.8",
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
      "when": "cited or submitted answer has passage ids and fewer than two verifications ran"
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
      "when": "timeout, turn budget, or tool budget is reached"
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
    "instruction_fingerprint": "4d81b07d162e3358b99e98c92566fe2ef759f85f4ffc53f7fd3f9fd24c27e4dd",
    "query_aware_reranking": true,
    "provider": "ollama",
    "scene_candidate_count": 20,
    "initial_scene_probe": false
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
  "notes": "Cache-enabled release based on v2.7. Adds request-scoped query, embedding, search, rerank, and tool-read cache layers; cache keys include the resolved pipeline, corpus, prompt, model, and index identities. Cache controls remain request-scoped."
}
```


## Version 2.9 — synthesis reranking trace

```json
{
  "id": "v2.9",
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
      "when": "cited or submitted answer has passage ids and fewer than two verifications ran"
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
      "when": "timeout, turn budget, or tool budget is reached"
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
    "instruction_fingerprint": "c6107149ca30f57fd92010299ce84e99d96fbe34817a7123e221b635dac71159",
    "query_aware_reranking": true,
    "provider": "ollama",
    "scene_candidate_count": 20,
    "initial_scene_probe": false
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
  "notes": "Cache-layer tracing release based on v2.8. Adds an explicit Langfuse span around query-aware synthesis evidence reranking; retrieval and answer behavior are unchanged."
}
```
