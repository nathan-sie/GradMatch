"""Aggregate applicant reports and conservative application planning tiers."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Annotated
from uuid import uuid4

from pydantic import Field, model_validator

from gradmatch.schemas import GPAScope, Intake, Positive, Record
from gradmatch.storage import PROJECT_ROOT


PREVIEW_FILE = PROJECT_ROOT / "work/admissions_dp/recommendation_preview.json"
BUNDLED_PREVIEW_FILE = PROJECT_ROOT / "data/review/admission_history_aggregates.json"
BROAD_ENGINE_VERSION = 4
OPENCS_DP_SOURCE = "OpenCS DataPoints"
OPENCS_DP_URL = "https://opencs.app/datapoints/"
OPENCS_GRADE_URL = "https://opencs.app/grade/"
GPA_BAND_COUNT = 16
MINIMUM_BAND_REPORTS = 5
PLANNING_TIERS = ("Lottery", "Reach", "Target", "Safer")
# Ordered from the most competitive OpenCS category to the least competitive.
OPENCS_PLANNING_TIERS = {
    "SSS": "Lottery", "SS": "Lottery", "S": "Lottery",
    "A+": "Reach", "A": "Reach", "A-": "Target", "B+": "Target",
    "B": "Safer", "B-": "Safer", "C+": "Safer", "C": "Safer",
}
BandIndex = Annotated[int, Field(ge=0, lt=GPA_BAND_COUNT)]


def gpa_band(value: Decimal, scale: Decimal) -> int:
    return min(int(value * GPA_BAND_COUNT / scale), GPA_BAND_COUNT - 1)


class OutcomeCounts(Record):
    admitted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    assumed_overall: int = Field(ge=0)

    @property
    def total(self):
        return self.admitted + self.rejected

    @model_validator(mode="after")
    def check_assumptions(self):
        if self.assumed_overall > self.total:
            raise ValueError("The assumed-scope count exceeds the outcome sample.")
        return self


class HistoryPreview(Record):
    intake: Intake
    cycles: list[int] = Field(min_length=1, max_length=3)
    snapshot_date: date
    gpa_scale: Positive
    gpa_scope: GPAScope
    programs: dict[str, OutcomeCounts]
    gpa_bands: dict[str, dict[BandIndex, OutcomeCounts]] = Field(default_factory=dict)

    def fingerprint(self):
        content = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def compare(self, profile):
        if (profile.gpa and profile.intake == self.intake and profile.gpa.scale == self.gpa_scale
                and profile.gpa.scope == self.gpa_scope):
            return HistoryComparison(self, gpa_band(profile.gpa.value, profile.gpa.scale))
        return None


@dataclass(frozen=True)
class HistoryComparison:
    snapshot: HistoryPreview
    band: int

    @property
    def band_label(self):
        width = self.snapshot.gpa_scale / GPA_BAND_COUNT
        lower, upper = self.band * width, (self.band + 1) * width
        limit = "through" if self.band == GPA_BAND_COUNT - 1 else "to below"
        return f"{lower.normalize():f} {limit} {upper.normalize():f}"

    def band_counts(self, program_id):
        bands = self.snapshot.gpa_bands.get(program_id)
        if bands is None:
            return None
        return bands.get(self.band) or OutcomeCounts(admitted=0, rejected=0, assumed_overall=0)

    def ranking_options(self, program_ids, snapshot_hash):
        options = {}
        for program_id in program_ids:
            counts = self.band_counts(program_id)
            if counts and counts.total >= MINIMUM_BAND_REPORTS:
                options[program_id] = {
                    "evidence_id": f"history:{program_id}:{self.band}:{snapshot_hash[:12]}",
                    "program_id": program_id,
                    "basis": "self_reported",
                    "source": OPENCS_DP_SOURCE,
                    "snapshot_date": self.snapshot.snapshot_date.isoformat(),
                    "admission_cycles": self.snapshot.cycles,
                    "intake": self.snapshot.intake.key,
                    "gpa_scale": format(self.snapshot.gpa_scale.normalize(), "f"),
                    "gpa_scope": self.snapshot.gpa_scope,
                    "gpa_band": self.band_label,
                    **counts.model_dump(),
                }
        return options

    def covered_candidates(self, result):
        blocked = {item["program_id"] for key in ("excluded", "preliminary_excluded") for item in result.get(key, [])}
        statuses = {}
        for key, label in (
            ("recommendations", "Formal recommendation"),
            ("preliminary_recommendations", "Preliminary recommendation"),
            ("pending_verification", "Pending verification"),
        ):
            for item in result.get(key, []):
                statuses.setdefault(item["program_id"], label)
        covered = []
        for program_id, status in statuses.items():
            counts = self.band_counts(program_id)
            if program_id not in blocked and counts and counts.total >= MINIMUM_BAND_REPORTS:
                covered.append((program_id, status, counts))
        return sorted(covered, key=lambda row: -row[2].total)


def write_preview(report, intake):
    programs = {}
    for row in report["programs"]:
        effective = row["same_gpa_scale_and_effective_scope_outcomes"]
        assumed = row["same_gpa_scale_assumed_overall_outcomes"]
        programs[row["program_id"]] = OutcomeCounts(
            admitted=effective.get("reported_admit", 0),
            rejected=effective.get("reported_reject", 0),
            assumed_overall=assumed.get("reported_admit", 0) + assumed.get("reported_reject", 0),
        )
    preview = HistoryPreview(
        intake=intake,
        cycles=report["report_cycles"],
        snapshot_date=datetime.fromisoformat(report["downloaded_at_utc"]).date(),
        gpa_scale=report["comparison_gpa_scale"],
        gpa_scope=report["comparison_gpa_scope"],
        programs=programs,
        gpa_bands={row["program_id"]: row["gpa_bands"] for row in report["programs"] if "gpa_bands" in row},
    )
    PREVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = PREVIEW_FILE.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(preview.model_dump_json(indent=2) + "\n", encoding="utf-8")
    temporary.replace(PREVIEW_FILE)
    return PREVIEW_FILE


def load_preview():
    try:
        return HistoryPreview.model_validate_json(PREVIEW_FILE.read_bytes())
    except (OSError, ValueError):
        return None


def load_bundled_preview():
    try:
        return HistoryPreview.model_validate_json(BUNDLED_PREVIEW_FILE.read_bytes())
    except (OSError, ValueError):
        return None


def planning_tier(history, *, hard_checks_passed, opencs_grade=None):
    """Assign a relative planning label and retain matched self-reported counts."""
    if opencs_grade in OPENCS_PLANNING_TIERS:
        relative_tier = OPENCS_PLANNING_TIERS[opencs_grade]
        return {"label": relative_tier, "history": history, "basis": "opencs_relative",
                "reason": f"OpenCS category {opencs_grade} places this program in the {relative_tier} planning group. "
                          "Check the budget and requirements below before applying."}
    label = "Reach"
    reason = "Fewer than five usable reports match this program, intake and GPA band. Treat it as a stretch option while checking the requirements."
    if history is not None:
        admitted, rejected = history["admitted"], history["rejected"]
        total = admitted + rejected
        reason = "The matched reports provide limited or mixed support for this application."
        if total >= 12 and 5 * admitted >= 4 * total and rejected > 0 and hard_checks_passed:
            label = "Safer"
            reason = "At least 12 reports match, at least four in five report admission, and the official hard checks pass."
        elif total >= 8 and 5 * admitted >= 3 * total:
            label = "Target"
            reason = "At least eight reports match and at least three in five report admission. Confirm the remaining application requirements."
    return {"label": label, "reason": reason, "history": history}


def read_preview(profile):
    snapshot = load_preview()
    return snapshot.compare(profile) if snapshot else None
