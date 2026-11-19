"""Corpus-specific quality evaluation settings; scoring remains shared."""
from dataclasses import dataclass
import json
from pathlib import Path

from app.corpus_config import corpus_config, langfuse_dataset_name, langfuse_evaluator_prefix, langfuse_project


@dataclass(frozen=True)
class QualityConfig:
    corpus: str
    project: str
    prefix: str
    root: Path
    dataset: str
    pipeline: str
    agent_settings: dict
    relevancy_hint: str

    @property
    def qrels(self):
        return self.root / 'retrieval-qrels.json'

    @property
    def observation_name(self):
        return f'{self.corpus} quality measurement'

    def evaluator_name(self, metric):
        return f'{self.prefix}-qm-{metric}'


def configuration():
    corpus = corpus_config()
    path = corpus.root / 'quality-evaluators.json'
    settings = json.loads(path.read_text(encoding='utf-8'))
    return QualityConfig(corpus.id, langfuse_project(), langfuse_evaluator_prefix(), corpus.root,
                         langfuse_dataset_name(), settings['pipeline'], settings.get('agent_settings', {}),
                         settings.get('relevancy_hint', ''))
