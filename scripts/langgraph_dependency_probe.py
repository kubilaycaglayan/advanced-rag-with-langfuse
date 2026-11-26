"""Step 2 isolated dependency/import probe; no models or external graph services.

Run in a disposable app container after installing app/requirements.txt.
"""
import importlib
from importlib.metadata import version
import json
import platform
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class ProbeState(TypedDict):
    count: int


def main():
    for name in ('app.main', 'app.agent.runner', 'app.models.agent', 'app.pipelines.resolver'):
        importlib.import_module(name)
    graph = StateGraph(ProbeState)
    graph.add_node('increment', lambda state: {'count': state['count'] + 1})
    graph.add_edge(START, 'increment')
    graph.add_edge('increment', END)
    result = graph.compile().invoke({'count': 0})
    assert result == {'count': 1}, result
    report = {
        'python': platform.python_version(),
        'versions': {name: version(name) for name in (
            'langgraph', 'langchain-core', 'langgraph-checkpoint', 'langgraph-prebuilt',
            'langgraph-sdk', 'langfuse', 'fastapi', 'pydantic', 'torch',
            'sentence-transformers', 'qdrant-client', 'redis',
        )},
        'app_imports': 'passed', 'minimal_graph_result': result,
        'live_model_calls': 0,
    }
    Path('docs/experiments/langgraph-v2.17-step2/dependency-probe.json').write_text(
        json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
