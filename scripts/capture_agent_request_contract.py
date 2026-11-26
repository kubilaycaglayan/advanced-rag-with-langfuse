"""Capture synthetic HTTP request contracts without calling a provider.

Used against the Step 2 checkout to freeze request bytes before centralization.
The fixture contains hashes rather than long, repetitive synthetic passage text.
"""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

from app.agent.state import AgentSettings
from app.agent.schemas import _tool_specs
from app.models.agent import _agent_chat


def request_contract():
    result = {}
    for provider, effort in [('ollama', 'none'), ('openai', 'none'), ('openai', 'high')]:
        for with_tools in (True, False):
            messages = [{'role': 'system', 'content': 'System'}, {'role': 'user', 'content': 'Question'}]
            for index in range(10):
                messages.append({'role': 'assistant', 'content': '', 'tool_calls': [{
                    'id': f'call_{index}', 'function': {'name': 'semantic_search', 'arguments': {'query': f'q{index}'}}}]})
                messages.append({'role': 'tool', 'tool_call_id': f'call_{index}',
                                 'content': json.dumps({'id': f'{index:08x}', 'text': 'x' * 3000})})
            tools = _tool_specs() if with_tools else None
            captured = {}
            def post(url, **kwargs):
                captured.update(url=url, payload=deepcopy(kwargs['json']), timeout=kwargs['timeout'])
                return SimpleNamespace(ok=True, raise_for_status=lambda: None, json=lambda: {})
            settings = AgentSettings(provider=provider, model='local' if provider == 'ollama' else 'gpt-6-luna',
                                     reasoning_effort=effort)
            with patch('app.models.agent.requests.post', side_effect=post), patch.dict('os.environ', {
                    'OPENAI_API_KEY': 'synthetic-only', 'OLLAMA_URL': 'http://example.invalid'}):
                _agent_chat(messages, tools, settings)
            encoded = json.dumps(captured['payload'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            result[f'{provider}/{effort}/tools={with_tools}'] = {
                'url': captured['url'], 'timeout': list(captured['timeout']),
                'payload_sha256': hashlib.sha256(encoded).hexdigest(), 'payload_bytes': len(encoded),
                'compacted_results': sum('"compacted": true' in m.get('content', '') for m in messages),
            }
    return result


if __name__ == '__main__':
    print(json.dumps(request_contract(), indent=2))
