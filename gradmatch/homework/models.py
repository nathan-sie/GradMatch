"""Candidate outputs and native model decisions; no evaluation answer fields."""
from dataclasses import dataclass, field
from typing import Literal
from pydantic import Field
from gradmatch.ranking import RecommendationDraft
from gradmatch.schemas import Record


class AnswerDraft(Record):
    answer: str = Field(min_length=1)
    citations: list[str]
    recommendations: list[RecommendationDraft]
    needs_clarification: bool


@dataclass
class ToolCall:
    call_id: str
    name: str
    arguments: str

    def as_input(self):
        return {"type":"function_call","call_id":self.call_id,"name":self.name,"arguments":self.arguments}


@dataclass
class Decision:
    calls: list[ToolCall] = field(default_factory=list)
    answer: AnswerDraft | None = None


class RunStop(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code=code
