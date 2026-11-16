"""Typed public evidence and deterministic M1 checks; no admission prediction."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


NonNegative = Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class Intake(Record):
    year: int = Field(ge=2020, le=2100)
    term: Literal["fall", "spring", "summer", "winter"]

    @property
    def key(self) -> str:
        return f"{self.year}-{self.term}"


class GPA(Record):
    value: NonNegative
    scale: Positive
    scope: Literal["overall", "last_60_semester", "last_90_quarter"] = "overall"

    @model_validator(mode="after")
    def within_scale(self):
        if self.value > self.scale:
            raise ValueError("GPA cannot exceed its original scale.")
        return self


class EnglishScore(Record):
    version: Literal["toefl_120", "toefl_6", "ielts_9", "det_160"]
    total: NonNegative
    test_date: date | None = None
    subscores: dict[str, NonNegative] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_score_range(self):
        total_max = {"toefl_120": 120, "toefl_6": 6, "ielts_9": 9, "det_160": 160}[self.version]
        sub_max = 30 if self.version == "toefl_120" else total_max
        if self.total > total_max or any(value > sub_max for value in self.subscores.values()):
            raise ValueError("Score exceeds the selected test version's scale.")
        return self


class ApplicantProfile(Record):
    profile_version: int = Field(default=1, ge=1)
    gpa: GPA | None = None
    institution: str | None = None
    institution_country: str | None = None
    major: str | None = None
    coursework: dict[str, bool | None] = Field(default_factory=dict)
    research: list[str] | None = None
    work_experience: list[str] | None = None
    english: EnglishScore | None = None
    english_status: Literal["known", "not_taken", "unknown"] = "unknown"
    goal: Literal["employment", "research", "mixed"] | None = None
    tuition_budget_usd: NonNegative | None = None
    budget_basis: Literal["published_rate_estimate", "guaranteed_final"] = "published_rate_estimate"
    intake: Intake | None = None
    applicant_category: Literal["international", "domestic"] = "international"
    study_mode: Literal["full_time", "part_time"] = "full_time"

    @model_validator(mode="after")
    def score_and_status_agree(self):
        if (self.english is not None) != (self.english_status == "known"):
            raise ValueError("A known English result requires scores; unknown/not_taken must not carry scores.")
        return self


class GPARequirement(Record):
    minimum: NonNegative | None = None
    recommended: NonNegative | None = None
    scale: Positive = Decimal("4")
    accepted_scopes: list[str] = Field(default_factory=lambda: ["overall"])
    below_minimum_review_possible: bool = False
    no_hard_minimum: bool = False


class EnglishRequirement(Record):
    version: Literal["toefl_120", "toefl_6", "ielts_9", "det_160"]
    minimum_total: NonNegative
    recommended_total: NonNegative | None = None
    minimum_subscores: dict[str, NonNegative] = Field(default_factory=dict)
    validity_years: int | None = Field(default=None, ge=1, le=5)
    valid_on_anniversary: bool = False
    condition_below_recommended: str | None = None


class TuitionPolicy(Record):
    currency: str = "USD"
    basis: Literal["full_program", "per_credit", "per_term", "per_year", "unknown"] = "unknown"
    unit_rate_lower: NonNegative | None = None
    unit_rate_upper: NonNegative | None = None
    required_units_lower: Positive | None = None
    required_units_upper: Positive | None = None
    rate_year: str | None = None
    guaranteed_for_intake: str | None = None
    mandatory_fees_usd: NonNegative | None = None
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ranges_are_ordered(self):
        for lower, upper in [(self.unit_rate_lower, self.unit_rate_upper),
                             (self.required_units_lower, self.required_units_upper)]:
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("Range lower bound exceeds upper bound.")
        return self


class DeadlineRound(Record):
    intake: Intake
    date: date
    label: str
    audience: Literal["all", "international", "international_full_time", "domestic", "part_time"] = "all"


class SourceRecord(Record):
    source_id: str
    program_id: str
    url: HttpUrl
    title: str
    source_type: Literal["official_program", "official_admissions", "official_tuition"]
    retrieved_at: datetime
    applicable_intake: str | None = None
    effective_period: str | None = None
    verification_status: Literal["verified", "unknown", "conflict", "stale"] = "verified"
    field_groups: list[str]
    verified_values: dict[str, dict[str, Any]]
    source_excerpt: str
    fact_summary: str
    locator: str
    snapshot_path: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def timestamp_has_timezone(self):
        if self.retrieved_at.tzinfo is None:
            raise ValueError("Evidence retrieval timestamp must include its timezone.")
        return self


class ProgramRecord(Record):
    program_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    university: str
    school: str
    program_name: str
    degree: str
    campus: str
    track: str
    discipline: Literal["CS", "ECE"]
    official_url: HttpUrl
    allowed_official_hosts: list[str]
    candidate_source_id: str
    required_credits: Positive | None = None
    gpa: GPARequirement | None = None
    english: list[EnglishRequirement] = Field(default_factory=list)
    english_not_required: bool = False
    required_topics: list[str] = Field(default_factory=list)
    recommended_topics: list[str] = Field(default_factory=list)
    prerequisites_complete: bool = False
    supported_intakes: list[Intake] = Field(default_factory=list)
    closed_intakes: list[Intake] = Field(default_factory=list)
    deadlines: list[DeadlineRound] = Field(default_factory=list)
    deadline_schedule_complete: bool = False
    tuition: TuitionPolicy = Field(default_factory=TuitionPolicy)
    field_sources: dict[str, list[str]] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    eligibility_review_complete: bool = False
    goal_features: list["GoalFeature"] = Field(default_factory=list)
    admission_evidence: list["AdmissionEvidence"] = Field(default_factory=list)
    catalog_version: str

    @model_validator(mode="after")
    def no_duplicate_rules(self):
        if len({rule.version for rule in self.english}) != len(self.english):
            raise ValueError("Duplicate English rules for the same test version.")
        return self


class GoalFeature(Record):
    feature_id: str
    goal: Literal["employment", "research", "mixed"]
    statement: str
    source_ids: list[str]


class AdmissionEvidence(Record):
    evidence_id: str
    kind: Literal["admitted_case", "program_selectivity"]
    source_ids: list[str]
    cycle_year: int
    independence_key: str
    gpa: GPA | None = None
    major: str | None = None
    experience_dimensions: list[Literal["research", "work_experience"]] = Field(default_factory=list)
    permitted_tiers: list[Literal["Lottery", "Reach", "Target", "Safer"]]
    statement: str
    reviewed: bool = False


ProgramRecord.model_rebuild()


class TuitionEstimate(Record):
    lower_usd: NonNegative | None = None
    upper_usd: NonNegative | None = None
    formula: str | None = None
    rate_year: str | None = None
    reason_code: str
    assumptions: list[str] = Field(default_factory=list)
    mandatory_fees_usd: NonNegative | None = None


class ConstraintCheck(Record):
    rule_id: str
    status: CheckStatus
    reason_code: str
    explanation: str
    source_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ConstraintReport(Record):
    program_id: str
    profile_version: int
    as_of_date: date
    data_mode: Literal["snapshot"] = "snapshot"
    checks: list[ConstraintCheck]
    tuition: TuitionEstimate
    hard_checks_status: CheckStatus
    recommendation_ready: bool = False

