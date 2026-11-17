"""Candidate-visible H1 contracts. Never import evaluator references here."""
from datetime import date
from typing import Literal
from pydantic import Field
from gradmatch.schemas import ApplicantProfile, Record


class CandidateInput(Record):
    task_id: str
    question: str
    profile: ApplicantProfile
    setup_messages: list[str]
    program_ids: list[str]
    as_of_date: date


class SearchProgramsArgs(Record):
    university: str | None
    campus: str | None
    discipline: Literal["CS", "ECE"] | None


class GetProgramArgs(Record):
    program_id: str


class GetEvidenceArgs(Record):
    source_id: str


class CheckProgramArgs(Record):
    program_id: str
    profile_version: int = Field(ge=1, strict=True)


TOOL_ARGUMENTS = {"search_programs": SearchProgramsArgs, "get_program": GetProgramArgs,
    "get_evidence": GetEvidenceArgs, "check_program": CheckProgramArgs}

TOOL_DESCRIPTIONS = {
    "search_programs": "Filter the frozen catalog by exact university/campus/discipline; null means unrestricted. Return matching IDs sorted ascending. No implicit fuzzy matching or top-k truncation.",
    "get_program": "Read one complete frozen program record and its source metadata; no network access.",
    "get_evidence": "Read one allowlisted frozen SourceRecord and its verified snapshot, with URL, date, locator and bound facts.",
    "check_program": "Check one program against the current session profile at the frozen assessment date. Reject a stale profile_version; never mutate the applicant profile.",
}


def tool_contracts():
    return {name: {"description": TOOL_DESCRIPTIONS[name], "arguments_schema": model.model_json_schema()}
        for name, model in TOOL_ARGUMENTS.items()}
