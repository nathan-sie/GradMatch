"""Browsable community leads joined to reviewed facts, outside recommendation data."""

from contextlib import closing
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from threading import Lock
from urllib.parse import urlsplit

from gradmatch.catalog import read_catalog
from gradmatch.catalog_audit import program_audit
from gradmatch.constraints import evidence_ids
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT, connect_read_only


INDEX = PROJECT_ROOT / "data/review/m61_candidate_index.json"
LINKS = PROJECT_ROOT / "data/review/m61c_review_plan.json"
DIRECTORY_VERSION = "M6.1e"
REVIEW_DATE = date(2026, 11, 20)
UNKNOWN = "Needs verification"
_LOCK = Lock()

FIELD_LABELS = {
    "intake": "Intake", "gpa": "GPA policy", "english": "English policy",
    "prerequisites": "Prerequisites", "degree": "Degree background", "gre": "GRE policy",
    "credits": "Credits", "tuition": "Tuition", "deadline": "Deadlines",
    "remaining_eligibility": "Other eligibility", "goal_features": "Program goals",
    "admission_evidence": "Admission evidence",
}


def requirement_summaries(program, sources, fields, profile):
    """Expose reviewed policies without promoting recommendations to hard cutoffs."""
    result = {label: UNKNOWN for label in FIELD_LABELS.values()}
    if fields["gpa"]["evidence_bound"] and program.gpa:
        gpa = program.gpa
        if gpa.no_hard_minimum:
            result["GPA policy"] = "No hard GPA minimum in the reviewed policy"
        elif gpa.minimum is not None or gpa.recommended is not None:
            result["GPA policy"] = (f"Minimum {gpa.minimum}/{gpa.scale}" if gpa.minimum is not None
                                    else f"Recommended {gpa.recommended}/{gpa.scale}; hard minimum needs verification")
            scopes = {"overall": "overall", "last_60_semester": "last 60 semester credits", "last_90_quarter": "last 90 quarter credits"}
            result["GPA policy"] += "; scope: " + (", ".join(scopes.get(s, s) for s in gpa.accepted_scopes) or "needs verification")
            if gpa.below_minimum_review_possible:
                result["GPA policy"] += "; below-minimum exceptions require review"
    if fields["english"]["evidence_bound"]:
        names = {"toefl_120": "TOEFL /120", "toefl_6": "TOEFL /6", "ielts_9": "IELTS", "det_160": "DET"}
        if program.english_not_required:
            result["English policy"] = "Not required under the reviewed policy"
        elif program.english:
            result["English policy"] = "; ".join(
                f"{names[r.version]} minimum {r.minimum_total}"
                + (f", recommended {r.recommended_total}" if r.recommended_total is not None else "")
                + (", subscores: " + ", ".join(f"{k} {v}" for k, v in r.minimum_subscores.items()) if r.minimum_subscores else "")
                for r in program.english) + ". Test age, conditions and waivers must also be checked."
    if fields["degree"]["evidence_bound"] and program.degree_required:
        result["Degree background"] = "Recognized bachelor degree or equivalent; university confirms equivalency"
    if fields["gre"]["evidence_bound"] and program.gre_policy != "unknown":
        result["GRE policy"] = "Not required" if program.gre_policy == "not_required" else "Required; verify date and accepted format"
    if fields["deadline"]["evidence_bound"]:
        deadlines = [r for r in program.deadlines if r.intake.key == profile.intake.key]
        if deadlines:
            result["Deadlines"] = "; ".join(f"{r.date}: {r.label} ({r.audience.replace('_', ' ')})" for r in deadlines)
            if not program.deadline_schedule_complete:
                result["Deadlines"] += ". Further rounds or priority dates may need verification."
    # Notes are usable only when their exact values have current official bindings.
    for sid in evidence_ids(program, "directory_policies", sources, profile):
        for note in sources[sid].verified_values["directory_policies"].values():
            label, value = note.split(": ", 1)
            result[label] = value
    return result


def _safe_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid public program URL in directory input.")
    return value


