"""Read-only access to the deployable public program catalog."""

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = PROJECT_ROOT / "data" / "gradmatch.db"
SCHEMA_VERSION = 1


class CatalogNotReadyError(RuntimeError):
    """The catalog is missing or does not use the expected schema."""


@dataclass(frozen=True)
class CatalogSummary:
    program_count: int
    source_count: int
    schema_version: int


def connect_read_only(path: Path = DEFAULT_DATABASE) -> sqlite3.Connection:
    """Never create a missing database or allow application writes."""
    path = Path(path).resolve()
    if not path.is_file():
        raise CatalogNotReadyError(
            "The catalog has not been built. Run python -m scripts.build_catalog --input data/catalog/m1_seed.json."
        )
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)


def inspect_catalog(path: Path = DEFAULT_DATABASE) -> CatalogSummary:
    """Check the schema and return real row counts, without mutating data."""
    try:
        with closing(connect_read_only(path)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if version != SCHEMA_VERSION or not {"programs", "sources"} <= tables:
                raise CatalogNotReadyError("The catalog version or schema is invalid. Check the build output.")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise CatalogNotReadyError("The catalog integrity check failed.")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise CatalogNotReadyError("The evidence-to-program foreign-key check failed.")
            return CatalogSummary(
                program_count=connection.execute("SELECT COUNT(*) FROM programs").fetchone()[0],
                source_count=connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                schema_version=version,
            )
    except sqlite3.DatabaseError as error:
        raise CatalogNotReadyError("The catalog cannot be read or is not a valid database file.") from error

