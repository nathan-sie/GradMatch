"""M4 shared tools, per-session LangGraph interrupts and bounded adaptive execution."""

from copy import deepcopy
from dataclasses import dataclass, field, replace
from decimal import Decimal
import hashlib
import json
import re
import traceback
from time import monotonic
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from pydantic import ValidationError, TypeAdapter

from gradmatch.agent_models import Action, AskArgs, Extraction, TOOL_ARGS, GROUP_FIELDS
from gradmatch.constraints import check_constraints
from gradmatch.providers import OpenAIProvider, ModelUnavailable
from gradmatch.ranking import RankingDraft, retrieve
from gradmatch.schemas import ProgramRecord, SourceRecord
from gradmatch.session import ROOT_FIELDS, LEAF_FIELDS, questions
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import validate_shortlist, changes_from_previous, data_hash
from gradmatch.validation import blocking_validation_errors
from gradmatch.web_reader import read_page, FetchError


class BudgetLimit(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass
class Task:
    strategy: str
    mode: str
    programs: list
    sources: dict
    limits: dict
    task_id: str = field(default_factory=lambda: str(uuid4()))
    evidence_version: int = 0
    tools: int = 0
    models: int = 0
    pages: int = 0
    turns: int = 0
    service_seconds: float = 0
    retrieved: list = field(default_factory=list)
    has_searched: bool = False
    reports: dict = field(default_factory=dict)
    checked_version: tuple | None = None
    draft: object = None
    validated: dict | None = None
    observations: list = field(default_factory=list)
    page_cache: dict = field(default_factory=dict)
    page_failures: dict = field(default_factory=dict)
    extraction_cache: dict = field(default_factory=dict)
    attempts: set = field(default_factory=set)
    attempt_counts: dict = field(default_factory=dict)
    live_receipts: list = field(default_factory=list)
    waiting: bool = False
    stopped: str | None = None
    profile_version: int = 0
    queued_action: object = None
    graph: object = None
    plan_state: object = None

    def summary(self):
        return dict(
            task_id=self.task_id,
            strategy=self.strategy,
            data_mode=self.mode,
            evidence_version=self.evidence_version,
            tool_calls=self.tools,
            model_calls=self.models,
            page_requests=self.pages,
            search_queries=0,
            turns=self.turns,
            service_seconds=round(self.service_seconds, 3),
            limits=self.limits,
            waiting_for_input=self.waiting,
            stop_reason=self.stopped,
            live_receipts=self.live_receipts,
            tool_log=self.observations,
            plan=self.plan_state.public() if self.plan_state is not None else None,
        )


class Execution:
    def __init__(self, task, session, settings, as_of, provider=None, fetcher=None):
        self.task, self.session, self.settings, self.as_of = (
            task,
            session,
            settings,
            as_of,
        )
        self.provider, self.fetcher = provider, fetcher or read_page
        self.started = monotonic()
        self.prepared_questions = []

    def remaining(self):
        elapsed = monotonic() - self.started
        return min(
            self.task.limits["turn_seconds"] - elapsed,
            self.task.limits["task_seconds"] - self.task.service_seconds - elapsed,
        )

    def time_check(self):
        if self.remaining() <= 0:
            raise BudgetLimit("SERVICE_TIME_LIMIT")

    def generate(self, output_type, purpose, payload, session):
        self.time_check()
        t = self.task
        if t.models >= t.limits["max_models"]:
            raise BudgetLimit("MODEL_CALL_LIMIT")
        # Check before incrementing; disabled/offline requests never pretend a model ran.
        if self.provider is None and not self.settings.ready:
            raise ModelUnavailable(
                "Enable model calls to run adaptive decisions. No model response was simulated."
            )
        if len(session.usage) >= self.settings.limits["max_model_calls_per_session"]:
            raise BudgetLimit("SESSION_MODEL_LIMIT")
        t.models += 1
        settings = replace(
            self.settings,
            limits={
                **self.settings.limits,
                "model_timeout_seconds": max(
                    0.05,
                    min(
                        self.settings.limits["model_timeout_seconds"], self.remaining()
                    ),
                ),
            },
        )
        provider = self.provider or OpenAIProvider(settings)
        value = provider.generate(output_type, purpose, payload, session)
        session.event(
            "model_output",
            task_id=t.task_id,
            purpose=purpose,
            output=value.model_dump(mode="json"),
        )
        self.time_check()
        return value

    def invalidate(self):
        t = self.task
        date_changed = t.validated is not None and t.validated.get("as_of_date") != str(
            self.as_of
        )
        evidence_changed = (
            t.checked_version is not None and t.checked_version[1] != t.evidence_version
        )
        if (
            t.profile_version != self.session.profile.profile_version
            or date_changed
            or evidence_changed
        ):
            t.profile_version = self.session.profile.profile_version
            t.reports = {}
            t.checked_version = None
            t.draft = None
            t.validated = None

    def page_budget(self):
        self.time_check()
        if self.task.pages >= self.task.limits["max_pages"]:
            raise BudgetLimit("PAGE_REQUEST_LIMIT")
        self.task.pages += 1

    def dispatch(self, name, arguments):
        t = self.task
        self.time_check()
        # One slot is always reserved for deterministic final validation.
        if t.tools >= t.limits["max_tools"] - (name != "validate_shortlist"):
            raise BudgetLimit("TOOL_CALL_LIMIT")
        t.tools += 1
        started = monotonic()
        before_models = t.models
        before_pages = t.pages
        usage_start = len(self.session.usage)
        result = {
            "ok": False,
            "data": {},
            "evidence_ids": [],
            "warnings": [],
            "error": None,
        }
        try:
            args = TOOL_ARGS[name].model_validate(arguments)
            key = canonical(
                [
                    name,
                    args.model_dump(mode="json"),
                    t.evidence_version,
                    self.session.profile.profile_version,
                    t.turns if name == "rank_programs" else None,
                    t.plan_state.replans
                    if name == "rank_programs" and t.plan_state is not None
                    else None,
                ]
            )
            if key in t.attempts and name not in {
                "validate_shortlist",
                "check_constraints",
            }:
                repair = (
                    name == "rank_programs"
                    and t.validated is not None
                    and blocking_validation_errors(t.validated)
                    and t.attempt_counts.get(key, 1) < 2
                )
                if not repair:
                    raise ValueError("REPEATED_ACTION")
            t.attempts.add(key)
            t.attempt_counts[key] = t.attempt_counts.get(key, 0) + 1
            data, ids, warnings = getattr(self, "tool_" + name)(args)
            result.update(ok=True, data=data, evidence_ids=ids, warnings=warnings)
        except BudgetLimit:
            result["error"] = {
                "code": "BUDGET_LIMIT",
                "message": "The cumulative task limit stopped this action.",
                "retryable": False,
            }
            raise
        except ModelUnavailable:
            result["error"] = {
                "code": "MODEL_OUTPUT_INVALID",
                "message": "No structured output was accepted for this action.",
                "retryable": False,
            }
            raise
        except (ValidationError, KeyError, TypeError):
            result["error"] = {
                "code": "INVALID_ARGUMENT",
                "message": "Use only registered tools and their typed current arguments.",
                "retryable": False,
            }
        except FetchError as error:
            result["error"] = {
                "code": error.code,
                "message": "Official page retrieval was unavailable; no missing fact was invented.",
                "retryable": False,
            }
        except ValueError as error:
            code = (
                str(error)
                if str(error)
                in {
                    "STALE_CHECKS",
                    "UNCHECKED_PROGRAMS",
                    "NO_DRAFT",
                    "REPEATED_ACTION",
                    "SNAPSHOT_MISS",
                    "SOURCE_NOT_REGISTERED",
                    "INVALID_EXTRACTION",
                    "UNKNOWN_PROGRAM",
                }
                else "INVALID_ARGUMENT"
            )
            result["error"] = {
                "code": code,
                "message": "The action was not accepted. Inspect the current observations before continuing.",
                "retryable": False,
            }
        finally:
            usage = self.session.usage[usage_start:]
            result["usage"] = {
                "tool_calls": 1,
                "model_calls": t.models - before_models,
                "page_requests": t.pages - before_pages,
                "search_queries": 0,
                "latency_ms": round((monotonic() - started) * 1000, 2),
                "model_call_ids": [u["call_id"] for u in usage],
                "input_tokens": sum(u["input_tokens"] for u in usage)
                if all(u.get("input_tokens") is not None for u in usage)
                else None,
                "output_tokens": sum(u["output_tokens"] for u in usage)
                if all(u.get("output_tokens") is not None for u in usage)
                else None,
                "estimated_cost_usd": str(
                    sum((Decimal(u["estimated_cost_usd"]) for u in usage), Decimal(0))
                )
                if all(u.get("estimated_cost_usd") is not None for u in usage)
                else None,
            }
            event = dict(
                tool=name,
                arguments=arguments,
                profile_version=self.session.profile.profile_version,
                evidence_version=t.evidence_version,
                result=deepcopy(result),
            )
            t.observations.append(event)
            self.session.event("tool_result", task_id=t.task_id, **event)
        self.time_check()
        return result

    def tool_search_programs(self, args):
        t = self.task
        allowed = {p.program_id for p in t.programs}
        if not set(args.program_ids) <= allowed:
            raise ValueError("UNKNOWN_PROGRAM")
        found = [
            p
            for p in retrieve(self.session.profile, t.programs, 10)
            if (not args.program_ids or p.program_id in args.program_ids)
            and (not args.discipline or p.discipline == args.discipline)
        ][: args.limit]
        t.has_searched = True
        t.retrieved = list(dict.fromkeys(t.retrieved + [p.program_id for p in found]))
        return (
            {
                "programs": [
                    {
                        "program_id": p.program_id,
                        "name": p.program_name,
                        "degree": p.degree,
                        "campus": p.campus,
                        "sources": [
                            {
                                "source_id": s.source_id,
                                "url": str(s.url),
                                "field_groups": s.field_groups,
                            }
                            for s in t.sources.values()
                            if s.program_id == p.program_id
                        ],
                        "missing_fields": [
                            g for g in GROUP_FIELDS if not p.field_sources.get(g)
                        ],
                    }
                    for p in found
                ],
                "evidence_version": t.evidence_version,
                "retrieval": "local_catalog",
                "external_search_used": False,
            },
            [],
            [],
        )

    def tool_fetch_official_page(self, args):
        t = self.task
        if t.mode != "live":
            raise ValueError("SNAPSHOT_MISS")
        program = next((p for p in t.programs if p.program_id == args.program_id), None)
        source = t.sources.get(args.source_id)
        if program is None or source is None or source.program_id != program.program_id:
            raise ValueError("SOURCE_NOT_REGISTERED")
        # Only existing catalog URLs can leave the process, never model-supplied query text or profiles.
        url = str(source.url)
        if url in t.page_failures:
            raise FetchError(t.page_failures[url])
        cache_hit = url in t.page_cache
        if not cache_hit:
            try:
                page = self.fetcher(
                    url,
                    program.allowed_official_hosts,
                    timeout=min(t.limits["page_seconds"], self.remaining()),
                    before_request=self.page_budget,
                )
            except FetchError as error:
                t.page_failures[url] = error.code
                raise
            t.page_cache[url] = page
        page = t.page_cache[url]
        extraction_key = canonical(
            [
                program.program_id,
                source.source_id,
                sorted(args.target_fields),
                page.raw_sha256,
                self.session.profile.intake.key
                if self.session.profile.intake
                else None,
            ]
        )
        if extraction_key in t.extraction_cache:
            data, ids, warnings = deepcopy(t.extraction_cache[extraction_key])
            data.update(cache_hit=True, evidence_version=t.evidence_version)
            return data, ids, warnings
        receipt = {
            "source_id": source.source_id,
            "program_id": program.program_id,
            **page.public(),
            "cache_hit": cache_hit,
            "extracted_source_ids": [],
            "warnings": [],
            "status": "read; extraction pending",
        }
        t.live_receipts.append(receipt)
        extraction = self.generate(
            Extraction,
            "extract",
            {
                "program_id": program.program_id,
                "program_identity": {
                    "university": program.university,
                    "name": program.program_name,
                    "degree": program.degree,
                    "campus": program.campus,
                },
                "target_fields": args.target_fields,
                "allowed_complete_bindings": {
                    g: sorted(GROUP_FIELDS[g]) for g in args.target_fields
                },
                "binding_value_schemas": {
                    g: {
                        key: TypeAdapter(
                            ProgramRecord.model_fields[key].annotation
                        ).json_schema()
                        for key in GROUP_FIELDS[g]
                    }
                    for g in args.target_fields
                },
                "as_of_date": str(self.as_of),
                "document_url": page.url,
                "document_text": page.text,
            },
            self.session,
        )
        if extraction.program_id != program.program_id:
            raise ValueError("INVALID_EXTRACTION")
        # Validate the complete batch before mutating any session evidence.
        proposals = []
        seen = set()
        for fact in extraction.facts:
            if (
                fact.group not in args.target_fields
                or fact.group in seen
                or fact.quote not in page.text
            ):
                raise ValueError("INVALID_EXTRACTION")
            seen.add(fact.group)
            bindings = json.loads(fact.bindings_json)
            if (
                not isinstance(bindings, dict)
                or set(bindings) != GROUP_FIELDS[fact.group]
            ):
                raise ValueError("INVALID_EXTRACTION")
            if fact.applicable_intake is not None and (
                not self.session.profile.intake
                or fact.applicable_intake != self.session.profile.intake.key
            ):
                raise ValueError("INVALID_EXTRACTION")
            document = program.model_dump(mode="json")
            document.update(bindings)
            candidate = ProgramRecord.model_validate(document)
            normalized = {
                key: candidate.model_dump(mode="json")[key] for key in bindings
            }
            # The scalar has to be present, not merely a number hallucinated next to a genuine quote.
            for key in ["required_credits"]:
                if key in normalized and normalized[key] is not None:
                    number = format(Decimal(str(normalized[key])).normalize(), "f")
                    if not re.search(
                        r"(?<![\d.])" + re.escape(number) + r"(?![\d.])", fact.quote
                    ):
                        raise ValueError("INVALID_EXTRACTION")
            existing = program.field_sources.get(fact.group, [])
            conflicts = [
                sid
                for sid in existing
                if t.sources[sid].verification_status == "conflict"
                or (
                    t.sources[sid].verification_status == "verified"
                    and t.sources[sid].applicable_intake
                    in {None, fact.applicable_intake}
                    and any(
                        program.model_dump(mode="json")[key] != value
                        for key, value in normalized.items()
                    )
                )
            ]
            sid = (
                "live-"
                + hashlib.sha256(
                    canonical(
                        [
                            program.program_id,
                            page.raw_sha256,
                            fact.model_dump(mode="json"),
                        ]
                    ).encode()
                ).hexdigest()[:24]
            )
            evidence = SourceRecord(
                source_id=sid,
                program_id=program.program_id,
                url=page.url,
                title=source.title,
                source_type=source.source_type,
                retrieved_at=page.retrieved_at,
                applicable_intake=fact.applicable_intake,
                effective_period=None,
                verification_status="conflict" if conflicts else "verified",
                field_groups=[fact.group],
                verified_values={fact.group: normalized},
                source_excerpt=fact.quote,
                fact_summary="Model-extracted official passage; typed bindings and exact quote validated. Semantic scope still needs review.",
                locator="Exact passage in bounded live document text",
                snapshot_path="session://" + sid,
                content_hash=page.text_sha256,
                raw_response_sha256=page.raw_sha256,
            )
            proposals.append((fact.group, normalized, evidence, conflicts))
        ids = []
        warnings = []
        for group, bindings, evidence, conflicts in proposals:
            t.sources[evidence.source_id] = evidence
            if conflicts:
                program.field_sources[group] = list(
                    dict.fromkeys(
                        program.field_sources.get(group, []) + [evidence.source_id]
                    )
                )
                warnings.append("SOURCE_CONFLICT:" + group)
            else:
                for key, value in bindings.items():
                    setattr(
                        program,
                        key,
                        ProgramRecord.model_validate(
                            {**program.model_dump(mode="json"), key: value}
                        ).__getattribute__(key),
                    )
                program.field_sources[group] = [evidence.source_id]
            ids.append(evidence.source_id)
        if proposals:
            t.evidence_version += 1
            t.reports = {}
            t.checked_version = None
            t.draft = None
            t.validated = None
        receipt.update(
            extracted_source_ids=ids,
            warnings=warnings,
            missing_fields=extraction.missing_fields,
            status="extraction validated",
        )
        output = (
            {
                "url": page.url,
                "retrieved_at": page.retrieved_at,
                "raw_sha256": page.raw_sha256,
                "cache_hit": cache_hit,
                "facts": [t.sources[sid].model_dump(mode="json") for sid in ids],
                "missing_fields": extraction.missing_fields,
                "evidence_version": t.evidence_version,
            },
            ids,
            warnings,
        )
        t.extraction_cache[extraction_key] = deepcopy(output)
        return output

    def current(self, args):
        t = self.task
        if (args.profile_version, args.evidence_version) != (
            self.session.profile.profile_version,
            t.evidence_version,
        ):
            raise ValueError("STALE_CHECKS")
        allowed = {p.program_id for p in t.programs}
        if not set(args.program_ids) <= allowed:
            raise ValueError("UNKNOWN_PROGRAM")
        return [p for p in t.programs if p.program_id in args.program_ids]

    def tool_check_constraints(self, args):
        programs = self.current(args)
        t = self.task
        t.retrieved = list(dict.fromkeys(t.retrieved + args.program_ids))
        t.reports.update(
            {
                p.program_id: check_constraints(
                    self.session.profile,
                    p,
                    t.sources,
                    as_of=self.as_of,
                    data_mode=t.mode,
                )
                for p in programs
            }
        )
        t.checked_version = (args.profile_version, args.evidence_version)
        return (
            {
                "reports": [
                    t.reports[p.program_id].model_dump(mode="json") for p in programs
                ]
            },
            [],
            [],
        )

    def tool_rank_programs(self, args):
        selected = self.current(args)
        t = self.task
        if t.checked_version != (
            args.profile_version,
            args.evidence_version,
        ) or not set(args.program_ids) <= set(t.reports):
            raise ValueError("UNCHECKED_PROGRAMS")
        reports = [t.reports[p.program_id] for p in selected]
        pairs = [
            (p, r) for p, r in zip(selected, reports) if r.hard_checks_status != "fail"
        ]
        payload = {
            "profile": self.session.profile.model_dump(mode="json"),
            "as_of_date": str(self.as_of),
            "programs": [p.model_dump(mode="json") for p, _ in pairs],
            "reports": [r.model_dump(mode="json") for _, r in pairs],
            "allowed_recommendation_program_ids": [
                p.program_id for p, r in pairs if r.recommendation_ready
            ],
            "ready_recommendation_options": [
                {
                    "program_id": p.program_id,
                    "goal_feature_ids": [
                        f.feature_id
                        for f in p.goal_features
                        if f.goal in {self.session.profile.goal, "mixed"}
                    ],
                    "tier_evidence_options": [
                        {
                            "evidence_id": e.evidence_id,
                            "permitted_tiers": e.permitted_tiers,
                        }
                        for e in p.admission_evidence
                        if e.reviewed
                    ],
                }
                for p, r in pairs
                if r.recommendation_ready
            ],
            "allowed_pending_program_ids": [p.program_id for p, _ in pairs],
            "excluded_summary": [
                r.model_dump(mode="json")
                for r in reports
                if r.hard_checks_status == "fail"
            ],
            "sources": [
                s.model_dump(mode="json")
                for s in t.sources.values()
                if s.program_id in args.program_ids
            ],
            "rubric": (PROJECT_ROOT / "config/ranking_rubric.md").read_text(
                encoding="utf-8"
            ),
            "all_catalog_retrieved": len(selected) == len(t.programs),
            "user_message": self.session.messages[-1]["content"]
            if self.session.messages
            else None,
            "referenced_program_ids": [],
        }
        t.draft = self.generate(RankingDraft, "rank", payload, self.session)
        t.validated = None
        return (
            {
                "draft": t.draft.model_dump(mode="json"),
                "next_step": "validate_shortlist",
            },
            [],
            [],
        )

    def current_state(self):
        t = self.task
        version = self.session.profile.profile_version
        checks_current = t.checked_version == (version, t.evidence_version)
        ranking_current = bool(
            t.draft is not None
            and t.draft.profile_version == version
            and checks_current
        )
        empty_search = t.has_searched and not t.retrieved
        validation_current = bool(
            t.validated is not None
            and t.validated.get("profile_version") == version
            and t.validated.get("evidence_version") == t.evidence_version
            and (ranking_current or empty_search)
        )
        return {
            "checks_current": checks_current,
            "checked_program_ids": sorted(t.reports),
            "ranking_current": ranking_current,
            "validation_current": validation_current,
            "finish_allowed": validation_current
            and not blocking_validation_errors(t.validated),
        }

    def tool_validate_shortlist(self, args, *, allow_unranked=False):
        t = self.task
        deterministic_only = self.provider is None and not self.settings.ready
        empty_search = t.has_searched and not t.retrieved
        if t.draft is None and not (
            allow_unranked or deterministic_only or empty_search
        ):
            raise ValueError("NO_DRAFT")
        selected = [p for p in t.programs if p.program_id in t.retrieved]
        t.validated = validate_shortlist(
            t.draft,
            self.session.profile,
            t.programs,
            selected,
            t.sources,
            as_of=self.as_of,
            data_mode=t.mode,
        )
        # An unvisited program is never silently presented as checked.
        t.validated.update(
            data_mode=t.mode,
            evidence_version=t.evidence_version,
            live_verified_at=max(
                (
                    r["retrieved_at"]
                    for r in t.live_receipts
                    if r["extracted_source_ids"]
                ),
                default=None,
            ),
            evidence_notice="Live mode supplements reviewed snapshots. Only sources in the live receipts were fetched for this task; other facts retain their recorded snapshot dates."
            if t.mode == "live"
            else "Reviewed snapshots only; no official page was fetched for this task.",
        )
        return t.validated, [], []

    def decision_context(self):
        t = self.task
        version = self.session.profile.profile_version
        observations = [
            o
            for o in t.observations
            if o["tool"] in {"search_programs", "fetch_official_page"}
            or (
                o["profile_version"] == version
                and o["evidence_version"] == t.evidence_version
            )
        ]
        messages = [
            m
            for m in self.session.messages
            if m["role"] != "assistant" or m.get("profile_version") == version
        ]
        prior = self.session.current_result or self.session.previous_result or {}
        return dict(
            profile=self.session.profile.model_dump(mode="json"),
            declared_unknown_fields=sorted(self.session.unknown_fields),
            messages=messages[-4:],
            previous_programs=[
                {"program_id": p["program_id"], "identity": p["identity"]}
                for p in prior.get("recommendations", [])
                + prior.get("pending_verification", [])
            ],
            catalog_index=[
                {
                    "program_id": p.program_id,
                    "identity": {
                        "university": p.university,
                        "program_name": p.program_name,
                        "degree": p.degree,
                        "campus": p.campus,
                    },
                    "sources": [
                        {"source_id": s.source_id, "field_groups": s.field_groups}
                        for s in t.sources.values()
                        if s.program_id == p.program_id
                    ],
                }
                for p in t.programs
            ],
            retrieved_program_ids=t.retrieved,
            data_mode=t.mode,
            evidence_version=t.evidence_version,
            task={"tool_calls": t.tools, "model_calls": t.models, "limits": t.limits},
            tools={
                name: model.model_json_schema() for name, model in TOOL_ARGS.items()
            },
            ask_user_schema=AskArgs.model_json_schema(),
            current_state=self.current_state(),
            observations=observations[-6:],
        )

    def choose(self, state):
        t = self.task
        if t.stopped:
            return {"route": "end"}
        self.time_check()
        self.invalidate()
        needed = questions(
            self.session.profile,
            t.programs,
            as_of=self.as_of,
            unknown_fields=self.session.unknown_fields,
        )
        if needed:
            self.session.pending_questions = needed
            return {"route": "ask", "question": needed}
        self.session.pending_questions = []
        if t.queued_action is not None:
            value = t.queued_action
            t.queued_action = None
            self.session.event(
                "agent_action_recovered",
                task_id=t.task_id,
                action=value.model_dump(mode="json"),
            )
            return {
                "route": "tool",
                "action": {
                    "tool": value.tool,
                    "arguments": json.loads(value.arguments_json),
                },
            }
        if self.provider is None and not self.settings.ready:
            # Offline use remains useful but is explicitly not an adaptive model run.
            if not t.retrieved:
                return {
                    "route": "tool",
                    "action": {"tool": "search_programs", "arguments": {}},
                }
            args = {
                "program_ids": t.retrieved,
                "profile_version": self.session.profile.profile_version,
                "evidence_version": t.evidence_version,
            }
            if t.checked_version != (args["profile_version"], args["evidence_version"]):
                return {
                    "route": "tool",
                    "action": {"tool": "check_constraints", "arguments": args},
                }
            if t.validated is None:
                return {
                    "route": "tool",
                    "action": {"tool": "validate_shortlist", "arguments": {}},
                }
            t.stopped = "finished"
            return {"route": "end"}
        if t.strategy == "fixed":
            return self.fixed_choice()
        if t.strategy == "plan":
            from gradmatch.planning import Planner

            return Planner(self).choose()
        version = self.session.profile.profile_version
        value = self.generate(Action, "act", self.decision_context(), self.session)
        self.session.event(
            "agent_action",
            task_id=t.task_id,
            action=value.model_dump(mode="json"),
            model_call_id=self.session.usage[-1]["call_id"]
            if self.session.usage
            else None,
        )
        args = json.loads(value.arguments_json)
        if value.tool == "ask_user":
            ask = AskArgs.model_validate(args)
            if not set(ask.requested_fields) <= ROOT_FIELDS | LEAF_FIELDS:
                raise ValueError("Unsupported applicant question")
            question = [
                {
                    "question_id": str(uuid4()),
                    "requested_fields": ask.requested_fields,
                    "text": ask.question,
                }
            ]
            self.session.pending_questions = question
            return {"route": "ask", "question": question}
        if value.tool == "finish":
            if t.validated is None and (
                t.draft is not None or (t.has_searched and not t.retrieved)
            ):
                self.dispatch("validate_shortlist", {})
            if not self.current_state()["finish_allowed"]:
                rejection = {
                    "tool": "finish",
                    "arguments": args,
                    "profile_version": version,
                    "evidence_version": t.evidence_version,
                    "result": {
                        "ok": False,
                        "data": {},
                        "evidence_ids": [],
                        "warnings": [],
                        "error": {
                            "code": "CURRENT_VALIDATION_REQUIRED",
                            "message": "The current profile/evidence needs new checks, ranking and validation before finish. Historical recommendations cannot complete this turn.",
                            "retryable": False,
                        },
                        "usage": {
                            "tool_calls": 0,
                            "model_calls": 0,
                            "page_requests": 0,
                            "search_queries": 0,
                        },
                    },
                }
                t.observations.append(rejection)
                self.session.event("action_rejected", task_id=t.task_id, **rejection)
                return {"route": "step"}
            t.stopped = "finished"
            return {"route": "end"}
        return {"route": "tool", "action": {"tool": value.tool, "arguments": args}}

    def fixed_choice(self):
        t = self.task
        # A fixed sequence, never selected or repaired by the model.
        if not t.retrieved:
            return {
                "route": "tool",
                "action": {"tool": "search_programs", "arguments": {}},
            }
        if t.mode == "live":
            plan = []
            for pid in t.retrieved:
                for group in ["tuition", "deadline", "gpa"]:
                    for s in list(t.sources.values()):
                        if (
                            s.program_id == pid
                            and not s.source_id.startswith("live-")
                            and group in s.field_groups
                        ):
                            plan.append(
                                {
                                    "program_id": pid,
                                    "source_id": s.source_id,
                                    "target_fields": [group],
                                }
                            )
            # Count attempts rather than successes: no adaptive retry or query expansion.
            attempted = sum(o["tool"] == "fetch_official_page" for o in t.observations)
            plan = plan[: t.limits["fixed_live_pages"]]
            if attempted < len(plan):
                return {
                    "route": "tool",
                    "action": {
                        "tool": "fetch_official_page",
                        "arguments": plan[attempted],
                    },
                }
        args = {
            "program_ids": t.retrieved,
            "profile_version": self.session.profile.profile_version,
            "evidence_version": t.evidence_version,
        }
        if t.checked_version != (args["profile_version"], args["evidence_version"]):
            return {
                "route": "tool",
                "action": {"tool": "check_constraints", "arguments": args},
            }
        if t.draft is None:
            return {
                "route": "tool",
                "action": {"tool": "rank_programs", "arguments": args},
            }
        if t.validated is None:
            return {
                "route": "tool",
                "action": {"tool": "validate_shortlist", "arguments": {}},
            }
        t.stopped = "finished"
        return {"route": "end"}

    def tool_node(self, state):
        action = state["action"]
        result = self.dispatch(action["tool"], action["arguments"])
        validation = None
        if action["tool"] == "rank_programs" and result["ok"]:
            validation = self.dispatch("validate_shortlist", {})
            if (
                not blocking_validation_errors(validation["data"])
                and self.task.strategy != "plan"
            ):
                self.task.stopped = "finished"
        if (
            action["tool"] == "validate_shortlist"
            and result["ok"]
            and not blocking_validation_errors(result["data"])
            and self.task.strategy != "plan"
        ):
            self.task.stopped = "finished"
        if self.task.strategy == "plan" and self.task.plan_state is not None:
            from gradmatch.planning import Planner

            Planner(self).observe(result, validation)
        return {"route": "step"}

    def build_graph(self):
        graph = StateGraph(dict)
        graph.add_node("step", lambda state: self.task.driver.choose(state))
        graph.add_node("tool", lambda state: self.task.driver.tool_node(state))
        # This node has no logging, paid requests, network reads or profile mutations.
        graph.add_node("ask", lambda state: {"reply": interrupt(state["question"])})
        graph.add_edge(START, "step")
        graph.add_conditional_edges(
            "step",
            lambda state: state["route"],
            {"ask": "ask", "tool": "tool", "step": "step", "end": END},
        )
        graph.add_edge("tool", "step")
        graph.add_edge("ask", "step")
        return graph.compile(checkpointer=InMemorySaver())


def run_task(
    session,
    *,
    request_id,
    programs,
    sources,
    settings,
    as_of,
    changes,
    unknown_fields,
    message,
    provider,
    strategy,
    data_mode,
    new_task,
    fetcher,
):
    from gradmatch.service import prepare_input, response_text

    if request_id in session.receipts:
        return session.receipts[request_id]
    if session.active:
        return {
            "status": "busy",
            "message": "A request is already running in this session.",
        }
    session.active = True
    started = monotonic()
    usage_start = len(session.usage)
    run_id = str(uuid4())
    task = session.agent_task
    if task is None or new_task or (task.strategy, task.mode) != (strategy, data_mode):
        task = Task(
            strategy,
            data_mode,
            deepcopy(programs),
            deepcopy(sources),
            json.loads((PROJECT_ROOT / "config/agent.json").read_text()),
        )
        session.agent_task = task
    driver = Execution(task, session, settings, as_of, provider, fetcher)
    tool_start = task.tools
    task.driver = driver
    if task.graph is None:
        task.graph = driver.build_graph()
    was_waiting = task.waiting
    session.event(
        "run_started",
        run_id=run_id,
        request_id=request_id,
        task_id=task.task_id,
        strategy=strategy,
        data_mode=data_mode,
    )
    result = None
    try:
        if task.turns >= task.limits["max_turns"]:
            raise BudgetLimit("INTERACTION_LIMIT")
        if task.stopped and task.stopped != "finished":
            raise BudgetLimit(task.stopped)
        task.turns += 1
        task.stopped = None
        if not was_waiting and strategy != "plan":
            task.checked_version = None
            task.reports = {}
            task.draft = None
            task.validated = None
        event_start = len(session.events)
        _, driver.input_intent = prepare_input(
            session,
            changes=changes,
            unknown_fields=unknown_fields,
            message=message,
            provider=driver,
            settings=settings,
        )
        driver.request_message = message
        driver.supplied_fields = set(changes or {})
        for event in session.events[event_start:]:
            if event.get("event_type") == "profile_patch":
                driver.supplied_fields.update(
                    name.split(".")[0]
                    for name in event["payload"].get("changed_fields", [])
                )
        driver.invalidate()
        output = task.graph.invoke(
            Command(resume={"profile_version": session.profile.profile_version})
            if was_waiting
            else {},
            config={
                "configurable": {
                    "thread_id": session.session_id
                    + ":"
                    + task.task_id
                    + ":"
                    + strategy
                },
                "recursion_limit": 100,
            },
        )
        task.waiting = bool(output.get("__interrupt__"))
        if task.waiting:
            result = {
                "status": "needs_input",
                "message": "Complete the requested applicant fields to resume this task. Progress and budgets are retained.",
                "pending_questions": session.pending_questions,
            }
        else:
            result = deepcopy(task.validated)
    except BudgetLimit as error:
        task.stopped = str(error)
        if strategy == "plan":
            from gradmatch.planning import Planner

            Planner(driver).stop(task.stopped)
        task.waiting = False
        # Final validation uses the reserved pure-code slot and cannot start a paid request.
        if task.tools < task.limits["max_tools"]:
            task.tools += 1
            driver.tool_validate_shortlist(None, allow_unranked=True)
            event = dict(
                tool="validate_shortlist",
                arguments={},
                profile_version=session.profile.profile_version,
                evidence_version=task.evidence_version,
                result={
                    "ok": True,
                    "data": deepcopy(task.validated),
                    "usage": {
                        "tool_calls": 1,
                        "model_calls": 0,
                        "page_requests": 0,
                        "search_queries": 0,
                    },
                },
            )
            task.observations.append(event)
            session.event("reserved_final_validation", task_id=task.task_id, **event)
        result = deepcopy(task.validated) if task.validated else {}
        result.update(
            status="budget_exhausted",
            message="The cumulative task budget was reached. Review the partial validated result or start a new task explicitly.",
        )
    except ModelUnavailable as error:
        if strategy == "plan":
            from gradmatch.planning import Planner

            Planner(driver).stop("MODEL_UNAVAILABLE")
        result = {"status": "error", "message": str(error)}
    except (ValueError, ValidationError, TypeError, KeyError) as error:
        session.event(
            "run_rejected",
            error_type=type(error).__name__,
            locations=[
                {"function": f.name, "line": f.lineno}
                for f in traceback.extract_tb(error.__traceback__)[-5:]
            ],
        )
        result = {
            "status": "error",
            "message": "An action or profile input was invalid. No unvalidated result was displayed.",
        }
    finally:
        task.service_seconds += monotonic() - started
        session.active = False
    if result is None:
        result = {"status": "stopped", "message": "No validated result was produced."}
    result.update(
        request_id=request_id,
        run_id=run_id,
        task_id=task.task_id,
        strategy=strategy,
        data_mode=data_mode,
        profile_version=session.profile.profile_version,
        usage=session.usage[usage_start:],
        model_calls=len(session.usage) - usage_start,
        model_status="completed"
        if any(u.get("response_id") for u in session.usage[usage_start:])
        else "test_stub"
        if provider is not None
        else "not_configured",
        pending_questions=session.pending_questions if task.waiting else [],
        service_latency_ms=round((monotonic() - started) * 1000, 2),
        model_config=settings.public(),
        task_usage=task.summary(),
    )
    if (
        strategy == "plan"
        and task.stopped == "finished"
        and not result["model_calls"]
        and task.plan_state is not None
        and task.plan_state.revisions
        and task.plan_state.revisions[-1]["status"] == "completed"
        and task.tools == tool_start
        and task.plan_state.revisions[-1]["profile_version"]
        == session.profile.profile_version
        and task.plan_state.revisions[-1]["evidence_version"] == task.evidence_version
        and task.plan_state.revisions[-1]["as_of_date"] == str(as_of)
    ):
        result["model_status"] = (
            "test_stub" if provider is not None else "reused_validated"
        )
        result["message"] = (
            "The current plan and validated result were reused. No new model request was made."
        )
    if result["status"] == "error" and result["usage"]:
        result["model_status"] = "error"
    if (
        provider is None
        and not settings.ready
        and result["model_status"] != "reused_validated"
    ):
        result["message"] = (
            "Deterministic checks only. Adaptive decisions and live extraction have not run; enable model calls to use them."
        )
    if "recommendations" in result:
        result["changes_from_previous"] = changes_from_previous(
            session.current_result or session.previous_result, result
        )
        result["profile_summary"] = session.profile.model_dump(mode="json")
        result["data_hash"] = data_hash(task.programs, task.sources)
        session.previous_result = session.current_result or session.previous_result
        session.current_result = result
    session.receipts[request_id] = result
    session.messages.append(
        {
            "role": "assistant",
            "content": response_text(result),
            "profile_version": session.profile.profile_version,
            "run_id": run_id,
        }
    )
    session.event(
        "output_finalized", run_id=run_id, status=result["status"], task_id=task.task_id
    )
    return result
