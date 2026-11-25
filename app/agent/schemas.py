"""agent / schemas responsibilities."""
from __future__ import annotations

from app.corpus_profiles import profile_tool_specs
from typing import Any


def _tool_specs() -> list[dict[str, Any]]:
    def spec(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {"type": "function", "function": {"name": name, "description": description,
                                                 "parameters": {"type": "object", "properties": properties,
                                                                "required": required}}}

    query = {"type": "string", "description": "words to search for"}
    count = {"type": "integer", "description": "how many results (default 5, max 10)"}
    return profile_tool_specs([
        spec("semantic_search", "Dense search over the books' passages; returns the best matches after cross-encoder reranking.",
             {"query": query, "k": count}, ["query"]),
        spec("keyword_search", "BM25 search for the exact content words in a query. Best for a quoted phrase, a nickname or a rare term.",
             {"query": query, "k": count}, ["query"]),
        spec("expand_query", "Ask the books' language model for a hypothetical answer passage, three alternative phrasings and a grammar correction. Search the results with semantic_search.",
             {"query": {"type": "string", "description": "question to expand (default: the user's question)"}}, []),
        spec("search_scenes", "Search summaries of six-passage windows. Use it to find a conversation or an explanation spread over several passages, or dialogue that never names the people. Pass `people` when the question names two people: their full names are added to the query. Each scene carries its scene_id and passage ids; `full` returns every member passage at length.",
             {"query": query, "people": {"type": "array", "items": {"type": "string"}, "description": "people the question names (optional)"},
              "k": {"type": "integer", "description": "how many scenes (default 2, max 5)"},
              "full": {"type": "boolean", "description": "return every member passage at ~500 characters instead of four 110-character snippets (default false)"}}, []),
        spec("read_scene", "Read every member passage of one scene in reading order (~500 characters each). Use the scene_id that search_scenes or true_account returned when the snippet does not contain the detail.",
             {"scene_id": {"type": "string", "description": "8-character scene id"}}, ["scene_id"]),
        spec("scene_moment", "For a question about a detail at one moment (what someone said, wore, noticed or held), write the situation out and let the model choose the scene that shows it; returns that scene's passages. Use it when a search for the question's words finds the right scene but not the detail.",
             {"question": {"type": "string", "description": "the question or the moment (default: the user's question)"}}, []),
        spec("true_account", "After the books give an official account of a death, a crime or a disappearance, find the true account: searches for the other person doing the event ('Harriet drowned her father') and returns the scene and passages that reveal what really happened. Pass who else was there when you know; otherwise the entity cards suggest them.",
             {"person": {"type": "string", "description": "the person the event happened to (or the event's subject)"},
              "event": {"type": "string", "description": "the event verb or words from the question (died, drowned, shot, nail gun, factory); derived from the question when omitted"},
              "other_person": {"type": "string", "description": "who else was there or who did it (optional)"}},
             ["person"]),
        spec("entity_card", "A person's entity card: how the books spell the name, facts about them, and their links to other names and things (aliases, nicknames, belongings). Facts are ranked by the question, or by `about` when given.",
             {"name": {"type": "string", "description": "person or thing name"},
              "about": {"type": "string", "description": "what to rank the facts for (optional; default the question)"}}, ["name"]),
        spec("find_connections", "What links two people: facts and edges that name both (how they met, what one did for the other, documents or names between them), with passages that state an edge. Use it for 'how did X know Y' or 'what connects X and Y'.",
             {"person_a": {"type": "string", "description": "first person"}, "person_b": {"type": "string", "description": "second person"}},
             ["person_a", "person_b"]),
        spec("find_names", "Suggest how the books spell a name, including close misspellings and full names for a first name.",
             {"name": {"type": "string", "description": "name as written in the question"}}, ["name"]),
        spec("read_passage", "Read one passage in full, with the passages before and after it.",
             {"id": {"type": "string", "description": "8-character passage id"},
              "before": {"type": "integer", "description": "passages before (0-3, default 1)"},
              "after": {"type": "integer", "description": "passages after (0-3, default 1)"}}, ["id"]),
        spec("read_chapter", "Browse a chapter: consecutive passages in reading order, by book and chapter number or name.",
             {"book": {"type": "string", "description": "Dragon Tattoo, Played with Fire or Hornet's Nest"},
              "chapter": {"type": "string", "description": "chapter number, e.g. 17"},
              "offset": {"type": "integer", "description": "first paragraph (default 0)"},
              "limit": {"type": "integer", "description": "paragraphs to return (default 8, max 12)"}}, ["book", "chapter"]),
        spec("submit_answer", "Finish: give the final answer and the passages it relies on.",
             {"answer": {"type": "string", "description": "the answer, citing passage ids in square brackets"},
              "passage_ids": {"type": "array", "items": {"type": "string"},
                              "description": "8-character ids of the passages the answer relies on, most important first"}},
             ["answer"]),
    ])


def tool_names() -> list[str]:
    return [spec["function"]["name"] for spec in _tool_specs()]

