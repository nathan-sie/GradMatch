"""Build the schema, or import a validated versioned catalog without clearing data."""

import argparse
from contextlib import closing
from pathlib import Path
import sqlite3

from gradmatch.storage import DEFAULT_DATABASE, PROJECT_ROOT, inspect_catalog


def build_empty_catalog(output: Path = DEFAULT_DATABASE) -> Path:
    output = Path(output).resolve()
    if output.exists():
        inspect_catalog(output)
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    schema = (PROJECT_ROOT / "data" / "schema.sql").read_text(encoding="utf-8")
    with closing(sqlite3.connect(output)) as connection:
        connection.executescript("BEGIN;\n" + schema + "\nCOMMIT;")
    inspect_catalog(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--input", type=Path, help="M1 versioned catalog seed JSON")
    parser.add_argument("--validate", action="store_true", help="Validate seed without modifying a database")
    args = parser.parse_args()
    if args.input:
        from gradmatch.catalog import import_catalog, load_seed
        if args.validate:
            programs, sources = load_seed(args.input)
            print(f"Valid seed: {len(programs)} programs; {len(sources)} sources")
        else:
            print(import_catalog(args.input, args.output))
        return
    path = build_empty_catalog(args.output)
    summary = inspect_catalog(path)
    print(f"Catalog ready: {path}")
    print(f"Programs: {summary.program_count}; sources: {summary.source_count}")
    print("No input seed supplied: schema only, existing records preserved.")


if __name__ == "__main__":
    main()

