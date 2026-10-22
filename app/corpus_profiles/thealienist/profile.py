try:
    from .. import CorpusProfile
except ImportError:
    from corpus_profiles import CorpusProfile

PROFILE = CorpusProfile(
    id="thealienist",
    language="en",
    name_pattern=r"[A-Z][a-zA-Z’'-]{2,}(?:-[A-Z][a-zA-Z’'-]+)?",
    name_word_pattern=r"[A-Z][a-zA-Z’'-]+",
    agent_context="Answer questions about Caleb Carr's novel The Alienist.",
    prompt_overrides={
        "query_translation_system": (
            "Reply with exactly two lines and nothing else:\n"
            "LANGUAGE: the language the question is written in\n"
            "ENGLISH: the question translated into English (if already English, repeat it unchanged)\n"
            "Keep every person, place, organization, and other name exactly as written. Never translate, respell, "
            "complete, or add names. Do not answer the question."
        ),
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
