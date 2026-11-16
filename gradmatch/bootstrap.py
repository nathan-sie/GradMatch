"""Rebuild public SQLite data on a clean host; normal app connections stay read-only."""

from pathlib import Path
import os
import sqlite3
import tempfile
from threading import Lock

from gradmatch.catalog import DEFAULT_SEED, import_catalog, load_seed, read_catalog
from gradmatch.storage import CatalogNotReadyError, DEFAULT_DATABASE, inspect_catalog
from gradmatch.validation import data_hash


_BUILD_LOCK = Lock()


def bootstrap_public_catalog(cache_root: Path | None = None) -> Path:
    programs, sources = load_seed(DEFAULT_SEED)  # Includes snapshot and evidence-binding validation.
    digest = data_hash(programs, sources)
    cache_root = Path(cache_root or (Path(tempfile.gettempdir()) / "gradmatch-public")).resolve()
    target = cache_root / (digest + ".db")
    with _BUILD_LOCK:
        if target.is_file():
            try:
                inspect_catalog(target)
                current_programs, current_sources = read_catalog(target)
                if data_hash(current_programs, current_sources) == digest:
                    return target
            except (CatalogNotReadyError, ValueError, sqlite3.DatabaseError):
                pass  # Only this app-managed, content-addressed public cache is rebuilt.
        cache_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="build-", dir=cache_root) as staging:
            staged = Path(staging) / "catalog.db"
            import_catalog(DEFAULT_SEED, staged)
            staged_programs, staged_sources = read_catalog(staged)
            if data_hash(staged_programs, staged_sources) != digest:
                raise CatalogNotReadyError("The rebuilt public catalog differs from the validated source records.")
            os.replace(staged, target)  # Readers see a complete database, never a partial build.
    return target


def resolve_app_database() -> Path:
    explicit = os.environ.get("GRADMATCH_DB_PATH")
    if explicit:
        path = Path(explicit)
        inspect_catalog(path)  # Explicit missing/corrupt user paths are errors; no silent fallback.
        return path
    if DEFAULT_DATABASE.exists():
        inspect_catalog(DEFAULT_DATABASE)
        return DEFAULT_DATABASE
    cache = os.environ.get("GRADMATCH_PUBLIC_CACHE_DIR")
    return bootstrap_public_catalog(Path(cache) if cache else None)
