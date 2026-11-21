"""Verify the complete exploration directory without paid or external requests."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
from unittest.mock import patch
from uuid import uuid4

from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import load_seed, read_catalog
from gradmatch.directory import bootstrap_directory, comparison_rows, filter_records, read_directory
from gradmatch.providers import OpenAIProvider
from gradmatch.storage import DEFAULT_DATABASE, PROJECT_ROOT
from gradmatch.validation import data_hash


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir or PROJECT_ROOT / "work/m61d" / str(uuid4())
    output.mkdir(parents=True, exist_ok=False)
    preserved = [p for p in (DEFAULT_DATABASE, PROJECT_ROOT / "work/csgrad_candidates.db") if p.exists()]
    before = {p.name: sha256(p) for p in preserved}
    def denied(*args, **kwargs):
        raise AssertionError("Directory verification must not make external or paid requests")
    with (patch.object(socket, "getaddrinfo", denied), patch.object(socket, "create_connection", denied),
          patch.object(socket.socket, "connect", denied), patch.object(OpenAIProvider, "generate", denied)):
        official = bootstrap_public_catalog(output / "public")
        official_hash = sha256(official)
        database = bootstrap_directory(official, output / "public")
        document = read_directory(database)
        official_count = len(load_seed()[0])
        assert document["total"] == 83 and document["official_records"] == official_count
        rows = document["records"]
        assert len(filter_records(rows, review="Needs official review")) == 83-official_count
        assert len(filter_records(rows, review="Source-reported halt")) == 4
        assert len(filter_records(rows, "nyu brooklyn")) == 1
        assert all(not r["recommendation_eligible"] for r in rows)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            assert connection.execute("SELECT COUNT(*) FROM directory_records").fetchone()[0] == 83
        assert bootstrap_directory(official, output / "public") == database
        first = sha256(database)
        database.unlink()  # Only this verifier's generated cache.
        assert read_directory(bootstrap_directory(official, output / "public")) == document
        assert sha256(database) == first and sha256(official) == official_hash
        assert data_hash(*read_catalog(official)) == data_hash(*load_seed())
        comparison = comparison_rows([rows[0], filter_records(rows, "nyu brooklyn")[0]])
    after = {p.name: sha256(p) for p in preserved}
    assert before == after
    proof = dict(
        milestone="M6.1d", status="passed", verified_at=datetime.now(timezone.utc).isoformat(),
        directory_programs=83, linked_official_records=official_count, awaiting_official_review=83-official_count,
        official_sources=len(load_seed()[1]), computable_tuition_estimates=sum(r['tuition_upper_usd'] is not None for r in rows), preserved_halt_flags=4,
        directory_database=str(database.resolve()), directory_sha256=sha256(database),
        official_data_hash=data_hash(*load_seed()), databases_before=before, databases_after=after,
        rebuild_after_cache_loss="passed", external_requests=0, paid_model_requests=0,
        recommendation_data_unchanged=True, formal_benchmark_run=False,
    )
    (output / "verification.json").write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    (output / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    print(f"Directory passed: 83 programs / {official_count} linked official records / {83-official_count} awaiting review; proof: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
