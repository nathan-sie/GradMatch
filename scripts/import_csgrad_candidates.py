"""Import a downloaded CS Grad tracker JSON into an unverified candidate DB.

This is M1 preparation, not an import of official university facts. It does not
alter the application catalog or access admissions datapoints (DP).
"""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from gradmatch.storage import DEFAULT_DATABASE, PROJECT_ROOT


UPSTREAM_PATH = "src/lib/tracker/school-list.json"
PROVIDER = "csgrad_tracker"

SCHEMA = """
CREATE TABLE IF NOT EXISTS import_manifests (
    source_sha256 TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_commit TEXT NOT NULL,
    upstream_generated TEXT NOT NULL,
    intake TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    row_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_programs (
    provider TEXT NOT NULL,
    source_id TEXT NOT NULL,
    intake TEXT NOT NULL,
    display_name TEXT NOT NULL,
    school_name TEXT,
    reported_program_name TEXT,
    program_url TEXT,
    application_url TEXT,
    source_tier TEXT,
    source_reports_halted INTEGER NOT NULL CHECK(source_reports_halted IN (0, 1)),
    verification_status TEXT NOT NULL CHECK(verification_status = 'community_unverified'),
    recommendation_eligible INTEGER NOT NULL DEFAULT 0 CHECK(recommendation_eligible = 0),
    source_sha256 TEXT NOT NULL REFERENCES import_manifests(source_sha256),
    attributes_json TEXT NOT NULL,
    PRIMARY KEY(provider, source_id, intake)
);
"""


def prepare_candidates(document: dict, expected_count: int) -> list[dict]:
    if expected_count < 1:
        raise ValueError("Expected count must be positive.")
    if not isinstance(document, dict):
        raise ValueError("Expected an object with generated, cycle, and rows.")
    for key in ("generated", "cycle"):
        if not isinstance(document.get(key), str) or not document[key].strip():
            raise ValueError(f"Missing dataset metadata: {key}")
    rows = document.get("rows")
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ValueError(f"Expected {expected_count} tracker rows; check the source version.")
    seen = set()
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Tracker rows must be objects.")
        for key in ("id", "name"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Missing candidate field: {key}")
        if row["id"] in seen:
            raise ValueError(f"Duplicate source id: {row['id']}")
        seen.add(row["id"])
        if not isinstance(row.get("halt"), bool):
            raise ValueError(f"Unknown halt status: {row['id']}")
        if not isinstance(row.get("rounds", []), list) or not isinstance(row.get("lang", {}), dict):
            raise ValueError(f"Unexpected deadline/language structure: {row['id']}")
        flags = ["identity_and_scope_unverified", "official_facts_unverified", "tuition_missing"]
        if row["halt"]:
            flags.append("source_reports_halted")
        if re.search(r"Doctor of|Ph\.?D\.?", row.get("official", ""), re.IGNORECASE):
            flags.append("source_mentions_doctoral_admission")
        # Preserve reported values and qualifiers; do not turn them into hard
        # eligibility thresholds or personalized admission-risk tiers.
        attributes = {
            "source_program_code": row.get("program"),
            "source_school_label": row.get("school"),
            "source_guide_path": row.get("slug"),
            "reported_deadline_rounds": row.get("rounds", []),
            "reported_gre": row.get("gre"),
            "reported_language": row.get("lang", {}),
            "application_fee_raw": row.get("fee"),
            "application_fee_currency": None,
            "tuition_total_usd": None,
            "personalized_tier": None,
            "review_flags": flags,
        }
        result.append({
            "provider": PROVIDER,
            "source_id": row["id"],
            "intake": document["cycle"],
            "display_name": row["name"],
            "school_name": row.get("schoolFull") or row.get("school"),
            "reported_program_name": row.get("official") or row.get("program"),
            "program_url": row.get("site"),
            "application_url": row.get("apply"),
            "source_tier": row.get("tier"),
            "source_reports_halted": int(row["halt"]),
            "verification_status": "community_unverified",
            "recommendation_eligible": 0,
            "attributes_json": json.dumps(attributes, ensure_ascii=False),
        })
    return result


def import_candidates(input_path: Path, database: Path, source_commit: str,
                      expected_count: int = 83) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Pin a full 40-character upstream commit, not a moving branch.")
    database = Path(database).resolve()
    if database == DEFAULT_DATABASE.resolve():
        raise ValueError("Use a separate candidate database; the verified app catalog is not an import target.")
    if database == Path(input_path).resolve():
        raise ValueError("The database cannot overwrite the input file.")
    raw = Path(input_path).read_bytes()
    document = json.loads(raw)
    candidates = prepare_candidates(document, expected_count)
    digest = hashlib.sha256(raw).hexdigest()
    source_url = f"https://raw.githubusercontent.com/csms-apply/csgrad/{source_commit}/{UPSTREAM_PATH}"
    imported_at = datetime.now(timezone.utc).isoformat()
    database.parent.mkdir(parents=True, exist_ok=True)
    columns = list(candidates[0]) + ["source_sha256"]
    insert = (
        f"INSERT INTO candidate_programs ({', '.join(columns)}) "
        f"VALUES ({', '.join(':' + key for key in columns)}) "
        "ON CONFLICT(provider, source_id, intake) DO UPDATE SET "
        + ", ".join(f"{key}=excluded.{key}" for key in columns if key not in {"provider", "source_id", "intake"})
    )
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO import_manifests VALUES (?, ?, ?, ?, ?, ?, ?)",
                (digest, source_url, source_commit, document["generated"], document["cycle"],
                 imported_at, len(candidates)),
            )
            connection.executemany(insert, [{**row, "source_sha256": digest} for row in candidates])
        counts = connection.execute(
            "SELECT COUNT(*), SUM(source_reports_halted), SUM(recommendation_eligible) "
            "FROM candidate_programs WHERE source_sha256 = ?", (digest,),
        ).fetchone()
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RuntimeError("Candidate database foreign-key validation failed.")
    return {
        "database": str(database), "source_url": source_url, "source_commit": source_commit,
        "source_sha256": digest, "upstream_generated": document["generated"],
        "intake": document["cycle"], "imported_rows": counts[0],
        "source_reports_halted": counts[1], "recommendation_eligible": counts[2],
        "official_verification": "not_performed", "app_catalog_modified": False,
        "datapoints_accessed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--database", type=Path, default=PROJECT_ROOT / "work" / "csgrad_candidates.db")
    parser.add_argument("--expected-count", type=int, default=83)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = import_candidates(args.input, args.database, args.source_commit, args.expected_count)
    except (ValueError, OSError, sqlite3.DatabaseError) as error:
        parser.exit(1, f"Import failed: {error}\n")
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()