def build_directory(programs, sources, index=None, links=None):
    """Keep all upstream identities; only explicit reviewed links supply official facts."""
    index = index if index is not None else json.loads(INDEX.read_text(encoding="utf-8"))
    links = links if links is not None else json.loads(LINKS.read_text(encoding="utf-8"))
    candidates = index["rows"]
    ids = [row["source_id"] for row in candidates]
    if len(ids) != index["expected_rows"] or len(set(ids)) != len(ids):
        raise ValueError("Directory candidate count or identity uniqueness check failed.")
    by_program = {p.program_id: p for p in programs}
    mapping = {}
    linked_ids = set()
    for link in links["catalog_links"]:
        sid, pid = link["candidate_source_id"], link["program_id"]
        if sid not in ids or sid in mapping or pid in linked_ids:
            raise ValueError("Ambiguous directory-to-program identity link.")
        mapping[sid] = pid
        linked_ids.add(pid)
    profile = tiering_profile()
    records = []
    for candidate in candidates:
        if candidate["recommendation_eligible"] or candidate["verification_status"] != "community_unverified":
            raise ValueError("Community leads must remain unverified directory inputs.")
        program = by_program.get(mapping.get(candidate["source_id"]))
        row = dict(
            source_id=candidate["source_id"], university=candidate["school_name"],
            program_name=candidate["reported_program_name"],
            reported_program_name=candidate["reported_program_name"],
            reported_university=candidate["school_name"],
            program_url=_safe_url(candidate["program_url"]),
            campus=UNKNOWN, track=UNKNOWN, discipline=UNKNOWN, degree=UNKNOWN,
            linked_program_id=None, review_status="Needs official review",
            source_reports_halted=bool(candidate["source_reports_halted"]),
            review_flags=list(candidate["review_flags"]),
            eligibility_review=UNKNOWN, tuition_upper_usd=None, tuition_formula=None,
            tuition_rate_year=None, tuition_assumptions=[], required_credits=None,
            official_source_count=0, official_sources=[], notes=[], field_coverage={},
            verified_fields=[], missing_fields=list(FIELD_LABELS.values()),
            requirements={label: UNKNOWN for label in FIELD_LABELS.values()},
            planning_tier="Requires applicant-specific evidence", recommendation_eligible=False,
        )
        if program is not None:
            audit = program_audit(program, sources, profile, REVIEW_DATE)
            fields = audit["field_coverage"]
            official_sources = [s.model_dump(mode="json") for s in sources.values()
                                if s.program_id == program.program_id and s.verification_status == "verified"]
            row.update(
                university=program.university, program_name=program.program_name,
                program_url=_safe_url(str(program.official_url)), campus=program.campus,
                track=program.track, discipline=program.discipline, degree=program.degree,
                linked_program_id=program.program_id, review_status="Official snapshots available",
                eligibility_review="Reviewed; applicant checks still required"
                    if fields["remaining_eligibility"]["rule_usable"] else UNKNOWN,
                tuition_upper_usd=audit["tuition"]["upper_usd"],
                tuition_formula=audit["tuition"]["formula"], tuition_rate_year=audit["tuition"]["rate_year"],
                tuition_assumptions=list(program.tuition.assumptions),
                required_credits=str(program.required_credits) if fields["credits"]["rule_usable"] else None,
                official_source_count=len(official_sources), official_sources=official_sources,
                notes=list(program.notes), field_coverage=fields,
                requirements=requirement_summaries(program, sources, fields, profile),
                verified_fields=[label for key, label in FIELD_LABELS.items() if fields[key]["rule_usable"]],
                missing_fields=[label for key, label in FIELD_LABELS.items() if not fields[key]["rule_usable"]],
            )
        records.append(row)
    records.sort(key=lambda r: (r["university"].casefold(), r["program_name"].casefold(), r["source_id"]))
    return dict(
        version=DIRECTORY_VERSION, source_commit=index["source_commit"],
        upstream_generated=index["upstream_generated"], source_intake=index["intake"],
        official_review_date=REVIEW_DATE.isoformat(),
        coverage_intake=profile.intake.key, attribution=index["attribution"],
        records=records, total=len(records),
        official_records=sum(r["linked_program_id"] is not None for r in records),
        notice="Directory entries are exploration leads, not applicant recommendations. Unknown fields remain unverified.",
    )


def _encoded(document):
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_directory(path):
    with closing(connect_read_only(path)) as connection:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Directory database integrity check failed.")
        metadata = json.loads(connection.execute("SELECT document FROM directory_metadata").fetchone()[0])
        metadata["records"] = [json.loads(row[0]) for row in connection.execute(
            "SELECT record_json FROM directory_records ORDER BY position")]
    return metadata


