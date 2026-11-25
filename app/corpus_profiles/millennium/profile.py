from app.corpus_profiles import CorpusProfile

PROFILE = CorpusProfile(
    id="millennium",
    language="en",
    name_pattern=r"[A-ZÅÄÖ][a-zåäöéü]{2,}(?:-[A-ZÅÄÖ][a-zåäöéü]+)?",
    name_word_pattern=r"[A-ZÅÄÖ][a-zåäöéü]+",
    chapter_reference_pattern=r"^\s*In (?:Chapter \d+(?: of)? )?\*?The Girl[^,]*?,\s*|^\s*In Chapter \d+,\s*",
)
