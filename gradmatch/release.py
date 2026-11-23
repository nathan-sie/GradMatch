"""Refresh catalog-view modules after a hosted hot update without clearing sessions."""

import hashlib
import importlib
from pathlib import Path
import sys
from threading import Lock


_ROOT = Path(__file__).resolve().parent.parent
RELEASE_REFRESH_VERSION = 16
_MODULES = ("gradmatch.coursework", "gradmatch.constraints", "gradmatch.catalog", "gradmatch.bootstrap",
            "gradmatch.tiers", "gradmatch.catalog_audit", "gradmatch.community", "gradmatch.directory", "gradmatch.broad_catalog", "gradmatch.ui_directory",
            "gradmatch.program_questions", "gradmatch.ui_m1", "gradmatch.ui_m2")
_ENGINE_MODULES = ('gradmatch.ranking', 'gradmatch.agent_models', 'gradmatch.validation', 'gradmatch.admission_history',
                   'gradmatch.service', 'gradmatch.agent', 'gradmatch.planning')
_ENGINE_VERSIONS = {'gradmatch.ranking': 2, 'gradmatch.admission_history': 4,
                    'gradmatch.service': 6, 'gradmatch.agent': 10, 'gradmatch.planning': 3}
_LOCK = Lock()
_signature = None


def refresh_catalog_modules():
    """Reload only stateless catalog/view code when its published files change.

    Streamlit may rerun app.py while cached imports still refer to an older seed.
    Keep applicant state, provider clients and task counters outside this refresh.
    """
    global _signature
    paths = [_ROOT / (name.replace(".", "/") + ".py") for name in _MODULES]
    paths.extend(_ROOT / (name.replace('.', '/') + '.py') for name in _ENGINE_MODULES)
    paths.append(_ROOT / "data/catalog/active.json")
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(_ROOT)).encode())
        digest.update(path.read_bytes() if path.exists() else b"missing")
    signature = digest.hexdigest()
    with _LOCK:
        if signature == _signature:
            return
        importlib.invalidate_caches()
        # Upgrade stale engine imports once; never reload Session or provider classes.
        for name in _ENGINE_MODULES:
            module = sys.modules.get(name)
            minimum_version = _ENGINE_VERSIONS.get(name, 1)
            if module is not None and getattr(module, 'BROAD_ENGINE_VERSION', 0) < minimum_version:
                importlib.reload(module)
        for name in _MODULES:
            if name in sys.modules:
                importlib.reload(sys.modules[name])
        provider = sys.modules.get('gradmatch.providers')
        if provider is not None:
            from gradmatch.broad_catalog import install_provider_instructions
            install_provider_instructions(provider.INSTRUCTIONS)
        # Expand accepted explicit patches in place; do not recreate Session or its classes.
        session = sys.modules.get('gradmatch.session')
        if session is not None:
            coursework = importlib.import_module('gradmatch.coursework')
            session.TOPICS.update(coursework.TOPICS)
            session.LEAF_FIELDS.update('coursework.' + key for key in coursework.TOPICS)
        # Refresh copied helper references without reloading session-bearing modules.
        constraints=sys.modules.get('gradmatch.constraints')
        if constraints is not None:
            for name,module in list(sys.modules.items()):
                if not name.startswith('gradmatch.') or module is constraints or module is None:
                    continue
                for exported in ('check_constraints','evidence_ids','estimate_tuition'):
                    previous=getattr(module,exported,None)
                    if getattr(previous,'__module__',None)=='gradmatch.constraints':
                        setattr(module,exported,getattr(constraints,exported))
        _signature = signature
