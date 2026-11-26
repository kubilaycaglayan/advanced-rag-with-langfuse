import json,dataclasses,hashlib,subprocess,urllib.request
from pathlib import Path
from app.pipelines.resolver import resolve
from app.evaluation.specs import evaluator_manifest
out=Path('docs/experiments/langgraph-v2.17-step1/starting-state.json')
runs={}
for provider,overrides in [('ollama',{}),('openai',{'agent_provider':'openai','agent_reasoning_effort':'high'})]:
 r=resolve('v2.16',overrides)
 runs[provider]={**dataclasses.asdict(r),'config':r.config.manifest()}
collection=r.index['collection']
def get(url):
 with urllib.request.urlopen(url,timeout=20) as r:return json.load(r)
models=get('http://127.0.0.1:11434/api/tags')
record={'starting_git_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'git_status':subprocess.check_output(['git','status','--short'],text=True),'resolved_v2_16':runs,'qdrant_collection':get('http://127.0.0.1:6334/collections/'+collection),'ollama_models':[m for m in models['models'] if m['name'] in ['qwen3.6:35b','qwen3:8b']],'current_evaluator_specs':evaluator_manifest(),'protected_handoff_sha256':hashlib.sha256(Path('app/context/agent_final_handoff.py').read_bytes()).hexdigest(),'notes':['Read-only identity capture; no model generation or index creation.','OpenAI identity is the configured model alias gpt-6-luna; immutable provider weight revision is not exposed.']}
out.write_text(json.dumps(record,indent=2,default=str)+'\n')
print(out)
