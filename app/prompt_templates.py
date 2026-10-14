"""Local reference templates used for interactive requests and prompt bootstrap."""
import hashlib

PROMPT_TEMPLATES = {
    "answer_system": ("Answer the user's question using only the evidence passages provided. Do not use outside knowledge or make unsupported claims. "
                      "If evidence is insufficient, say so. Cite each factual claim with labels such as [E1]. Keep the answer concise."),
    "hyde_system": "Write a concise hypothetical answer to help retrieve relevant passages. No preamble; do not claim access to the source books.",
    "query_expansion_system": "Generate exactly three distinct search queries preserving intent with varied literary phrasing. Return one per line, no numbering or commentary.",
}
PROMPT_HASHES = {name: hashlib.sha256(value.encode("utf-8")).hexdigest() for name, value in PROMPT_TEMPLATES.items()}
