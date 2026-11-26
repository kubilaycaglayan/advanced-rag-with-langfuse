"""Apply only the approved factory rubric and rescore three saved answers, serially."""
import argparse
import hashlib
import json
from pathlib import Path
from app.answer_facts import plan
from app.evaluation.judges import correctness
from app.evaluation.specs import ANSWER_CORRECTNESS_V2
from app.prompt_assets import ManagedJudgePrompt, load_managed_evaluators
from app.experiments.telemetry import _client, _flush_client

ITEM = '36c50723-3b65-49f6-9d9b-70574cc9471c'
folder = Path('docs/experiments/langgraph-v2.17-step8')
parser=argparse.ArgumentParser()
parser.add_argument('--revision', default='v2')
a=parser.parse_args()
artifact = folder/f'factory-rubric-rescore-{a.revision}.json'
if artifact.exists():
    raise SystemExit('Rescore already exists; inspect rather than overwrite')
facts = json.loads(Path('corpora/millennium/answer-facts.json').read_text())
scoped = {**facts, 'datasets': {'Additional Questions': {ITEM: facts['datasets']['Additional Questions'][ITEM]}}}
client = _client()
def snapshot():
    return {i.id: {'input':i.input, 'expected_output':i.expected_output, 'metadata':i.metadata}
            for i in client.get_dataset('Additional Questions').items}
before = snapshot()
changes = plan(client, scoped)
assert len(changes) == 1 and changes[0]['id'] == ITEM
client.create_dataset_item(**changes[0])
after = snapshot()
assert before.keys() == after.keys()
assert [key for key in before if before[key] != after[key]] == [ITEM]
expected = after[ITEM]['expected_output']
managed = load_managed_evaluators()[ANSWER_CORRECTNESS_V2.name]
rubric_hash = hashlib.sha256(json.dumps(expected,sort_keys=True).encode()).hexdigest()
state = {'item_id':ITEM,'changed_live_item_ids':[ITEM], 'expected_output_before':before[ITEM]['expected_output'],
         'expected_output_after':expected,'rubric_sha256':rubric_hash,'managed_evaluator':managed,
         'other_live_items_unchanged':True,'attempts':[]}
artifact.write_text(json.dumps(state,indent=2,default=str)+'\n')
for attempt in range(1,4):
    label=f'openai-q09-a{attempt}'
    result=json.loads((folder/label/'results.json').read_text())
    item,=result['item_results']
    score=correctness(input=after[ITEM]['input'],output=item['output'],expected_output=expected,
        spec=ANSWER_CORRECTNESS_V2,evaluator_id='factory-rubric-'+rubric_hash,
        langfuse_client=client,managed_prompt=ManagedJudgePrompt(managed),
        evaluator_version=managed['version'],managed_evaluator_id=managed['id'])
    assert score['name']==ANSWER_CORRECTNESS_V2.name, score
    row={'label':label,'original_correctness':item['correctness_score'],'evaluation':score,
         'latency_seconds':item['output']['latency_seconds'],'source_trace_id':item['trace_id'],
         'source_execution_id':result['execution_id']}
    state['attempts'].append(row)
    client.create_score(trace_id=item['trace_id'],name='answer_correctness_v2_factory_rubric',
        value=score['value'],comment=score.get('comment'),metadata={**score['metadata'],'rubric_sha256':rubric_hash,
        'source_execution_id':result['execution_id'],'rescore_only':True})
    artifact.write_text(json.dumps(state,indent=2,default=str)+'\n')
    print(json.dumps(row,indent=2),flush=True)
state['telemetry_flush']=_flush_client(client)
artifact.write_text(json.dumps(state,indent=2,default=str)+'\n')
