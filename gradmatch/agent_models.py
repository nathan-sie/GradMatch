"""M4 action and evidence contracts; only five registered tools can execute."""

from typing import Literal
from pydantic import Field
from gradmatch.schemas import Record
BROAD_ENGINE_VERSION = 1

Group = Literal[
    "credits",
    "gpa",
    "english",
    "tuition",
    "deadline",
    "intake",
    "degree",
    "gre",
    "prerequisites",
]


class SearchArgs(Record):
    program_ids: list[str] = Field(default_factory=list, max_length=83)
    discipline: Literal["CS", "ECE"] | None = None
    target_fields: list[Group] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=83)


class FetchArgs(Record):
    program_id: str
    source_id: str
    target_fields: list[Group] = Field(min_length=1, max_length=4)


class CheckArgs(Record):
    program_ids: list[str] = Field(min_length=1, max_length=83)
    profile_version: int = Field(ge=1)
    evidence_version: int = Field(ge=0)


class RankArgs(CheckArgs):
    pass


class ValidateArgs(Record):
    pass


class Action(Record):
    tool: Literal[
        "search_programs",
        "fetch_official_page",
        "check_constraints",
        "rank_programs",
        "validate_shortlist",
        "ask_user",
        "finish",
    ]
    arguments_json: str = Field(max_length=12000)
    summary: str = Field(max_length=1000)


class AskArgs(Record):
    requested_fields: list[str] = Field(min_length=1, max_length=6)
    question: str = Field(min_length=1, max_length=500)


class ExtractedFact(Record):
    group: Group
    bindings_json: str = Field(max_length=8000)
    quote: str = Field(min_length=8, max_length=1800)
    applicable_intake: str | None


class Extraction(Record):
    program_id: str
    facts: list[ExtractedFact] = Field(max_length=4)
    missing_fields: list[Group]


TOOL_ARGS = {
    "search_programs": SearchArgs,
    "fetch_official_page": FetchArgs,
    "check_constraints": CheckArgs,
    "rank_programs": RankArgs,
    "validate_shortlist": ValidateArgs,
}
GROUP_FIELDS = {
    "credits": {"required_credits"},
    "gpa": {"gpa"},
    "english": {"english", "english_not_required"},
    "tuition": {"tuition"},
    "deadline": {"deadlines", "deadline_schedule_complete"},
    "intake": {"supported_intakes", "closed_intakes"},
    "degree": {"degree_required", "accepted_degree_fields"},
    "gre": {"gre_policy", "gre_validity_years", "gre_at_home_accepted"},
    "prerequisites": {
        "required_topics",
        "recommended_topics",
        "prerequisites_complete",
    },
}
