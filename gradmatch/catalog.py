"""Validate and import versioned public records and short evidence snapshots."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from gradmatch.schemas import ApplicantProfile, Intake, ProgramRecord, SourceRecord
from gradmatch.storage import DEFAULT_DATABASE, PROJECT_ROOT, connect_read_only
from scripts.build_catalog import build_empty_catalog


M1_SEED = PROJECT_ROOT / "data" / "catalog" / "m1_seed.json"
M35_SEED = PROJECT_ROOT / "data" / "catalog" / "m35_seed.json"
M61B_SEED = PROJECT_ROOT / "data" / "catalog" / "m61b_seed.json"
M61C_SEED = PROJECT_ROOT / "data" / "catalog" / "m61c_seed.json"
M61E_SEED = PROJECT_ROOT / "data" / "catalog" / "m61e_seed.json"
M61F_SEED = PROJECT_ROOT / "data" / "catalog" / "m61f_seed.json"
DEFAULT_SEED = PROJECT_ROOT / "data" / "catalog" / "m61g_seed.json"
ACTIVE_SEED = PROJECT_ROOT / "data" / "catalog" / "active.json"


def current_seed() -> Path:
    """Resolve a stable on-disk pointer on each call, including after hot data updates."""
    if not ACTIVE_SEED.exists():
        return DEFAULT_SEED
    name = json.loads(ACTIVE_SEED.read_text(encoding="utf-8"))["seed"]
    path = (ACTIVE_SEED.parent / name).resolve()
    if path.parent != ACTIVE_SEED.parent.resolve() or path.suffix != ".json" or path == ACTIVE_SEED.resolve():
        raise ValueError("The active catalog pointer must name a seed in data/catalog.")
    return path


def load_seed(path: Path | None = None) -> tuple[list[ProgramRecord], dict[str, SourceRecord]]:
    path = Path(path) if path is not None else current_seed()
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    programs = [ProgramRecord.model_validate(row) for row in document["programs"]]
    source_list = [SourceRecord.model_validate(row) for row in document["sources"]]
    if len({program.program_id for program in programs}) != len(programs):
        raise ValueError("Duplicate program IDs in catalog seed.")
    sources = {source.source_id: source for source in source_list}
    if len(sources) != len(source_list):
        raise ValueError("Duplicate source IDs in catalog seed.")
    program_map = {program.program_id: program for program in programs}
    from gradmatch.constraints import evidence_ids
    for source in source_list:
        if source.program_id not in program_map:
            raise ValueError(f"Source points to an unknown program: {source.source_id}")
        snapshot = (PROJECT_ROOT / source.snapshot_path).resolve()
        if not snapshot.is_relative_to((PROJECT_ROOT / "data" / "snapshots").resolve()):
            raise ValueError("Snapshot path escapes the public snapshots directory.")
        snapshot_bytes = snapshot.read_bytes()
        if hashlib.sha256(snapshot_bytes).hexdigest() != source.content_hash:
            raise ValueError(f"Snapshot hash mismatch: {source.source_id}")
        captured = json.loads(snapshot_bytes)
        if (captured["verified_values"] != source.verified_values
                or captured["source_excerpt"] != source.source_excerpt
                or captured["fact_summary"] != source.fact_summary
                or captured["raw_response_sha256"] != source.raw_response_sha256
                or captured["url"].rstrip("/") != str(source.url).rstrip("/")):
            raise ValueError(f"Snapshot metadata mismatch: {source.source_id}")
        program = program_map[source.program_id]
        reference_intake = source.applicable_intake or (program.supported_intakes[0].key if program.supported_intakes else "2027-fall")
        year, term = reference_intake.split("-")
        profile = ApplicantProfile(intake=Intake(year=int(year), term=term))
        for group in source.field_groups:
            if source.source_id not in program.field_sources.get(group, []):
                raise ValueError(f"Unbound source field group: {source.source_id}/{group}")
            if source.verification_status == "verified" and not evidence_ids(program, group, sources, profile):
                raise ValueError(f"Official field values do not match evidence: {source.source_id}/{group}")
    for program in programs:
        if program.official_url.host not in program.allowed_official_hosts:
            raise ValueError(f"Program home host not allowlisted: {program.program_id}")
        if not program.field_sources.get("identity"):
            raise ValueError(f"No official identity source: {program.program_id}")
        for ids in program.field_sources.values():
            if any(source_id not in sources for source_id in ids):
                raise ValueError(f"Unknown source reference in {program.program_id}")
    return programs, sources


def import_catalog(seed: Path | None = None, database: Path = DEFAULT_DATABASE) -> dict:
    programs, sources = load_seed(seed)  # Validate everything before any write.
    build_empty_catalog(database)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.executemany(
                "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(program_id) DO UPDATE SET university=excluded.university, "
                "program_name=excluded.program_name, degree=excluded.degree, campus=excluded.campus, "
                "discipline=excluded.discipline, record_json=excluded.record_json, catalog_version=excluded.catalog_version",
                [(p.program_id, p.university, p.program_name, p.degree, p.campus, p.discipline,
                  p.model_dump_json(), p.catalog_version) for p in programs],
            )
            connection.executemany(
                "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_id) DO NOTHING",
                [(s.source_id, s.program_id, str(s.url), s.source_type, s.applicable_intake,
                  s.retrieved_at.isoformat(), s.content_hash, s.snapshot_path,
                  s.model_dump_json(), s.verification_status) for s in sources.values()],
            )
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Imported source foreign keys are invalid.")
    return {"imported_programs": len(programs), "imported_sources": len(sources),
            "catalog_version": programs[0].catalog_version}


def read_catalog(database: Path = DEFAULT_DATABASE) -> tuple[list[ProgramRecord], dict[str, SourceRecord]]:
    with closing(connect_read_only(database)) as connection:
        programs = [ProgramRecord.model_validate_json(row[0]) for row in connection.execute(
            "SELECT record_json FROM programs ORDER BY program_id")]
        sources = [SourceRecord.model_validate_json(row[0]) for row in connection.execute("SELECT facts_json FROM sources")]
    return programs, {source.source_id: source for source in sources}


def coverage_rows(programs, sources) -> list[dict]:
    from gradmatch.constraints import estimate_tuition
    rows = []
    for program in programs:
        estimate = estimate_tuition(program.tuition)
        missing = ([] if program.eligibility_review_complete else ["remaining_eligibility"]) + ([] if program.admission_evidence else ["admission_risk_evidence"]) + [group for group in ["intake", "gpa", "english", "prerequisites", "tuition", "deadline"]
                   if not program.field_sources.get(group)]
        if estimate.upper_usd is None and "tuition" not in missing:
            missing.append("tuition_not_computable")
        if program.gpa and program.gpa.minimum is None:
            missing.append("hard_gpa_minimum_not_verified")
        if not program.prerequisites_complete:
            missing.append("prerequisites_need_review")
        if program.deadlines and not program.deadline_schedule_complete:
            missing.append("final_deadline_schedule_partial")
        rows.append({"program_id": program.program_id, "university": program.university,
            "program_name": program.program_name, "campus": program.campus,
            "required_credits": str(program.required_credits) if program.required_credits is not None else None,
            "tuition_estimate_usd": str(estimate.upper_usd) if estimate.upper_usd is not None else None,
            "rate_year": estimate.rate_year, "source_count": sum(s.program_id == program.program_id for s in sources.values()),
            "missing_fields": missing, "admission_risk_evidence": "reviewed_cohort" if program.admission_evidence else "not_collected",
            "recommendation_ready": False})
    return rows

