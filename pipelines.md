# Query pipeline catalog

```json
{"default": "v2.2"}
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
