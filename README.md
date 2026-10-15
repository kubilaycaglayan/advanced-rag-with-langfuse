# Millennium semantic search

Ask questions about Stieg Larsson's *Millennium* trilogy and find answers grounded in the books. This project searches passages from locally supplied EPUBs, chooses the most relevant evidence, and uses a local language model to write an answer with citations. You can inspect the cited passages and the steps that produced the answer.

The book files are **not included** in this repository. The app builds its search index from EPUBs you place in the local `corpus/` directory.

## How it works

```mermaid
flowchart TD
    user["User query"] --> routes

    subgraph query_pool["1 · Query pool"]
        routes["6 main searches: original + HyDE + 3 alternatives + grammar fix<br/>Optional completed name adds a 7th search"]
        embed["Embed each search locally<br/>multi-qa-MiniLM-L6-cos-v1 · CPU"]
        routes --> embed
    end

    subgraph candidate_pool["2 · Candidate pool"]
        lookup["Qdrant dense semantic search<br/>Up to 100 passages per search · no BM25"]
        fusion["Combine rankings with RRF<br/>Top 30 per main search; keep a wider pool"]
        lookup --> fusion
    end

    subgraph evidence_pool["3 · Evidence pool"]
        rerank["Rerank with local cross-encoder<br/>ms-marco-MiniLM-L-6-v2 · CPU"]
        select["Choose 10 passages, or 15 when evidence is weak<br/>Admit up to 3 strong wider-pool hits"]
        rerank --> select
    end

    embed --> lookup
    fusion --> rerank
    select --> generate["Generate cited answer<br/>qwen3:8b via Ollama · original query + evidence"]
    generate --> output["System output: answer and cited passages shown to user"]
```

For a wider view, download the [standalone pipeline diagram](docs/pipeline-diagram.html) and open it in a browser. To compare visual treatments, open the [diagram style gallery](docs/pipeline-style-gallery.html); it shows six static styles and a step reveal using the same pipeline.

The default `full` mode runs six searches: the original query, one imagined answer passage (HyDE), three alternative phrasings, and one grammar-corrected query. If a short name can be completed from the books, a seventh search contributes to the wider candidate pool without changing the main fusion. All searches use dense embeddings against Qdrant; **BM25 keyword search is not part of the current pipeline**.

The embedding and reranking models run locally on CPU by default. `qwen3:8b` runs through Ollama for the search rewrites and the final answer. When evidence looks weak, the pipeline can admit strong passages from a wider pool and give the answer model more context. Model names and endpoints are configurable; the diagram shows the defaults. The final answer cites the selected passages so you can check the source.

## What Langfuse does here

Langfuse is the project's workspace for **prompts, traces, and experiments**:

- **Prompts:** The instructions for search rewrites and answers are versioned in Langfuse. A run pins the versions it used, so later prompt edits do not change that run's record.
- **Traces:** Each question records its search steps, retrieved passages, reranking, answer, and timing. The web app can show the trace for a question and send a helpfulness rating.
- **Experiments:** A question-and-answer dataset can be run through different pipeline settings. Langfuse links each answer to its trace and scores answer correctness and citation support, making runs easier to compare. Reference answers are used for evaluation, never to generate the answer.

Langfuse helps explain *why* an answer changed when a prompt or search setting changes. The actual book search runs through Qdrant, and the language model calls run through Ollama.

## Explore the project

The Vue web app is for asking questions. The Python API handles indexing, search, answers, and experiment runs. See the [technical guide](TECHNICAL_GUIDE.md) for setup and configuration, the [frontend guide](frontend/README.md) for the UI, and the [improvement log](IMPROVEMENTS.md) for examples of how the pipeline was tuned.
