"""Generate a self-contained HTML review page for the qm_ quality metrics.

Each question page combines the qrels, full passage text, the actual search calls,
the metric scores, and editable notes. Notes autosave in the browser and export as JSON.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from langfuse import Langfuse
from qdrant_client import QdrantClient

try:
    from .quality_metrics import DEFAULT_QRELS, SEARCH_TOOLS, fetch_observations
except ImportError:
    from quality_metrics import DEFAULT_QRELS, SEARCH_TOOLS, fetch_observations

DEFAULT_TRACES = [
    ("QA1", "785e319a-89a1-5950-96cf-f99a23162a87", "a18f003e157b35c8c10e455e5a7b6551"),
    ("QA2", "f59e5c80-b58e-5639-add4-ac587c7a368a", "71822c72bf05f7261aca3d1e60793272"),
    ("QA3", "fb5b6f9d-2a37-5f3b-9f40-e8dd97ca7952", "475ad49e1cf38a0d39b463615bec94d6"),
    ("QA4", "c51aa2b1-bc66-5f9b-a323-23138d35675f", "f76878c7f7100617066bfd2d0378480d"),
    ("QA5", "09543843-b857-5bcd-ac6c-428ac4eb6501", "681a40df59b7ffc609e9cc0254a29f92"),
    ("QA6", "276fb010-6f69-5aef-9593-de095b841537", "960fbf6b3221fe0a6fc5d313c6e41aa2"),
    ("QA7", "9cec0dd1-4ede-5f14-8162-8de3c76938a8", "092d4c3b31447e53d7ca9a3e83605f08"),
    ("QA10", "5491526c-fa73-57bc-98c7-9bfc36fbf9a7", "d2f777675a2311f6f2d7b7439e05e559"),
]
LANGFUSE_URL = "http://127.0.0.1:28420/project/millenium/traces"


def _loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _passage_texts(collection: str, ids: set[str]) -> dict[str, dict[str, Any]]:
    qdrant = QdrantClient(url="http://127.0.0.1:6334", timeout=30)
    rows: dict[str, dict[str, Any]] = {}
    offset = None
    while True:
        batch, offset = qdrant.scroll(collection_name=collection, limit=500, offset=offset, with_payload=True)
        for point in batch:
            short = str(point.id)[:8]
            if short in ids:
                payload = dict(point.payload or {})
                payload["short_id"] = short
                payload["id"] = str(point.id)
                rows[short] = payload
        if offset is None:
            break
    return rows


def _scores(trace_ids: list[str]) -> dict[str, dict[str, float]]:
    if not trace_ids:
        return {}
    quoted = ",".join(f"'{trace_id}'" for trace_id in trace_ids)
    query = ("select trace_id,name,value,observation_id from default.scores FINAL "
             f"where name like 'qm_%' and trace_id in ({quoted}) format TSV")
    try:
        text = subprocess.check_output(
            ["docker", "exec", "langfuse-clickhouse-1", "clickhouse-client", "--query", query],
            text=True, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return {}
    result: dict[str, dict[str, float]] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        trace_id, name, value, observation_id = parts
        if observation_id in ("\\N", ""):
            result.setdefault(trace_id, {})[name] = float(value)
    return result


def _trace_calls(observations: list[Any], texts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    calls = []
    for observation in observations:
        if observation.name not in SEARCH_TOOLS:
            continue
        data = _loads(observation.output)
        if not isinstance(data, dict):
            continue
        hits = []
        for rank, hit in enumerate(data.get("hits") or [], 1):
            if not isinstance(hit, dict):
                continue
            short = str(hit.get("id") or "")[:8]
            source = texts.get(short, {})
            hits.append({"rank": rank, "id": short, "score": hit.get("score"),
                         "text": source.get("text") or hit.get("text") or "",
                         "book": source.get("book") or hit.get("book"),
                         "chapter": source.get("chapter") or hit.get("chapter"),
                         "paragraph": source.get("paragraph") or hit.get("paragraph")})
        calls.append({"observation_id": observation.id, "tool": observation.name,
                      "query": data.get("query") or "", "hits": hits})
    return calls


def build_data(qrels_path: Path, dataset: str, traces: list[tuple[str, str, str]]) -> dict[str, Any]:
    qrels = json.loads(qrels_path.read_text(encoding="utf-8"))
    qrels_items = qrels["datasets"][dataset]
    langfuse = Langfuse()
    observations = {trace_id: fetch_observations(langfuse, trace_id) for _, _, trace_id in traces}
    all_ids = {row["short_id"] for item in qrels_items.values() for row in item["passages"]}
    for obs in observations.values():
        for observation in obs:
            if observation.name not in SEARCH_TOOLS:
                continue
            data = _loads(observation.output)
            if isinstance(data, dict):
                all_ids.update(str(hit.get("id"))[:8] for hit in data.get("hits") or [] if isinstance(hit, dict))
    texts = _passage_texts(qrels["index_collection"], all_ids)
    scores = _scores([trace_id for _, _, trace_id in traces])

    questions = []
    for label, item_id, trace_id in traces:
        item = qrels_items[item_id]
        direct = {row["short_id"] for row in item["passages"] if row["relevance"] == "direct"}
        support = {row["short_id"] for row in item["passages"] if row["relevance"] == "support"}
        calls = _trace_calls(observations[trace_id], texts)
        union = set()
        for call in calls:
            union.update(hit["id"] for hit in call["hits"])
        for call in calls:
            for hit in call["hits"]:
                hit["gold"] = "direct" if hit["id"] in direct else "support" if hit["id"] in support else ""
                for k in (5, 10):
                    if len(call["hits"]) >= k:
                        hit[f"p{k}"] = sum(1 for other in call["hits"][:k] if other["id"] in direct) / k
        gold = []
        for row in item["passages"]:
            source = texts.get(row["short_id"], {})
            gold.append({**row, "text": source.get("text", "")})
        questions.append({
            "label": label, "item_id": item_id, "trace_id": trace_id,
            "url": f"{LANGFUSE_URL}/{trace_id}",
            "question": item["question"], "claims": item["claims"],
            "single_evidence": bool(item.get("single_evidence")),
            "question_type": item.get("question_type"),
            "retrieval_metrics": item.get("retrieval_metrics"),
            "scores": scores.get(trace_id, {}), "gold": gold,
            "missing_direct": sorted(direct - union),
            "calls": calls, "union_count": len(union),
            "direct_count": len(direct), "support_count": len(support),
        })
    return {"generated_for": dataset, "index_collection": qrels["index_collection"],
            "qrels_version": qrels.get("version"), "questions": questions}


def render_html(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload)


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QA quality review · v2.12</title>
<script>(()=>{const forced=new URLSearchParams(location.search).get("theme");const saved=localStorage.getItem("qm-review-theme");const dark=forced?forced==="dark":saved?saved==="dark":matchMedia("(prefers-color-scheme: dark)").matches;document.documentElement.dataset.theme=dark?"dark":"light";})();</script>
<style>
:root{--ink:#231f25;--muted:#6d6469;--bg:#f6f2ea;--card:#fffdf8;--panel:#fbf7ef;--panel-2:#e8dfd2;--input:#fff;--line:#d8cec5;--line-soft:#e7ded4;--header-bg:#231f25;--header-ink:#f6f2ea;--accent:#8c3547;--ok:#2f6b4f;--warn:#9a6a1f;--bad:#9b2c2c;--tag-direct-bg:#eef7f1;--tag-direct-line:#9bc4af;--tag-support-bg:#fdf5e5;--tag-support-line:#e0c58e;--tag-miss-bg:#fceeee;--tag-miss-line:#e2aaa8;--miss-bg:#fceeee;--miss-line:#e2aaa8}
[data-theme="dark"]{--ink:#f1e9e1;--muted:#b9aaa3;--bg:#1b181a;--card:#252124;--panel:#2d272b;--panel-2:#3a3238;--input:#211d20;--line:#4b4047;--line-soft:#3a3137;--header-bg:#111012;--header-ink:#f6f2ea;--accent:#e58b9b;--ok:#8fd3ae;--warn:#e7c37b;--bad:#ff9a96;--tag-direct-bg:#23392e;--tag-direct-line:#4c8064;--tag-support-bg:#3a2f1d;--tag-support-line:#8a6b32;--tag-miss-bg:#3e2325;--tag-miss-line:#8e4a4b;--miss-bg:#3a2326;--miss-line:#7d4345}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{position:sticky;top:0;z-index:10;background:var(--header-bg);color:var(--header-ink);padding:14px 22px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0;font-weight:650}header .sub{font-size:12px;opacity:.75}
button{font:inherit;border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:5px 10px;cursor:pointer}
button:hover{background:var(--panel-2)}button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
#saved{margin-left:auto;font-size:12px;opacity:.8}main{max-width:1180px;margin:0 auto;padding:22px}
.intro{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px;margin-bottom:18px;font-size:13px;color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:0 0 20px;overflow:hidden}
.card h2{margin:0;padding:16px 18px 6px;font-size:19px;line-height:1.3}.meta{padding:0 18px 12px;color:var(--muted);font-size:12px;display:flex;gap:12px;flex-wrap:wrap}
.meta a{color:var(--accent)}.scores{display:flex;gap:8px;flex-wrap:wrap;padding:0 18px 14px}
.score{border:1px solid var(--line);border-radius:7px;padding:5px 9px;font-size:12px;background:var(--panel)}.score b{display:block;font-size:15px}
.claims{padding:0 18px 10px;font-size:13px}.claims ul{margin:4px 0 0;padding-left:20px}
details{border-top:1px solid var(--line);padding:0 18px}summary{cursor:pointer;padding:11px 0;font-weight:650;color:var(--ink)}
table{width:100%;border-collapse:collapse;font-size:13px;margin:4px 0 12px}th,td{border-bottom:1px solid var(--line-soft);padding:7px 6px;vertical-align:top;text-align:left}
th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}td.id{font-family:ui-monospace,monospace;font-size:12px;white-space:nowrap}
.tag{display:inline-block;border-radius:99px;padding:1px 7px;font-size:11px;border:1px solid}.tag.direct{color:var(--ok);border-color:var(--tag-direct-line);background:var(--tag-direct-bg)}.tag.support{color:var(--warn);border-color:var(--tag-support-line);background:var(--tag-support-bg)}.tag.miss{color:var(--bad);border-color:var(--tag-miss-line);background:var(--tag-miss-bg)}
.text{white-space:pre-wrap;max-width:720px}.hit-irrelevant{opacity:.58}.note{width:100%;min-height:34px;font:inherit;font-size:13px;border:1px solid var(--line);border-radius:5px;padding:5px 7px;background:var(--input);color:var(--ink)}
select{font:inherit;font-size:12px;padding:3px 5px;border:1px solid var(--line);border-radius:4px;background:var(--input);color:var(--ink)}
.qnote{display:block;width:100%;min-height:64px;margin:2px 0 8px;font:inherit;font-size:13px;border:1px solid var(--line);border-radius:6px;padding:8px;background:var(--input);color:var(--ink)}
.row-note{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:4px 0}.row-note label{font-size:12px;color:var(--muted)}
.missing{margin:0 18px 12px;padding:8px 10px;border:1px solid var(--miss-line);background:var(--miss-bg);border-radius:6px;font-size:12px}
.missing code{font-family:ui-monospace,monospace}
@media(max-width:760px){.text{max-width:none}th:nth-child(2),td:nth-child(2){display:none}}
</style>
</head>
<body>
<header>
  <div><h1>QA quality review · pipeline v2.12</h1><div class="sub">Qrels + retrieved passages + qm_ scores · direct-only headline</div></div>
  <button class="primary" onclick="exportNotes()">Export notes</button>
  <button onclick="clearNotes()">Clear notes</button>
  <button onclick="toggleTheme()" id="theme">Dark mode</button>
  <span id="saved">notes autosave locally</span>
</header>
<main>
  <div class="intro">
    <b>How to review:</b> check whether each gold passage is really <b>direct</b> or <b>support</b>; mark missing or wrong ones in the notes. For each search call, mark hits that should be <b>direct</b> or <b>support</b>, or <b>irrelevant</b>. Tick <b>single evidence</b> when only one passage is needed. Export notes when done.
  </div>
  <div id="app"></div>
</main>
<script>
const DATA = __DATA__;
const STORAGE = 'qm-review-notes-v1';
let state = JSON.parse(localStorage.getItem(STORAGE) || '{}');
function qstate(q){ return state[q] || (state[q] = {note:'',single:false,gold:{},hits:{}}); }
function esc(v){ return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function fmt(v){ return (v === null || v === undefined) ? '—' : Number(v).toFixed(4).replace(/0+$/,'').replace(/\.$/,''); }
function save(){ localStorage.setItem(STORAGE, JSON.stringify(state)); document.getElementById('saved').textContent = 'saved ' + new Date().toLocaleTimeString(); }
function bind(qid, kind, id, field, el){
  const q = qstate(qid);
  if(kind === 'question'){ if(field === 'single') el.checked = q.single === undefined ? el.dataset.default === 'true' : !!q.single; else el.value = q.note || ''; }
  else if(kind === 'gold'){ const g = q.gold[id] || (q.gold[id] = {}); if(field === 'label') el.value = g.label || el.dataset.default || 'direct'; else el.value = g.note || ''; }
  else { const h = q.hits[id] || (q.hits[id] = {}); if(field === 'label') el.value = h.label || el.dataset.default || 'unknown'; else el.value = h.note || ''; }
  el.addEventListener(kind === 'question' && field === 'single' ? 'change' : 'input', () => {
    if(kind === 'question' && field === 'single') q.single = el.checked;
    else if(kind === 'question') q.note = el.value;
    else if(kind === 'gold'){ const g = q.gold[id] || (q.gold[id] = {}); g[field] = el.value; }
    else { const h = q.hits[id] || (q.hits[id] = {}); h[field] = el.value; }
    save();
  });
}
function tag(label){ return label ? `<span class="tag ${label}">${label}</span>` : '<span class="tag">not gold</span>'; }
function render(){
  const app = document.getElementById('app');
  app.innerHTML = DATA.questions.map(q => {
    const scores = Object.entries(q.scores).filter(([k]) => !k.includes('_at_10') || q.scores[k] != null)
      .map(([k,v]) => `<div class="score">${esc(k.replace('qm_',''))}<b>${fmt(v)}</b></div>`).join('');
    const claims = Object.entries(q.claims).map(([k,v]) => `<li><b>${k}</b> ${esc(v)}</li>`).join('');
    const gold = q.gold.map(g => `<tr>
      <td class="id">${esc(g.short_id)}</td>
      <td>${esc(g.book)}<br><span class="tag">${esc((g.chapter||'no chapter') + ' ¶' + g.paragraph_start + (g.paragraph_end!==g.paragraph_start?'–'+g.paragraph_end:''))}</span></td>
      <td>${tag(g.relevance)}<br><span class="tag">${g.supports.join(', ')}</span></td>
      <td class="text">${esc(g.text || g.quote)}</td>
      <td><select data-kind="gold" data-q="${q.item_id}" data-id="${g.short_id}" data-field="label" data-default="${g.relevance}"></select>
          <input class="note" placeholder="note" data-kind="gold" data-q="${q.item_id}" data-id="${g.short_id}" data-field="note"></td>
    </tr>`).join('');
    const calls = q.calls.map((c, ci) => {
      const hits = c.hits.map(h => `<tr class="${h.gold ? '' : 'hit-irrelevant'}">
        <td class="id">${h.rank}</td><td class="id">${esc(h.id)}</td><td>${h.score == null ? '—' : Number(h.score).toFixed(3)}</td>
        <td>${tag(h.gold)}</td><td class="text">${esc(h.text)}</td>
        <td><select data-kind="hit" data-q="${q.item_id}" data-id="${c.observation_id}:${h.rank}" data-field="label" data-default="${h.gold || 'unknown'}"></select>
            <input class="note" placeholder="note" data-kind="hit" data-q="${q.item_id}" data-id="${c.observation_id}:${h.rank}" data-field="note"></td></tr>`).join('');
      const p5 = c.hits.length >= 5 ? (c.hits.slice(0,5).filter(h=>h.gold==='direct').length/5).toFixed(2) : '—';
      const p10 = c.hits.length >= 10 ? (c.hits.slice(0,10).filter(h=>h.gold==='direct').length/10).toFixed(2) : '—';
      return `<details><summary>${esc(c.tool.replace('tool: ',''))} · “${esc(c.query)}” · P@5 ${p5}${p10!=='—' ? ' · P@10 '+p10 : ''}</summary>
        <table><thead><tr><th>#</th><th>Passage</th><th>Score</th><th>Gold</th><th>Text</th><th>Review</th></tr></thead><tbody>${hits}</tbody></table></details>`;
    }).join('');
    const missing = q.missing_direct.length ? `<div class="missing"><b>Missing direct gold:</b> ${q.missing_direct.map(x=>`<code>${x}</code>`).join(' ')}</div>` : '';
    return `<section class="card"><h2>${esc(q.label)} · ${esc(q.question)}</h2>
      <div class="meta"><span>item <code>${q.item_id}</code></span><a href="${q.url}" target="_blank" rel="noopener">open trace ↗</a>
      ${q.single_evidence ? '<span class="tag direct">single evidence</span>' : ''}
      ${q.question_type === 'broad' ? '<span class="tag support">broad question</span>' : ''}
      <label class="row-note"><input type="checkbox" data-kind="question" data-q="${q.item_id}" data-field="single" data-default="${q.single_evidence}"> single evidence</label></div>
      <div class="scores">${scores}</div>
      <div class="claims"><b>Claims</b><ul>${claims}</ul></div>
      <div style="padding:0 18px 10px"><label><b>Question notes</b><textarea class="qnote" data-kind="question" data-q="${q.item_id}" data-field="note" placeholder="wrong label, missing passage, single-evidence reasoning, judge error…"></textarea></label></div>
      ${missing}
      ${q.question_type === 'broad' ? '<div class="missing" style="border-color:var(--tag-support-line);background:var(--tag-support-bg)"><b>Broad question:</b> retrieval precision/recall are not reliable against a short gold list. Use answer-level evaluation.</div>' : ''}
      ${q.single_evidence ? '<div class="missing" style="border-color:var(--tag-direct-line);background:var(--tag-direct-bg)"><b>Single evidence:</b> use Hit@K, not Precision@K.</div>' : ''}
      <details open><summary>Gold passages · ${q.direct_count} direct / ${q.support_count} support</summary>
        <table><thead><tr><th>ID</th><th>Location</th><th>Label</th><th>Text</th><th>Review</th></tr></thead><tbody>${gold}</tbody></table></details>
      <details><summary>Search calls · ${q.calls.length} calls · ${q.union_count} unique passages</summary>${calls}</details>
    </section>`;
  }).join('');
  document.querySelectorAll('[data-field="label"]').forEach(sel => {
    const options = sel.dataset.kind === 'hit' ? ['unknown','direct','support','irrelevant'] : ['direct','support','remove'];
    sel.innerHTML = options.map(x => `<option value="${x}">${x}</option>`).join('');
    bind(sel.dataset.q, sel.dataset.kind, sel.dataset.id, 'label', sel);
  });
  document.querySelectorAll('[data-field="note"], [data-field="single"]').forEach(el => bind(el.dataset.q, el.dataset.kind, el.dataset.id, el.dataset.field, el));
}
function applyTheme(theme){ document.documentElement.dataset.theme=theme; localStorage.setItem('qm-review-theme',theme); document.getElementById('theme').textContent = theme==='dark' ? 'Light mode' : 'Dark mode'; }
function toggleTheme(){ applyTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'); }
function exportNotes(){
  const out = {version:1, exported_at:new Date().toISOString(), dataset:DATA.generated_for, questions:state};
  const blob = new Blob([JSON.stringify(out,null,2)], {type:'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'qm-review-notes.json'; a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href), 2000);
}
function clearNotes(){ if(confirm('Clear all notes on this page? Export first if you need them.')){ state={}; localStorage.removeItem(STORAGE); render(); document.getElementById('saved').textContent='notes cleared'; } }
render();
applyTheme(document.documentElement.dataset.theme || (localStorage.getItem("qm-review-theme") || "light"));
</script>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qrels", type=Path, default=DEFAULT_QRELS)
    parser.add_argument("--dataset", default="QA.csv")
    parser.add_argument("--output", type=Path,
                        default=Path("data/millennium/quality-reviews/qa1-qa6.html"))
    parser.add_argument("--trace", action="append", default=None,
                        metavar="LABEL:ITEM_ID:TRACE_ID")
    args = parser.parse_args()
    traces = DEFAULT_TRACES
    if args.trace:
        traces = [tuple(item.split(":", 2)) for item in args.trace]
    data = build_data(args.qrels, args.dataset, traces)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_html(data), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
