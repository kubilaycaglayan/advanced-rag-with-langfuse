try:
    from .. import CorpusProfile
except ImportError:
    from corpus_profiles import CorpusProfile

PROFILE = CorpusProfile(
    id="millennium",
    language="en",
    name_pattern=r"[A-ZÅÄÖ][a-zåäöéü]{2,}(?:-[A-ZÅÄÖ][a-zåäöéü]+)?",
    name_word_pattern=r"[A-ZÅÄÖ][a-zåäöéü]+",
    agent_context=("Answer questions about Stieg Larsson's Millennium novels: The Girl with the Dragon Tattoo, "
                   "The Girl Who Played with Fire, and The Girl Who Kicked the Hornet's Nest."),
    translation_exception=("The only exception is a translated form of a name from Stieg Larsson's Millennium "
                           "novels (for example a translated book title or nickname): write it as the English edition does."),
    chapter_reference_pattern=r"^\s*In (?:Chapter \d+(?: of)? )?\*?The Girl[^,]*?,\s*|^\s*In Chapter \d+,\s*",
    prompt_overrides={
        "query_translation_system": (
            "Reply with exactly two lines and nothing else:\n"
            "LANGUAGE: the language the question is written in\n"
            "ENGLISH: the question translated into English (if it is already English, repeat it unchanged)\n"
            "Keep every name of a person, place, company or other entity exactly as written; never translate, respell, "
            "complete or add names. The only exception is a translated form of a name from Stieg Larsson's Millennium "
            "novels (for example a translated book title or nickname): write it as the English edition does. Do not answer "
            "the question."
        )
    },
)
