# Pipeline v2.12 tool list

Which tools and automatic steps return content, their size, and which precision and recall techniques apply to each.

**Ordered best-first** means the result is a ranked list: rank 1 is the best match, rank 2 the next, and so on.

**Approx. tokens** are rough estimates at the default limits, using about four characters per token. Actual size depends on the text and optional arguments.

## Model tools

| Tool | What it does | What it returns | Size | Approx. tokens | Ordered best-first? | Precision technique | Recall technique |
|---|---|---|---|---|---|---|---|
| `semantic_search` | Searches by meaning | Passages | 5 (max 10) | ~500 (max ~1,100) | ✅ Yes | **P@K** | **Recall@K** (search diagnostics only) |
| `keyword_search` | Searches exact words | Passages | 5 (max 10) | ~500 (max ~1,100) | ✅ Yes | **P@K** | **Recall@K** (search diagnostics only) |
| `search_scenes` | Searches scene summaries | Scenes | 2 (max 5) | ~600 (max ~1,400) | ✅ Yes | **Scene P@K** | **Scene recall@K** (search diagnostics only) |
| `scene_moment` | Picks a scene for a moment | One scene's passages | ≤8 passages + ≤6 summaries | ~1,500–2,000 | ❌ No | **Set precision** | — (use context recall) |
| `true_account` | Finds the real-event scene | Scene passages | ≤2 search + ≤6 scene passages + ≤2 summaries | ~1,000–1,300 | ❌ No | **Set precision** | — (use context recall) |
| `read_passage` | Opens a named passage | Passage + neighbours | 1 passage ±3 neighbours (max 7) | ~650 (max ~1,150) | ❌ No | **Set precision** (debug only) | — |
| `read_scene` | Opens a named scene | Scene passages | ≤6 shown; rest in `more_passages` | ~900 | ❌ No | **Set precision** (debug only) | — |
| `read_chapter` | Opens a chapter | Chapter passages | 8 (max 12) | ~1,100 (max ~1,700) | ❌ No | **Set precision** (debug only) | — |
| `entity_card` | Looks up a person or thing | Facts and links | ≤8 facts + ≤10 links + ≤6 passages | ~1,000 | ❌ No | **Fact precision** | — |
| `find_connections` | Looks up links between people | Facts and edges | ≤6 facts + 4 edges + ≤6 IDs | ~600 | ❌ No | **Fact precision** | — |
| `find_names` | Suggests name spellings | Names | ≤6 matches | ~150 | ❌ No | — | — |
| `expand_query` | Rewrites the question | Queries | 1 HyDE + 3 alternatives + 1 corrected | ~250 | ❌ No | — | — |
| `submit_answer` | Ends the loop | Final answer | 1 answer | ~150 | ❌ No | — | — |

## Automatic retrieval steps

| Step | What it retrieves | Size | Approx. tokens | Precision technique | Recall technique |
|---|---|---|---|---|---|
| `initial scene probe` | Best scene + passages | 1 scene; ≤6 passages | ~900 | **Set precision** | — (use context recall) |
| `connection pre-check` | Connection facts and passages | ≤4 facts, ≤6 IDs each, ≤2 edges | ~300 | **Fact precision** | — |
| `true account pre-check` | True-event evidence | ≤7 passages | ~900 | **Set precision** | — (use context recall) |
| `sequence pre-check` | Scene passages for a place event | ≤8 passages + ≤6 later summaries | ~1,200 | **Set precision** | — (use context recall) |
| `moment pre-check` | Moment keywords and scene rows | ≤5 keyword + ≤6 scene passages + ≤6 summaries | ~2,000–2,500 | **Set precision** | — (use context recall) |
| `premise probe` | Evidence about the question's premise | ≤3 passages | ~700 | **Set precision** | — (use context recall) |

## Measurement techniques

| Technique | Definition | Applies when |
|---|---|---|
| **P@K** | Relevant passages in the top K / K | The tool returns passages ranked best-first |
| **Scene P@K** | Relevant scenes in the top K / K | The tool returns scenes ranked best-first |
| **Set precision** | Relevant passages in the returned set / passages returned | The tool returns a selected set of passages, with no ranking |
| **Fact precision** | Relevant facts in the returned set / facts returned | The tool returns facts rather than passages |
| **Recall@K** | Relevant passages retrieved in the top K / all relevant passages | Ranked passage search; diagnostic only |
| **Scene recall@K** | Relevant scenes retrieved in the top K / all relevant scenes | Ranked scene search; diagnostic only |
| **Context recall** | Reference claims supported by the retrieved context / all reference claims | Measured once over the deduplicated union of passages given to the generator |

**Primary rule:** per-tool recall is a diagnostic for search tools only. The main recall measure is **context recall** over the union of passages the generator received.

**Primary rule:** P@K applies only to ranked passage lists (`semantic_search`, `keyword_search`). Other tools still get set precision, scene P@K, or fact precision where their output supports it.
