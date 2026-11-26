"""Select an execution backend without registering or relabeling a release."""
from pathlib import Path

from app.identity import source_manifest
from app.settings_definitions import AgentSettings, TargetAgentSettings


def execution_backend(resolved):
    backend = getattr(resolved, 'execution_backend', 'legacy')
    if backend not in ('legacy', 'langgraph'):
        raise ValueError(f'unsupported execution backend {backend!r}')
    if backend == 'langgraph':
        if resolved.version != 'v2.17' or not isinstance(resolved.agent_settings, TargetAgentSettings) or isinstance(resolved.agent_settings, AgentSettings):
            raise ValueError('graph execution requires v2.17 identity and target settings')
    elif isinstance(resolved.agent_settings, TargetAgentSettings) and not isinstance(resolved.agent_settings, AgentSettings):
        raise ValueError('target settings cannot execute under the legacy backend')
    return backend


def execution_identity(resolved, source_fingerprint=None):
    if execution_backend(resolved) == 'legacy':
        return None
    if source_fingerprint is None:
        source_fingerprint = source_manifest(str(Path(__file__).resolve().parents[2]))['source_fingerprint']
    from app.agent.instructions import target_instruction_fingerprint
    return {'backend': 'langgraph', 'instruction_fingerprint': target_instruction_fingerprint(),
            'source_fingerprint': source_fingerprint}
