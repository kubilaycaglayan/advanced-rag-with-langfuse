"""Local reference templates used for interactive requests and prompt bootstrap."""
import hashlib

PROMPT_TEMPLATES = {
    "answer_system": ("Answer the user's question using only the evidence passages provided. Do not use outside knowledge or make unsupported claims. "
                      "If evidence is insufficient, say so. Cite each factual claim with labels such as [E1]. Keep the answer concise."),
    "hyde_system": "Write a short passage, in the style of a novel's narration, that could appear in the source text and would answer the question. Use only the names that appear in the question; do not invent names, dates, places, or other specific facts — describe unknown details generically (for example \"her mother\", \"the town\"). No preamble; do not claim access to the source books.",
    "grammar_system": "Correct the grammar and spelling of this question while preserving its meaning and all character and place names. Return only the corrected question, without explanation or an answer.",
    # Index-time only: summaries of consecutive-passage windows used as a second search index (app/scenes.py).
    "scene_summary_system": ("You summarise excerpts of a novel for a search index. Write a factual summary (60-120 words) of what happens in the "
                             "excerpt: name the characters (resolve 'he', 'she', 'you' to the names used in the excerpt), and state concretely what "
                             "they do, say, decide, demand, reveal or learn. Write names exactly as the excerpt does; never add a first name, "
                             "surname, title or description that the excerpt does not give. Use only the excerpt. Output only the summary."),
    "query_translation_system": ("Reply with exactly two lines and nothing else:\n"
                                 "LANGUAGE: the language the question is written in\n"
                                 "ENGLISH: the question translated into English (if it is already English, repeat it unchanged)\n"
                                 "Keep every name of a person, place, company or other entity exactly as written; never translate, respell, "
                                 "complete or add names. The only exception is a translated form of a name from Stieg Larsson's Millennium "
                                 "novels (for example a translated book title or nickname): write it as the English edition does. Do not answer "
                                 "the question."),
    "query_expansion_system": "Generate exactly {{expansion_count}} distinct search queries for finding passages in a novel that answer the question. Preserve the question's intent and keep every name exactly as written in the question; never add names that are not in the question. Each query must be worded differently from the question and from each other: vary the vocabulary (for example synonyms, statements instead of questions, words a narrator or character in the book might use). Do not answer the question. Return one query per line, with no numbering or commentary.",
}
PROMPT_HASHES = {name: hashlib.sha256(value.encode("utf-8")).hexdigest() for name, value in PROMPT_TEMPLATES.items()}
