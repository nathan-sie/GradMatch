"""Model-authored plans, code-checked steps and observation-triggered revisions."""

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field

from gradmatch.agent_models import Group
from gradmatch.constraints import evidence_ids
from gradmatch.schemas import Record
from gradmatch.session import LEAF_FIELDS, ROOT_FIELDS

Criterion = Literal[
    "candidates_available",
    "source_reviewed",
    "constraints_current",
    "ranking_current",
    "validation_current",
    "user_input_received",
]


class PlanStep(Record):
    step_id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    tool: Literal[
        "search_programs",
        "fetch_official_page",
        "check_constraints",
        "rank_programs",
        "validate_shortlist",
        "ask_user",
    ]
    program_ids: list[str] = Field(max_length=10)
    target_fields: list[Group] = Field(max_length=4)
    source_id: str | None
    depends_on: list[str] = Field(max_length=6)
    status: Literal["pending"]
    done_criteria: list[Criterion] = Field(min_length=1, max_length=2)
    requested_fields: list[str] = Field(max_length=6)
    question: str | None = Field(max_length=500)


class PlanDraft(Record):
    summary: str = Field(min_length=1, max_length=1000)
    steps: list[PlanStep] = Field(min_length=3, max_length=6)


CRITERION = {
    "search_programs": "candidates_available",
    "fetch_official_page": "source_reviewed",
    "check_constraints": "constraints_current",
    "rank_programs": "ranking_current",
    "validate_shortlist": "validation_current",
    "ask_user": "user_input_received",
}


@dataclass
class PlanState:
    revisions: list = field(default_factory=list)
    replans: int = 0
    pending_trigger: dict | None = None
    active_step_id: str | None = None
    request_key: str | None = None

    def public(self):
        return deepcopy(
            dict(
                replans=self.replans,
                revisions=self.revisions,
                pending_trigger=self.pending_trigger,
                active_step_id=self.active_step_id,
            )
        )


