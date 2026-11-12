function evaluate({observation: {input}}) {
  if (!input || !Array.isArray(input.direct_gold_ids) || !Array.isArray(input.search_calls) || !Array.isArray(input.union_passage_ids)) {
    throw new Error('Expected direct_gold_ids, search_calls and union_passage_ids');
  }
  if (input.question_type === 'broad') return {scores: []};
  const gold = new Set(input.direct_gold_ids);
  if (!gold.size) throw new Error('Direct gold labels are required');
  const single = input.single_evidence === true;
  const scores = [];
  for (const k of [5, 10]) {
    const values = input.search_calls.filter(c => ['tool: semantic_search', 'tool: keyword_search'].includes(c.tool) && c.hit_ids.length >= k).map(c => {
      const found = c.hit_ids.slice(0, k).filter(id => gold.has(id)).length;
      return single ? Number(found > 0) : found / k;
    });
    if (values.length) scores.push({name: `qm_${single ? 'hit' : 'precision'}_retrieval_at_${k}`, value: values.reduce((a,b) => a+b, 0) / values.length, dataType: 'NUMERIC'});
  }
  if (!single) {
    const union = new Set(input.union_passage_ids);
    const found = [...union].filter(id => gold.has(id)).length;
    if (union.size) scores.push({name: 'qm_precision_retrieval_set', value: found / union.size, dataType: 'NUMERIC'});
    scores.push({name: 'qm_recall_retrieval_context', value: found / gold.size, dataType: 'NUMERIC'});
  }
  return {scores};
}
