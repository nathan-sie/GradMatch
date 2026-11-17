"""Evaluator-only task/reference loading and an explicit candidate projection."""
from datetime import date
import json
from pathlib import Path
from typing import Literal
from pydantic import Field, JsonValue, model_validator
from gradmatch.schemas import ApplicantProfile, Record
from gradmatch.homework.contracts import CandidateInput, TOOL_ARGUMENTS


class ExpectedCall(Record):
    name: str
    arguments: dict[str, JsonValue]

    @model_validator(mode="after")
    def valid_tool_arguments(self):
        if self.name not in TOOL_ARGUMENTS:
            raise ValueError("Unknown homework tool name")
        TOOL_ARGUMENTS[self.name].model_validate(self.arguments)
        return self


class EvalTask(Record):
    id: str = Field(pattern=r"^(t[0-9]{2}|d[0-9]{2})$")
    type: Literal["exact", "tool", "rubric", "unanswerable"]
    question: str = Field(min_length=20)
    profile: ApplicantProfile
    setup_messages: list[str] = Field(default_factory=list)
    program_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(min_length=1)
    family: str
    expected: str | None = None
    expected_call: ExpectedCall | None = None
    rubric: list[str] | None = None

    @model_validator(mode="after")
    def correct_grading_fields(self):
        if self.type == "exact":
            if not self.expected or self.expected_call or self.rubric is not None:
                raise ValueError("Exact tasks require only expected")
        elif self.type == "tool":
            if self.expected_call is None or self.expected is not None or self.rubric is not None:
                raise ValueError("Tool tasks require only expected_call")
        elif not self.rubric or self.expected is not None or self.expected_call is not None:
            raise ValueError("Rubric/unanswerable tasks require only rubric")
        if len(set(self.tags)) != len(self.tags) or len(set(self.program_ids)) != len(self.program_ids):
            raise ValueError("Duplicate tags or scoped program IDs")
        return self


class FactClaim(Record):
    program_id: str
    path: str
    value: JsonValue
    basis: Literal["official_binding", "snapshot_state"] = "official_binding"
    group: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class ExactBasis(Record):
    kind: Literal["field", "tuition_lower", "tuition_upper"]
    program_id: str
    path: str | None = None
    normalization: Literal["decimal", "text", "date"]


class ExpectedCheck(Record):
    program_id: str
    rule_id: str
    status: Literal["pass", "fail", "unknown", "not_applicable"]


class SourceAssertion(Record):
    source_id: str
    field: Literal["fact_summary", "source_excerpt"]
    contains: str = Field(min_length=5)


class Reference(Record):
    task_id: str
    answer: str = Field(min_length=30)
    basis_note: str = Field(min_length=20)
    source_ids: list[str]
    claims: list[FactClaim]
    source_assertions: list[SourceAssertion] = Field(default_factory=list)
    exact_basis: ExactBasis | None = None
    expected_checks: list[ExpectedCheck] = Field(default_factory=list)
    expected_profile_changes: dict[str, JsonValue] = Field(default_factory=dict)
    preserve_other_profile_fields: bool = False
    required_program_ids: list[str] = Field(default_factory=list)
    forbidden_formal_program_ids: list[str] = Field(default_factory=list)
    absence_query: str | None = None
    review_status: Literal["authored_and_snapshot_checked"] = "authored_and_snapshot_checked"


def read_jsonl(path: Path, model):
    def unique_keys(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError(f"Duplicate JSON key: {key}")
            values[key] = value
        return values

    def invalid_constant(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    records = []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"Blank JSONL record at {path.name}:{line_no}")
        try:
            records.append(model.model_validate(json.loads(line, object_pairs_hook=unique_keys,
                parse_constant=invalid_constant)))
        except (ValueError, TypeError) as error:
            raise ValueError(f"Invalid {model.__name__} at {path.name}:{line_no}: {error}") from error
    return records


def candidate_input(task: EvalTask, as_of: date) -> CandidateInput:
    """Whitelist only declared user inputs; grading metadata never crosses here."""
    return CandidateInput(task_id=task.id, question=task.question,
        profile=task.profile.model_copy(deep=True), setup_messages=list(task.setup_messages),
        program_ids=list(task.program_ids), as_of_date=as_of)


def load_candidate_inputs(path: Path, as_of: date) -> list[CandidateInput]:
    """H2 consumes this projection, not raw tasks.jsonl or evaluator references."""
    return [candidate_input(task, as_of) for task in read_jsonl(path, EvalTask)]
