"""Refresh catalog-view modules after a hosted hot update without clearing sessions."""

import hashlib
import importlib
from pathlib import Path
import sys
from threading import Lock


_ROOT = Path(__file__).resolve().parent.parent
RELEASE_REFRESH_VERSION = 4
_MODULES = ("gradmatch.coursework", "gradmatch.constraints", "gradmatch.catalog", "gradmatch.bootstrap",
            "gradmatch.tiers", "gradmatch.catalog_audit", "gradmatch.directory", "gradmatch.ui_directory",
            "gradmatch.ui_m1", "gradmatch.ui_m2")
_LOCK = Lock()
_signature = None


def refresh_catalog_modules():
    """Reload only stateless catalog/view code when its published files change.

    Streamlit may rerun app.py while cached imports still refer to an older seed.
    Keep applicant state, provider clients and task counters outside this refresh.
    """
    global _signature
    paths = [_ROOT / (name.replace(".", "/") + ".py") for name in _MODULES]
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
        for name in _MODULES:
            if name in sys.modules:
                importlib.reload(sys.modules[name])
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
