"""Refresh catalog-view modules after a hosted hot update without clearing sessions."""

import hashlib
import importlib
from pathlib import Path
import sys
from threading import Lock


_ROOT = Path(__file__).resolve().parent.parent
_MODULES = ("gradmatch.catalog", "gradmatch.bootstrap", "gradmatch.directory", "gradmatch.ui_directory")
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
        _signature = signature