class Planner:
    def __init__(self, execution):
        self.e = execution
        self.t = execution.task
        self.session = execution.session
        if self.t.plan_state is None:
            self.t.plan_state = PlanState()
        self.state = self.t.plan_state

    @property
    def revision(self):
        return self.state.revisions[-1] if self.state.revisions else None

    def event(self, kind, **values):
        self.session.event(kind, task_id=self.t.task_id, **deepcopy(values))

    def trigger(self, reason, **detail):
        if self.state.pending_trigger is None:
            self.state.pending_trigger = {"reason_code": reason, "detail": detail}
            self.event("plan_trigger", **self.state.pending_trigger)

    def validate(self, draft):
        known = {p.program_id for p in self.t.programs}
        seen = {}
        ancestors = {}
        tools = [s.tool for s in draft.steps]
        if tools.count("rank_programs") != 1 or tools.count("validate_shortlist") != 1:
            raise ValueError("ONE_RANK_AND_VALIDATION_REQUIRED")
        if tools[-1] != "validate_shortlist" or any(
            t
            in {
                "ask_user",
                "fetch_official_page",
                "search_programs",
                "check_constraints",
            }
            for t in tools[tools.index("rank_programs") + 1 :]
        ):
            raise ValueError("RANK_THEN_FINAL_VALIDATION_REQUIRED")
        for step in draft.steps:
            if step.step_id in seen or len(step.depends_on) != len(
                set(step.depends_on)
            ):
                raise ValueError("DUPLICATE_STEP_OR_DEPENDENCY")
            if not set(step.depends_on) <= set(seen):
                raise ValueError("DEPENDENCY_MUST_PRECEDE_STEP")
            if not set(step.program_ids) <= known or len(step.program_ids) != len(
                set(step.program_ids)
            ):
                raise ValueError("UNKNOWN_OR_DUPLICATE_PROGRAM")
            if step.done_criteria != [CRITERION[step.tool]]:
                raise ValueError("INVALID_DONE_CRITERIA")
            prior = set(step.depends_on)
            for dep in step.depends_on:
                prior.update(ancestors[dep])
            ancestors[step.step_id] = prior
            if step.tool == "rank_programs" and not any(
                seen[d].tool == "check_constraints" for d in prior
            ):
                raise ValueError("RANK_DEPENDS_ON_CHECKS")
            if step.tool == "validate_shortlist" and not any(
                seen[d].tool == "rank_programs" for d in prior
            ):
                raise ValueError("VALIDATION_DEPENDS_ON_RANK")
            if step.tool == "fetch_official_page":
                source = self.t.sources.get(step.source_id)
                if self.t.mode != "live":
                    raise ValueError("FETCH_NOT_ALLOWED_IN_SNAPSHOT")
                if (
                    len(step.program_ids) != 1
                    or not step.target_fields
                    or source is None
                    or source.program_id != step.program_ids[0]
                ):
                    raise ValueError("UNREGISTERED_PLAN_SOURCE")
            elif step.source_id is not None:
                raise ValueError("SOURCE_ONLY_FOR_FETCH")
            if step.tool == "ask_user":
                if (
                    not step.question
                    or not step.requested_fields
                    or not set(step.requested_fields) <= ROOT_FIELDS | LEAF_FIELDS
                ):
                    raise ValueError("INVALID_APPLICANT_QUESTION")
            elif step.question is not None or step.requested_fields:
                raise ValueError("QUESTION_ONLY_FOR_ASK")
            seen[step.step_id] = step

    def make_revision(self, reason, detail):
        from gradmatch.agent import BudgetLimit

        if self.revision is not None:
            if self.state.replans >= self.t.limits.get("max_replans", 3):
                raise BudgetLimit("REPLAN_LIMIT")
            self.state.replans += 1
        revision_no = self.state.replans
        context = self.e.decision_context()
        context.update(
            trigger={"reason_code": reason, "detail": detail},
            plan_history=self.state.public()["revisions"],
            plan_contract="3-6 pending steps. Empty program_ids binds to the retrieved scope. One rank step after checks, one validation after rank. No arbitrary code or URLs.",
        )
        draft = self.e.generate(PlanDraft, "plan", context, self.session)
        record = {
            "revision": revision_no,
            "reason_code": reason,
            "reason_detail": detail,
            "summary": draft.summary,
            "profile_version": self.session.profile.profile_version,
            "evidence_version": self.t.evidence_version,
            "initial_evidence_version": self.t.evidence_version,
            "as_of_date": str(self.e.as_of),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model_call_id": self.session.usage[-1]["call_id"]
            if self.session.usage
            else None,
            "status": "running",
            "steps": [s.model_dump(mode="json") for s in draft.steps],
        }
        for step in record["steps"]:
            step["result_refs"] = []
        invalid = None
        try:
            self.validate(draft)
        except ValueError as error:
            invalid = str(error)
            record.update(status="invalid", error_code=invalid)
        if self.revision:
            self.revision["status"] = "superseded"
            for step in self.revision["steps"]:
                if step["status"] in {"pending", "running"}:
                    step["status"] = "skipped"
        self.state.revisions.append(record)
        self.state.pending_trigger = None
        self.state.active_step_id = None
        self.event(
            "plan_created" if revision_no == 0 else "plan_revised", revision=record
        )
        if invalid:
            self.trigger("PLAN_INVALID", error_code=invalid)
            return
        # A new plan never inherits an old ranking or current-check assertion.
        self.t.reports = {}
        self.t.checked_version = None
        self.t.draft = None
        self.t.validated = None

    def active(self):
        return (
            next(
                (
                    s
                    for s in self.revision["steps"]
                    if s["step_id"] == self.state.active_step_id
                ),
                None,
            )
            if self.revision
            else None
        )

    def complete(self, step, refs=()):
        step["status"] = "done"
        step["result_refs"] = list(refs)
        self.event(
            "plan_step_completed",
            revision=self.revision["revision"],
            step_id=step["step_id"],
            done_criteria=step["done_criteria"],
            result_refs=list(refs),
        )
        self.state.active_step_id = None

    def arguments(self, step):
        tool = step["tool"]
        scope = step["program_ids"] or self.t.retrieved
        if tool == "search_programs":
            return {
                "program_ids": step["program_ids"],
                "target_fields": step["target_fields"],
                "limit": 10,
            }
        if tool == "fetch_official_page":
            return {
                "program_id": scope[0],
                "source_id": step["source_id"],
                "target_fields": step["target_fields"],
            }
        if tool in {"check_constraints", "rank_programs"}:
            return {
                "program_ids": scope,
                "profile_version": self.session.profile.profile_version,
                "evidence_version": self.t.evidence_version,
            }
        return {}

    def choose(self):
        self.e.time_check()
        active = self.active()
        if active and active["tool"] == "ask_user" and active["status"] == "running":
            fields = {name.split(".")[0] for name in active["requested_fields"]}
            supplied = set(getattr(self.e, "supplied_fields", ()))
            if fields <= supplied | self.session.unknown_fields:
                self.complete(active)
        if self.revision:
            if self.revision["profile_version"] != self.session.profile.profile_version:
                self.trigger(
                    "PROFILE_UPDATED",
                    old_version=self.revision["profile_version"],
                    new_version=self.session.profile.profile_version,
                )
            elif self.revision["as_of_date"] != str(self.e.as_of):
                self.trigger("ASSESSMENT_DATE_CHANGED", as_of_date=str(self.e.as_of))
            elif self.revision["evidence_version"] != self.t.evidence_version:
                self.trigger(
                    "EVIDENCE_CHANGED", evidence_version=self.t.evidence_version
                )
        message = getattr(self.e, "request_message", None)
        intent = getattr(self.e, "input_intent", None)
        if (
            message
            and intent not in {"update_profile", "answer_question"}
            and message.lower().strip()
            not in {"generate", "generate recommendations", "rerun checks"}
        ):
            key = " ".join(message.split())
            if self.revision is not None and key != self.state.request_key:
                self.trigger("USER_REQUEST_UPDATED")
            self.state.request_key = key
        if self.revision is None:
            self.make_revision("INITIAL_PLAN", {})
        elif self.state.pending_trigger:
            trigger = self.state.pending_trigger
            self.make_revision(trigger["reason_code"], trigger["detail"])
        if self.state.pending_trigger:
            return {"route": "step"}
        for step in self.revision["steps"]:
            if step["status"] == "done":
                continue
            if step["status"] == "failed":
                self.trigger(
                    "TOOL_FAILURE",
                    step_id=step["step_id"],
                    error_code=step.get("error_code"),
                )
                return {"route": "step"}
            done = {
                s["step_id"] for s in self.revision["steps"] if s["status"] == "done"
            }
            if not set(step["depends_on"]) <= done:
                self.trigger("PLAN_INVALID", error_code="DEPENDENCY_NOT_DONE")
                return {"route": "step"}
            if (
                step["tool"] == "validate_shortlist"
                and self.e.current_state()["validation_current"]
            ):
                if self.t.validated["validation_errors"]:
                    self.trigger(
                        "VALIDATION_FAILED",
                        errors=self.t.validated["validation_errors"],
                    )
                    return {"route": "step"}
                refs = [
                    i
                    for i, o in enumerate(self.t.observations)
                    if o["tool"] == "validate_shortlist"
                    and o["profile_version"] == self.session.profile.profile_version
                    and o["evidence_version"] == self.t.evidence_version
                    and o["result"]["ok"]
                ]
                self.complete(step, refs[-1:])
                continue
            if step["status"] != "running":
                step["status"] = "running"
                self.state.active_step_id = step["step_id"]
                self.event(
                    "plan_step_started",
                    revision=self.revision["revision"],
                    step_id=step["step_id"],
                    tool=step["tool"],
                )
            if step["tool"] == "ask_user":
                question = [
                    {
                        "question_id": f"plan_{self.revision['revision']}_{step['step_id']}",
                        "requested_fields": step["requested_fields"],
                        "text": step["question"],
                    }
                ]
                self.session.pending_questions = question
                return {"route": "ask", "question": question}
            return {
                "route": "tool",
                "action": {"tool": step["tool"], "arguments": self.arguments(step)},
            }
        if not self.e.current_state()["finish_allowed"]:
            self.trigger("VALIDATION_FAILED", error_code="CURRENT_VALIDATION_REQUIRED")
            return {"route": "step"}
        self.revision["status"] = "completed"
        self.t.stopped = "finished"
        return {"route": "end"}

    def observe(self, result, validation=None):
        step = self.active()
        if step is None:
            return
        failure = None
        detail = {}
        if not result["ok"]:
            failure = "TOOL_FAILURE"
            detail = {"error_code": result["error"]["code"]}
        elif any(w.startswith("SOURCE_CONFLICT") for w in result.get("warnings", [])):
            failure = "SOURCE_CONFLICT"
            detail = {"warnings": result["warnings"]}
        elif step["tool"] == "fetch_official_page":
            groups = {
                g for f in result["data"].get("facts", []) for g in f["field_groups"]
            }
            if not set(step["target_fields"]) <= groups:
                failure = "MISSING_EVIDENCE"
                detail = {"fields": sorted(set(step["target_fields"]) - groups)}
        elif step["tool"] == "search_programs" and not result["data"]["programs"]:
            failure = "MISSING_EVIDENCE"
            detail = {"error_code": "NO_CANDIDATES"}
        elif (
            step["tool"] == "check_constraints"
            and self.t.mode == "live"
            and step["target_fields"]
        ):
            scope = step["program_ids"] or self.t.retrieved
            missing = []
            for p in self.t.programs:
                if p.program_id not in scope:
                    continue
                report = self.t.reports[p.program_id]
                for group in step["target_fields"]:
                    check = next((c for c in report.checks if c.rule_id == group), None)
                    # Applicant scale/scope mismatches and future-price uncertainty are
                    # not source gaps. A per-credit tuition check also needs credits.
                    missing_source = not evidence_ids(
                        p, group, self.t.sources, self.session.profile
                    )
                    if (
                        group == "tuition"
                        and check
                        and check.reason_code
                        in {
                            "MISSING_TUITION_EVIDENCE",
                            "MISSING_TOTAL_UNITS",
                            "MISSING_RATE",
                        }
                    ):
                        missing_source = True
                    if missing_source:
                        missing.append({"program_id": p.program_id, "field": group})
            index = self.revision["steps"].index(step)
            planned = {
                (pid, g)
                for s in self.revision["steps"][index + 1 :]
                if s["tool"] == "fetch_official_page"
                for pid in s["program_ids"]
                for g in s["target_fields"]
            }
            missing = [
                m
                for m in missing
                if (m["program_id"], m["field"]) not in planned
                and not (
                    m["field"] == "tuition" and (m["program_id"], "credits") in planned
                )
            ]
            if missing:
                failure = "MISSING_EVIDENCE"
                detail = {"missing": missing}
        if validation and (
            not validation["ok"] or validation["data"]["validation_errors"]
        ):
            failure = "VALIDATION_FAILED"
            detail = {"errors": validation["data"].get("validation_errors", [])}
        criterion = {
            "check_constraints": "checks_current",
            "rank_programs": "ranking_current",
            "validate_shortlist": "validation_current",
        }.get(step["tool"])
        if not failure and criterion and not self.e.current_state()[criterion]:
            failure = "DONE_CRITERIA_FAILED"
            detail = {"criterion": criterion}
        self.revision["evidence_version"] = self.t.evidence_version
        if failure:
            step.update(status="failed", error_code=failure)
            self.trigger(failure, step_id=step["step_id"], **detail)
        else:
            self.complete(
                step, [len(self.t.observations) - 1 - (1 if validation else 0)]
            )

    def stop(self, reason):
        if self.revision:
            self.revision["status"] = "stopped"
            for step in self.revision["steps"]:
                if step["status"] in {"pending", "running"}:
                    step.update(status="blocked", error_code=reason)
        self.event("plan_stopped", reason_code=reason)