def bootstrap_directory(database, cache_root=None):
    """Atomic, content-addressed SQLite cache; never changes the official catalog."""
    document = build_directory(*read_catalog(database))
    digest = hashlib.sha256(_encoded(document).encode("utf-8")).hexdigest()
    root = Path(cache_root or os.environ.get("GRADMATCH_PUBLIC_CACHE_DIR")
                or Path(tempfile.gettempdir()) / "gradmatch-public") / "directory"
    target = root / (digest + ".db")
    with _LOCK:
        if target.is_file():
            try:
                if read_directory(target) == document:
                    return target
            except (sqlite3.DatabaseError, ValueError, TypeError):
                pass
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="build-", dir=root) as staging:
            staged = Path(staging) / "directory.db"
            with closing(sqlite3.connect(staged)) as connection, connection:
                connection.execute("CREATE TABLE directory_records (source_id TEXT PRIMARY KEY, position INTEGER UNIQUE, record_json TEXT NOT NULL)")
                connection.execute("CREATE TABLE directory_metadata (document TEXT NOT NULL)")
                connection.execute("INSERT INTO directory_metadata VALUES (?)", (_encoded({k: v for k, v in document.items() if k != "records"}),))
                connection.executemany("INSERT INTO directory_records VALUES (?, ?, ?)",
                    [(r["source_id"], i, _encoded(r)) for i, r in enumerate(document["records"])])
            if read_directory(staged) != document:
                raise ValueError("Directory SQLite round-trip changed records.")
            os.replace(staged, target)
    return target


def filter_records(records, query="", review="All programs", university="All universities"):
    terms = query.casefold().split()
    return [row for row in records
            if (university == "All universities" or row["university"] == university)
            and (review == "All programs"
                 or review == "Official snapshots available" and row["linked_program_id"] is not None
                 or review == "Needs official review" and row["linked_program_id"] is None
                 or review == "Source-reported halt" and row["source_reports_halted"])
            and all(term in " ".join(str(row[key]) for key in (
                "university", "program_name", "reported_program_name", "campus", "track", "discipline", "source_id"
            )).casefold() for term in terms)]


def tuition_label(row):
    amount = row["tuition_upper_usd"]
    return f"USD {float(amount):,.0f} ({row['tuition_rate_year']}; estimate)" if amount is not None else UNKNOWN


def comparison_rows(records):
    labels = {r["source_id"]: f"{r['university']} — {r['program_name']} [{r['source_id']}]" for r in records}
    fields = {
        "Review status": lambda r: r["review_status"], "Campus": lambda r: r["campus"],
        "Track": lambda r: r["track"], "Credits": lambda r: r["required_credits"] or UNKNOWN,
        "GPA policy": lambda r: r["requirements"]["GPA policy"],
        "English policy": lambda r: r["requirements"]["English policy"],
        "Degree background": lambda r: r["requirements"]["Degree background"],
        "GRE policy": lambda r: r["requirements"]["GRE policy"],
        "Preparation": lambda r: r["requirements"].get("Preparation", UNKNOWN),
        "Deadlines": lambda r: r["requirements"]["Deadlines"],
        "Estimated full-program tuition": tuition_label,
        "Tuition formula": lambda r: r["tuition_formula"] or UNKNOWN,
        "Tuition assumptions": lambda r: "; ".join(r["tuition_assumptions"]) or UNKNOWN,
        "Cost context": lambda r: r["requirements"].get("Cost context", UNKNOWN),
        "Funding context": lambda r: r["requirements"].get("Funding context", UNKNOWN),
        "Official evidence records": lambda r: r["official_source_count"],
        "Eligibility review": lambda r: r["eligibility_review"],
        "Planning tier": lambda r: r["planning_tier"],
        "Source-reported halt": lambda r: "Reported; official confirmation needed" if r["source_reports_halted"] else "No halt flag in source; availability not verified",
        "Needs verification": lambda r: ", ".join(r["missing_fields"]) or "Applicant-specific checks still required",
        "Program URL": lambda r: r["program_url"],
    }
    return [{"Field": label, **{labels[r["source_id"]]: value(r) for r in records}}
            for label, value in fields.items()]
