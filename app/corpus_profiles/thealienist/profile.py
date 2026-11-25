from app.corpus_profiles import CorpusProfile

PROFILE = CorpusProfile(
    id="thealienist",
    language="en",
    name_pattern=r"[A-Z][a-zA-Z’'-]{2,}(?:-[A-Z][a-zA-Z’'-]+)?",
    name_word_pattern=r"[A-Z][a-zA-Z’'-]+",
    prompt_overrides={
        "agent_synthesis_system": (
            "You answer a question about The Alienist using only the supplied evidence passages. Cite each factual "
            "claim with the passage id in square brackets, exactly as given. If the evidence does not state the answer, "
            "say so; do not fill gaps with outside knowledge."
        ),
        "tool_descriptions": {
            "read_chapter": "Browse a chapter of The Alienist: consecutive passages in reading order by chapter number or name.",
        },
        "tool_parameter_descriptions": {
            "read_chapter": {"book": "book title, The Alienist."},
        },
    },
)
