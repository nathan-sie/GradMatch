"""Load only candidate-accessible execution settings and verified public evidence."""
from dataclasses import dataclass, replace
import hashlib
import json
from gradmatch.catalog import load_seed
from gradmatch.config import ConfigurationError, load_settings
from gradmatch.homework.contracts import tool_contracts
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import data_hash


@dataclass
class Runtime:
    manifest: dict
    programs: list
    sources: dict
    settings: object
    rubric: str
    code_hash: str


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def load_runtime(*,live_model=False):
    manifest=json.loads((PROJECT_ROOT/'homework/experiment.json').read_text(encoding='utf-8'))
    if manifest['data_mode']!='snapshot' or manifest['catalog_path']!='data/catalog/m35_seed.json':
        raise ConfigurationError('Only the frozen snapshot catalog is supported by H2.')
    for path,expected in [(manifest['catalog_path'],manifest['catalog_sha256']),
            (manifest['tier_rubric_path'],manifest['tier_rubric_sha256']),
            ('homework/tool_contracts.json',manifest['files']['homework/tool_contracts.json'])]:
        if sha(PROJECT_ROOT/path)!=expected:raise ConfigurationError('A frozen candidate-accessible artifact changed.')
    if json.loads((PROJECT_ROOT/'homework/tool_contracts.json').read_text(encoding='utf-8'))!=tool_contracts():
        raise ConfigurationError('Tool contracts differ from the H1 freeze.')
    programs,sources=load_seed()
    if data_hash(programs,sources)!=manifest['catalog_data_hash']:
        raise ConfigurationError('Catalog facts differ from the H1 freeze.')
    settings=load_settings()
    if settings.model!=manifest['model']:
        raise ConfigurationError('Configured model differs from the frozen homework model.')
    limits={**settings.limits,'max_model_calls_per_session':manifest['candidate_limits']['max_model_calls_per_task'],
        'model_timeout_seconds':manifest['candidate_limits']['model_timeout_seconds'],
        'max_output_tokens':manifest['candidate_limits']['max_output_tokens_per_call']}
    settings=replace(settings,enabled=settings.enabled and live_model,limits=limits)
    if live_model and not settings.ready:
        raise ConfigurationError('Live calls require the local API key and MODEL_ENABLED=true.')
    raw=(PROJECT_ROOT/manifest['tier_rubric_path']).read_text(encoding='utf-8')
    # Coverage notes belong in retrieved data, not an advance answer hint.
    rubric=raw.split('\nCurrent pilot:')[0]
    paths=['homework/'+name for name in ['contracts.py','models.py','runtime.py','trace.py','tools.py','provider.py','engine.py','prompts.py']]
    paths += ['catalog.py','config.py','constraints.py','providers.py','ranking.py','schemas.py','session.py','storage.py','tiers.py','validation.py']
    code_hash=hashlib.sha256(''.join(name+sha(PROJECT_ROOT/'gradmatch'/name) for name in paths).encode()).hexdigest()
    return Runtime(manifest,programs,sources,settings,rubric,code_hash)
