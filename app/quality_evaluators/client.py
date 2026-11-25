"""Project-checked Langfuse access for evaluator configuration."""
import requests
from app.prompt_assets import _api
from app.quality_evaluators.config import configuration


def project_api():
    base, auth = _api()
    response = requests.get(base + '/api/public/projects', auth=auth, timeout=20)
    response.raise_for_status()
    projects = response.json()['data']
    if len(projects) != 1 or projects[0]['name'] != configuration().project:
        raise ValueError('Langfuse credentials do not match the selected corpus project')
    return base, auth


def list_resources(base, auth, resource):
    response = requests.get(base + '/api/public/v2/' + resource,
                            params={'limit': 100}, auth=auth, timeout=20)
    response.raise_for_status()
    rows = response.json()['data']
    if len(rows) >= 100:
        raise ValueError(f'{resource} listing may be truncated; reconciliation refused')
    return rows
