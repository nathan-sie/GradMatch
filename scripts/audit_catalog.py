"""Create an offline M6.1 evidence audit without writing either SQLite database."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from uuid import uuid4

from gradmatch.catalog import DEFAULT_SEED, load_seed
from gradmatch.catalog_audit import audit_catalog, markdown_report, screen_candidates
from gradmatch.schemas import Intake
from gradmatch.storage import PROJECT_ROOT

INDEX = PROJECT_ROOT / "data/review/m61_candidate_index.json"
LEGACY_REVIEW = PROJECT_ROOT / "data/review/m61_review_plan.json"
REVIEW = PROJECT_ROOT / "data/review/m61b_review_plan.json"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_candidate_store(index, database):
    database = Path(database).resolve()
    before = sha256(database)
    with closing(
        sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    ) as connection:
        records = connection.execute(
            "SELECT source_id,program_url,source_reports_halted,verification_status,recommendation_eligible FROM candidate_programs WHERE source_sha256=? AND intake=?",
            (index["source_sha256"], index["intake"]),
        ).fetchall()
        manifest = connection.execute(
            "SELECT source_commit,source_url,upstream_generated,row_count FROM import_manifests WHERE source_sha256=?",
            (index["source_sha256"],),
        ).fetchone()
    expected = sorted(
        (
            r["source_id"],
            r["program_url"],
            r["source_reports_halted"],
            r["verification_status"],
            r["recommendation_eligible"],
        )
        for r in index["rows"]
    )
    if sorted(records) != expected or manifest != (
        index["source_commit"],
        index["source_url"],
        index["upstream_generated"],
        index["expected_rows"],
    ):
        raise ValueError("CANDIDATE_DATABASE_DIFFERS_FROM_PINNED_INDEX")
    if sha256(database) != before:
        raise ValueError("CANDIDATE_DATABASE_CHANGED_DURING_AUDIT")
    return dict(
        status="passed",
        matched_rows=len(records),
        database_sha256=before,
        read_only=True,
    )


def build_report(
    *,
    seed=DEFAULT_SEED,
    index_path=INDEX,
    review_path=REVIEW,
    as_of=None,
    candidate_database=None,
    original_tracker=None,
):
    review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    as_of = as_of or date.fromisoformat(review["reviewed_on"])
    year, term = review["target_intake"].split("-")
    programs, sources = load_seed(Path(seed))
    catalog = audit_catalog(
        programs, sources, as_of=as_of, intake=Intake(year=int(year), term=term)
    )
    candidates = screen_candidates(index, review, programs)
    source_check = {
        "status": "not_supplied",
        "notice": "The reduced pinned index is bundled; the full upstream JSON is optional local material.",
    }
    if original_tracker:
        from scripts.import_csgrad_candidates import prepare_candidates

        original_tracker = Path(original_tracker)
        raw = json.loads(original_tracker.read_text(encoding="utf-8"))
        prepared = prepare_candidates(raw, index["expected_rows"])
        reduced = [
            {k: r[k] for k in index["rows"][0] if k != "review_flags"}
            | {"review_flags": json.loads(r["attributes_json"])["review_flags"]}
            for r in prepared
        ]
        if (
            sha256(original_tracker) != index["source_sha256"]
            or reduced != index["rows"]
        ):
            raise ValueError("UPSTREAM_TRACKER_DIFFERS_FROM_REDUCED_INDEX")
        source_check = dict(
            status="passed", source_sha256=index["source_sha256"], rows=len(prepared)
        )
    return dict(
        milestone=review.get("milestone", "M6.1a"),
        scope=review.get("scope", "Existing-data audit and first-batch research queue"),
        catalog=catalog,
        candidates=candidates,
        target_catalog_min=review["target_catalog_min"],
        target_catalog_max=review["target_catalog_max"],
        inputs_sha256=dict(
            seed=sha256(seed),
            candidate_index=sha256(index_path),
            review_plan=sha256(review_path),
        ),
        full_tracker_check=source_check,
        candidate_store_check=check_candidate_store(index, candidate_database)
        if candidate_database
        else dict(status="not_supplied"),
        expanded_catalog_gate_met=review["target_catalog_min"]
        <= len(programs)
        <= review["target_catalog_max"],
        paid_model_requests=0,
        datapoints_accessed=False,
        formal_benchmark_run=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--candidate-index", type=Path, default=INDEX)
    parser.add_argument("--review-plan", type=Path, default=REVIEW)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--candidate-database", type=Path)
    parser.add_argument("--original-tracker", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report = build_report(
        seed=args.seed,
        index_path=args.candidate_index,
        review_path=args.review_plan,
        as_of=args.as_of,
        candidate_database=args.candidate_database,
        original_tracker=args.original_tracker,
    )
    directory = args.output_dir or PROJECT_ROOT / "work/m61" / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "catalog_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (directory / "catalog_audit.md").write_text(
        markdown_report(report), encoding="utf-8", newline="\n"
    )
    summary = report["catalog"]["summary"]
    print(
        f"Audited {summary['programs']} programs / {summary['sources']} sources; verified tuition {summary['computable_verified_tuition']}; reference formal evidence ready {summary['reference_formal_evidence_ready']}."
    )
    print(
        f"Screened {report['candidates']['summary']['total']} leads. No model calls; no database writes. Full expanded-catalog gate: {report['expanded_catalog_gate_met']}."
    )
    print("Reports: " + str(directory.resolve()))


if __name__ == "__main__":
    main()
