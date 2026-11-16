"""Per-connection state and atomic profile patches; no shared profile cache."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Literal
from uuid import uuid4

from gradmatch.schemas import ApplicantProfile, Record


TOPICS = {"calculus", "differential_equations", "linear_algebra", "programming",
          "object_oriented_programming", "data_structures", "algorithms", "probability_statistics", "discrete_math"}
TOPICS |= {"undergraduate_cs", "undergraduate_math"}
ROOT_FIELDS = set(ApplicantProfile.model_fields) - {"profile_version"}
LEAF_FIELDS = {"gpa.value", "gpa.scale", "gpa.scope", "english.version", "english.total", "english.test_date",
    "english_status", "goal", "tuition_budget_usd", "budget_basis", "intake.year", "intake.term",
    "institution", "institution_country", "major", "research", "work_experience", "applicant_category", "study_mode"}
LEAF_FIELDS |= {"english.subscores." + key for key in ["reading", "listening", "speaking", "writing"]}
LEAF_FIELDS |= {"coursework." + key for key in TOPICS}
LEAF_FIELDS |= {"degree.completion", "degree.recognition", "degree.field", "degree.country",
    "gre.verbal", "gre.quantitative", "gre.writing", "gre.test_date", "gre.format"}


class PatchOperation(Record):
    field: str
    value_json: str
    explicit_span: str


class ProfilePatch(Record):
    intent: Literal["new_request", "update_profile", "answer_question", "explain_previous"]
    operations: list[PatchOperation]
    referenced_program_ids: list[str]
    ambiguous_fields: list[str]


@dataclass
class Session:
    session_id: str = field(default_factory=lambda: str(uuid4()))
    profile: ApplicantProfile = field(default_factory=ApplicantProfile)
    unknown_fields: set[str] = field(default_factory=set)
    messages: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    receipts: dict[str, dict] = field(default_factory=dict)
    current_result: dict | None = None
    previous_result: dict | None = None
    pending_questions: list[dict] = field(default_factory=list)
    usage: list[dict] = field(default_factory=list)
    active: bool = False

    def event(self, kind: str, **payload):
        self.events.append({"event_id": str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id, "profile_version": self.profile.profile_version,
            "event_type": kind, "payload": payload})

    def update(self, changes: dict, *, unknown_fields=None):
        if not set(changes) <= ROOT_FIELDS:
            raise ValueError("Unsupported profile field. Profile versions are managed by the application.")
        data = self.profile.model_dump(mode="json")
        data.update(deepcopy(changes))
        candidate = ApplicantProfile.model_validate(data)
        changed = [key for key in changes if getattr(candidate, key) != getattr(self.profile, key)]
        new_unknown = set(unknown_fields) if unknown_fields is not None else self.unknown_fields - set(changes)
        if changed or new_unknown != self.unknown_fields:
            candidate.profile_version = self.profile.profile_version + 1
            self.profile = candidate
            self.unknown_fields = new_unknown
            if self.current_result is not None:
                self.previous_result = self.current_result
            self.current_result = None
            self.pending_questions = []
            self.event("profile_patch", changed_fields=changed, checks_invalidated=True)
        return changed


def synthetic_profile():
    return ApplicantProfile(gpa={"value": "3.5", "scale": "4", "scope": "last_60_semester"},
        major="Electrical and Computer Engineering", research=["One synthetic research project"],
        work_experience=["One synthetic software internship"], goal="employment",
        tuition_budget_usd="70000", intake={"year": 2027, "term": "fall"},
        english_status="known", english={"version": "toefl_120", "total": "100", "test_date": "2025-11-01"},
        degree={"completion": "completed", "recognition": "recognized_bachelors_or_equivalent", "field": "ECE", "country": "US"},
        coursework=dict.fromkeys(TOPICS - {"discrete_math"}, True))


def questions(profile: ApplicantProfile, programs, *, as_of: date, unknown_fields=()):
    missing = []
    def ask(field, text):
        if field not in unknown_fields:
            missing.append({"question_id": "provide_" + field, "requested_fields": [field], "text": text})
    if profile.gpa is None:
        ask("gpa", "What is your GPA, original scale, and calculation scope? Use the profile form; do not convert scales.")
    if profile.tuition_budget_usd is None:
        ask("tuition_budget_usd", "What is your full-program tuition budget in USD, excluding living costs?")
    if profile.intake is None:
        ask("intake", "Which intake year and term are you targeting?")
    if profile.goal is None:
        ask("goal", "Is your main goal employment, research, or a mix of both?")
    if profile.major is None:
        ask("major", "What is your undergraduate major? You can mark it unknown in the profile form.")
    from gradmatch.constraints import estimate_tuition
    candidates = [p for p in programs if profile.tuition_budget_usd is None
        or estimate_tuition(p.tuition).upper_usd is None or estimate_tuition(p.tuition).upper_usd <= profile.tuition_budget_usd]
    if any(p.degree_required for p in candidates) and (profile.degree is None or profile.degree.completion == "unknown" or profile.degree.recognition == "unknown"):
        ask("degree", "What is your degree completion and recognized-bachelor/equivalency status? Please use the degree section of the form.")
    if any(p.gre_policy == "required" for p in candidates) and (profile.gre is None or profile.gre.test_date is None):
        ask("gre", "A candidate requires GRE scores. Provide the report and test date, or explicitly mark them unknown.")
    relevant = [p for p in programs if p.english and any(d.intake == profile.intake for d in p.deadlines)]
    if relevant and profile.english_status == "unknown":
        ask("english", "Which English test/version, score, and test date do you have? If unavailable, select Unknown or Not taken yet explicitly.")
    if profile.english:
        rules = [r for p in relevant for r in p.english if r.version == profile.english.version]
        if any(r.validity_years or r.minimum_test_date for r in rules) and profile.english.test_date is None:
            ask("english.test_date", "What is the English test date? Mark it unknown if you cannot provide it.")
        for name in sorted({name for r in rules for name in r.minimum_subscores} - profile.english.subscores.keys()):
            ask("english.subscores." + name, f"What is your {name} subscore on the same test scale? It is required by a candidate's rule.")
    return missing


def tiering_profile():
    """Fictional evidence-complete test profile, never a real applicant record."""
    data = synthetic_profile().model_dump(exclude={"profile_version"})
    data.update(gpa={"value": "3.5", "scale": "4", "scope": "overall"},
        major="Computer Science", tuition_budget_usd="140000",
        degree={"completion": "completed", "recognition": "recognized_bachelors_or_equivalent", "field": "CS", "country": "US"},
        english={"version": "toefl_120", "total": "110", "test_date": "2025-11-01"},
        gre={"verbal":160,"quantitative":165,"writing":"4","test_date":"2025-06-01","format":"in_person"})
    return ApplicantProfile.model_validate(data)


def quick_patch(message: str) -> ProfilePatch | None:
    # Deliberately narrow full-message commands; everything else goes to the shared interpreter.
    match = re.fullmatch(r"\s*(?:change (?:my |the )?(?:tuition )?budget to|set (?:my |the )?(?:tuition )?budget to|(?:my )?(?:tuition )?budget(?: is|:)?|预算(?:改成|改为|调整为))\s*(?:USD\s*|\$)?([0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*(?:USD|dollars|美元)?[.!。]?\s*", message, re.I)
    if match:
        return ProfilePatch(intent="update_profile", operations=[PatchOperation(field="tuition_budget_usd",
            value_json=json.dumps(match.group(1).replace(",", "")), explicit_span=message)],
            referenced_program_ids=[], ambiguous_fields=[])
    return None


def explanation_only(message: str) -> bool:
    """An empty patch can answer a question despite a mistaken model intent label."""
    text = re.sub(r"\b(?:do not|don't)\s+(?:change|modify|update)\b|不要(?:修改|更改|更新)", "", message.lower())
    question = re.match(r"\s*(?:which\b|what\b|why\b|how\b|explain\b|compare\b|tell me about\b|哪些|哪个|为什么|如何|解释|比较)", text)
    mutation = re.search(r"\b(?:change|set|update|increase|decrease|lower|raise|switch|replace)\b|改成|改为|更改|更新", text)
    return bool(question and not mutation)


def apply_patch(session: Session, patch: ProfilePatch, message: str):
    """Validate the whole patch before committing; one bad operation changes nothing."""
    if patch.ambiguous_fields:
        raise ValueError("The requested changes are ambiguous. Please use the profile form to state the exact values.")
    data = session.profile.model_dump(mode="json")
    changed_roots = set()
    seen = set()
    for operation in patch.operations:
        path, span = operation.field, operation.explicit_span
        if path not in LEAF_FIELDS or path in seen or not span.strip() or span not in message:
            raise ValueError("A proposed change has no valid explicit support in your message. Please use the profile form.")
        seen.add(path)
        value = json.loads(operation.value_json)
        if not literal_support(path, value, span):
            raise ValueError("A proposed value could not be verified against your words. Please enter it in the profile form.")
        pieces = path.split(".")
        target = data
        for piece in pieces[:-1]:
            if target.get(piece) is None:
                target[piece] = {}
            target = target[piece]
        target[pieces[-1]] = value
        changed_roots.add(pieces[0])
    return session.update({root: data[root] for root in changed_roots})


def literal_support(path, value, span):
    text = span.lower()
    root = path.split(".")[0]
    cues = {"tuition_budget_usd": ["budget", "tuition", "预算", "学费"],
        "gpa": ["gpa", "绩点"], "english": ["english", "toefl", "ielts", "score", "英语", "托福", "雅思"],
        "intake": ["intake", "fall", "spring", "summer", "winter", "入学", "秋", "春"],
        "goal": ["goal", "employment", "research", "mixed", "找工", "就业", "科研", "目标"],
        "major": ["major", "专业"], "institution": ["university", "college", "institution", "学校"],
        "institution_country": ["country", "国家"], "research": ["research", "科研"],
        "work_experience": ["work", "internship", "experience", "实习", "工作"],
        "coursework": ["course", "completed", "programming", "课程", "学过"],
        "english_status": ["english", "test", "toefl", "ielts", "英语", "托福", "雅思"],
        "budget_basis": ["published", "estimate", "guarantee", "估算", "保证"],
        "applicant_category": ["international", "domestic", "国际"], "study_mode": ["full-time", "part-time", "全日制", "非全日制"]}
    cues.update(degree=["degree", "bachelor", "学历", "学位"], gre=["gre"])
    if not any(cue in text for cue in cues.get(root, [])):
        return False
    if value is None:
        return bool(re.search(r"\b(unknown|clear|remove)\b|未知|不清楚", text))
    if isinstance(value, bool):
        positive = bool(re.search(r"\b(completed|passed|have taken)\b|学过|完成", text))
        negative = bool(re.search(r"\b(no|not|never|haven't|have not)\b|没|未", text))
        return (positive and not negative) if value else negative
    if isinstance(value, (list, dict)):
        return isinstance(value, list) and ((not value and bool(re.search(r"\b(none|no)\b|没有", text)))
            or (bool(value) and all(isinstance(item, str) and item.lower() in text for item in value)))
    if path in {"tuition_budget_usd", "gpa.value", "gpa.scale", "english.total", "intake.year", "gre.verbal", "gre.quantitative", "gre.writing"} or path.startswith("english.subscores."):
        try:
            numbers = [Decimal(n.replace(",", "")) for n in re.findall(r"(?<![0-9.])-?\d+(?:,\d{3})*(?:\.\d+)?", text)]
            return Decimal(str(value)) in numbers
        except InvalidOperation:
            return False
    aliases = {"employment": ["employment", "job", "找工", "就业"], "research": ["research", "科研"],
        "mixed": ["mixed", "both", "两者"], "known": ["score", "成绩"], "not_taken": ["not taken", "未考"],
        "unknown": ["unknown", "未知"], "fall": ["fall", "秋"], "spring": ["spring", "春"],
        "full_time": ["full-time", "全日制"], "part_time": ["part-time", "非全日制"]}
    return str(value).lower() in text or any(word in text for word in aliases.get(str(value), []))
