"""Shared UI/CLI task entry: patch -> questions -> fixed retrieval -> rank once -> validate."""

from datetime import date
from decimal import Decimal
import json
import re
from time import monotonic
from uuid import uuid4

from pydantic import ValidationError

from gradmatch.constraints import check_constraints
from gradmatch.providers import ModelUnavailable, OpenAIProvider
from gradmatch.ranking import RankingDraft, retrieve
from gradmatch.schemas import GPA
from gradmatch.session import (
    LEAF_FIELDS, ROOT_FIELDS, PatchOperation, ProfilePatch, Session, apply_patch, explanation_only, questions, quick_patch,
)
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import changes_from_previous, data_hash, validate_shortlist
BROAD_ENGINE_VERSION = 5
_DEFAULT_HISTORY = object()


class GPACommandError(ValueError):
    """A direct score update needs a valid saved GPA scale and scope."""


def gpa_patch(message: str, current: GPA | None) -> ProfilePatch | None:
    match = re.fullmatch(
        r"\s*(?:change|set|update)\s+(?:(?:my|the)\s+)?gpa\s+to\s+(-?\d+(?:\.\d+)?)\s*[.!。]?\s*",
        message, re.I | re.ASCII,
    )
    if match is None:
        return None
    if current is None:
        raise GPACommandError("Enter your GPA, original scale, and calculation scope in Applicant information before updating the score in chat.")
    value = Decimal(match.group(1))
    if not 0 <= value <= current.scale:
        raise GPACommandError(f"Enter a GPA between 0 and {current.scale:g} on the saved GPA scale.")
    if value == current.value:
        value = current.value
    return ProfilePatch(
        intent="update_profile",
        operations=[PatchOperation(field="gpa.value", value_json=json.dumps(str(value)), explicit_span=message)],
        referenced_program_ids=[],
        ambiguous_fields=[],
    )


def prepare_input(session, *, changes, unknown_fields, message, provider, settings):
    """Shared explicit input boundary; tools never call this function."""
    references = []
    input_intent = None
    if changes is not None:
        session.update(changes, unknown_fields=unknown_fields)
    if message is not None:
        if not message.strip() or len(message) > settings.limits["max_message_characters"]:
            raise ValueError("Enter a message between 1 and 4,000 characters.")
        session.messages.append({"role": "user", "content": message})
        patch = gpa_patch(message, session.profile.gpa) or quick_patch(message)
        # Explicit read-only requests need no paid mutation interpreter in any strategy.
        marker=r"\b(?:do not|don't) (?:change|modify|update) my profile\b"
        remainder=re.sub(marker,'',message.lower())
        if re.search(marker,message.lower()) and not re.search(r'\b(change|set|update|increase|decrease|lower|raise|switch|replace)\b',remainder):
            prior=session.current_result or session.previous_result or {}
            known=prior.get('recommendations',[])+prior.get('preliminary_recommendations',[])+prior.get('pending_verification',[])
            patch=ProfilePatch(intent='explain_previous',operations=[],ambiguous_fields=[],
                referenced_program_ids=[p['program_id'] for p in known if p['program_id'] in message])
        if patch is None and message.lower().strip() not in {"generate", "generate recommendations", "rerun checks"}:
            if not settings.ready and isinstance(provider, OpenAIProvider):
                raise ModelUnavailable("Free-text interpretation needs the configured model. You can still edit the profile form or use 'Change my GPA to 3.8' or 'Change my tuition budget to 50000'.")
            prior = session.current_result or session.previous_result or {}
            known = prior.get("recommendations", []) + prior.get('preliminary_recommendations', []) + prior.get("pending_verification", [])
            patch = provider.generate(ProfilePatch, "interpret", {"message": message,
                "profile": session.profile.model_dump(mode="json"), "pending_questions": session.pending_questions,
                "previous_programs": [{"program_id": p["program_id"], "identity": p["identity"]} for p in known],
                "allowed_leaf_fields": sorted(LEAF_FIELDS)}, session)
            allowed_references = {p["program_id"] for p in known}
            if not set(patch.referenced_program_ids) <= allowed_references:
                raise ValueError("That program reference is not in the previous result. Please use its exact program name.")
            if not patch.operations and patch.intent in {"update_profile", "answer_question"}:
                if not patch.ambiguous_fields and explanation_only(message):
                    patch.intent = "explain_previous"
                else:
                    raise ValueError("No unambiguous supported change was found. Please use the profile form.")
        if patch is not None:
            if not patch.operations and patch.intent=='explain_previous':
                invalid=[f for f in patch.ambiguous_fields if f not in ROOT_FIELDS|LEAF_FIELDS]
                if invalid:
                    session.event('catalog_ambiguity_deferred',fields=invalid)
                    patch.ambiguous_fields=[f for f in patch.ambiguous_fields if f in ROOT_FIELDS|LEAF_FIELDS]
            input_intent = patch.intent
            # Budget scope was established by the explicitly labelled form. Never reinterpret a total/living-cost budget.
            lower = message.lower()
            if any(op.field == "tuition_budget_usd" for op in patch.operations) and any(
                    word in lower for word in ["living", "total budget", "cny", "rmb", "eur", "人民币", "生活费", "总预算"]):
                raise ValueError("Please state a tuition-only budget in USD, excluding living costs. No budget change was applied.")
            apply_patch(session, patch, message)
            references = patch.referenced_program_ids
    return references, input_intent


def answer_catalog_question(session, question, *, message, request_id, programs, sources,
                            settings, as_of, strategy, broad_context):
    from gradmatch.program_questions import catalog_answer

    if request_id in session.receipts:
        return session.receipts[request_id]
    if session.active:
        return {"status": "busy", "message": "A request is already running in this session."}

    started, run_id = monotonic(), str(uuid4())
    previous_id = session.messages[-1].get("catalog_program_id") if session.messages else None
    topic, name = question
    session.active = True
    try:
        answer, program_id, citations = catalog_answer(
            topic, name, programs, sources, session.profile, as_of, broad_context, previous_id,
        )
        result = {
            "status": "catalog_answer", "message": answer, "topic": topic, "program_id": program_id,
            "citations": citations, "request_id": request_id, "run_id": run_id,
            "strategy": strategy, "data_mode": "snapshot", "profile_version": session.profile.profile_version,
            "usage": [], "model_calls": 0, "model_status": "catalog_lookup", "model_config": settings.public(),
            "service_latency_ms": round((monotonic() - started) * 1000, 2),
        }
        session.messages.extend([
            {"role": "user", "content": message},
            {"role": "assistant", "content": answer, "catalog_program_id": program_id,
             "topic": topic, "profile_version": session.profile.profile_version, "run_id": run_id},
        ])
        session.receipts[request_id] = result
        session.event("catalog_answered", run_id=run_id, topic=topic, program_id=program_id,
                      source_ids=[row["source_id"] for row in citations], model_calls=0)
        return result
    finally:
        session.active = False


def start_task(session: Session, *, request_id: str, programs, sources, settings, as_of: date,
               changes=None, unknown_fields=None, message=None, provider=None,
               strategy=None, data_mode="snapshot", new_task=False, fetcher=None, recommendation_scope='reviewed',
               history_preview=_DEFAULT_HISTORY):
    if recommendation_scope not in {'reviewed', 'broad'}:
        raise ValueError('Unsupported recommendation scope.')
    broad_context = None
    if recommendation_scope == 'broad':
        from gradmatch.admission_history import load_bundled_preview
        from gradmatch.broad_catalog import build_broad_catalog
        programs, broad_context = build_broad_catalog(programs, sources)
        if history_preview is _DEFAULT_HISTORY:
            history_preview = load_bundled_preview()
    legacy=strategy is None and data_mode=='snapshot' and broad_context is None
    strategy=strategy or 'fixed'
    if strategy not in {"fixed", "react", "plan"} or data_mode not in {"snapshot", "live"}:
        raise ValueError("Unsupported execution strategy or data mode.")
    if (message and changes is None and unknown_fields is None
            and len(message) <= settings.limits["max_message_characters"]):
        from gradmatch.program_questions import parse_catalog_question
        if question := parse_catalog_question(message):
            return answer_catalog_question(session, question, message=message, request_id=request_id,
                programs=programs, sources=sources, settings=settings, as_of=as_of,
                strategy=strategy, broad_context=broad_context)
    if not legacy:
        from gradmatch.agent import run_task
        return run_task(session, request_id=request_id, programs=programs, sources=sources, settings=settings,
            as_of=as_of, changes=changes, unknown_fields=unknown_fields, message=message, provider=provider,
            strategy=strategy, data_mode=data_mode, new_task=new_task, fetcher=fetcher, broad_context=broad_context,
            history_preview=history_preview if broad_context else None)
    if request_id in session.receipts:
        return session.receipts[request_id]
    if session.active:
        return {"status": "busy", "message": "A request is already running in this session."}
    session.active = True
    started, usage_start = monotonic(), len(session.usage)
    run_id = str(uuid4())
    provider = provider or OpenAIProvider(settings)
    references = []
    input_intent = None
    session.event("run_started", run_id=run_id, request_id=request_id, strategy="fixed")
    result = None
    try:
        references, input_intent = prepare_input(session, changes=changes, unknown_fields=unknown_fields,
            message=message, provider=provider, settings=settings)
        needed = questions(session.profile, programs, as_of=as_of, unknown_fields=session.unknown_fields)
        session.pending_questions = needed
        if needed:
            result = {"status": "needs_input", "profile_version": session.profile.profile_version,
                "pending_questions": needed, "model_status": "not_run_waiting_for_input",
                "message": "Please complete the missing fields, or explicitly mark unavailable information as unknown in the form."}
            session.event("question_asked", requested_fields=[field for q in needed for field in q["requested_fields"]])
        else:
            retrieved = retrieve(session.profile, programs, settings.limits["baseline_top_k"])
            retrieved_ids = {p.program_id for p in retrieved}
            retrieved_sources = {sid: source for sid, source in sources.items() if source.program_id in retrieved_ids}
            reports = [check_constraints(session.profile, p, retrieved_sources, as_of=as_of) for p in retrieved]
            ranking_pairs = [(p, r) for p, r in zip(retrieved, reports) if r.hard_checks_status != "fail"]
            session.event("fixed_retrieval", program_ids=[p.program_id for p in retrieved], top_k=settings.limits["baseline_top_k"])
            draft, model_error = None, None
            model_status = "not_configured"
            if settings.ready or not isinstance(provider, OpenAIProvider):
                if len(session.usage) - usage_start >= settings.limits["max_model_calls_per_turn"]:
                    raise ModelUnavailable("The per-turn model-call limit has been reached.")
                try:
                    draft = provider.generate(RankingDraft, "rank", {
                        "profile": session.profile.model_dump(mode="json"), "as_of_date": str(as_of),
                        "user_message": message, "referenced_program_ids": references,
                        "programs": [p.model_dump(mode="json") for p, _ in ranking_pairs],
                        "reports": [r.model_dump(mode="json") for _, r in ranking_pairs],
                        "allowed_recommendation_program_ids": [p.program_id for p,r in ranking_pairs if r.recommendation_ready],
                        "ready_recommendation_options": [{"program_id":p.program_id,
                            "goal_feature_ids":[f.feature_id for f in p.goal_features if f.goal in {session.profile.goal,"mixed"}],
                            "tier_evidence_options":[{"evidence_id":e.evidence_id,"permitted_tiers":e.permitted_tiers}
                                for e in p.admission_evidence if e.reviewed]}
                            for p,r in ranking_pairs if r.recommendation_ready],
                        "allowed_pending_program_ids": [p.program_id for p, _ in ranking_pairs],
                        "excluded_summary": [{"program_id": r.program_id,
                            "failed_checks": [c.model_dump(mode="json") for c in r.checks if c.status == "fail"]}
                            for r in reports if r.hard_checks_status == "fail"],
                        "sources": [{"source_id": s.source_id, "program_id": s.program_id,
                            "field_groups": s.field_groups, "verified_values": s.verified_values,
                            "source_excerpt": s.source_excerpt, "fact_summary": s.fact_summary,
                            "applicable_intake": s.applicable_intake} for s in retrieved_sources.values()],
                        "all_catalog_retrieved": len(retrieved) == len(programs),
                        "rubric": (PROJECT_ROOT / "config" / "ranking_rubric.md").read_text(encoding="utf-8")}, session)
                    model_status = "completed" if isinstance(provider, OpenAIProvider) else "test_stub"
                    session.event("ranking_draft", draft=draft.model_dump(mode="json"))
                except ModelUnavailable as error:
                    model_error, model_status = str(error), "error"
            result = validate_shortlist(draft, session.profile, programs, retrieved, retrieved_sources, as_of=as_of)
            result["data_hash"] = data_hash(programs, sources)
            result["model_status"] = model_status
            result["evidence_status"] = result["status"]
            if model_error:
                result.update(status="error", message=model_error)
            elif model_status == "not_configured":
                result["message"] = "Deterministic checks only. The model has not run; configure the local API key and enable model calls to generate a model-backed result."
            result["changes_from_previous"] = changes_from_previous(session.current_result or session.previous_result, result)
            result["profile_summary"] = session.profile.model_dump(mode="json")
            if input_intent == "explain_previous" and not any(p.goal_features for p in retrieved):
                result["followup_answer"] = ("Goal-fit evidence has not been verified for the remaining candidates, so no supported employment/research comparison can be made yet. "
                    "Your current budget, GPA, English score, experiences, and intake remain as shown in the structured profile.")
            result["pending_questions"] = []
            session.previous_result = session.current_result or session.previous_result
            session.current_result = result
            for error in result["validation_errors"]:
                session.event("validation_failed", detail=error)
    except (ValueError, ValidationError) as error:
        # Do not echo a Pydantic dump of user inputs or untrusted model values.
        result = {"status": "needs_input", "message": str(error) if not isinstance(error, ValidationError)
                  else "The profile values do not match their selected scale or format. Correct the form and submit again.",
            "profile_version": session.profile.profile_version, "pending_questions": [], "model_status": "not_accepted"}
    except ModelUnavailable as error:
        result = {"status": "error", "message": str(error), "profile_version": session.profile.profile_version,
                  "pending_questions": [], "model_status": "error"}
    finally:
        session.active = False
    result.update(request_id=request_id, run_id=run_id, strategy="fixed", data_mode="snapshot",
        usage=session.usage[usage_start:], model_calls=len(session.usage) - usage_start,
        service_latency_ms=round((monotonic() - started) * 1000, 2), model_config=settings.public())
    session.receipts[request_id] = result
    session.messages.append({"role": "assistant", "content": response_text(result),
        "profile_version": session.profile.profile_version, "run_id": run_id})
    session.event("output_finalized", run_id=run_id, status=result["status"], model_calls=result["model_calls"])
    return result


def response_text(result):
    if result["status"] == "needs_input":
        return result.get("message", "More information is needed.") + "\n\n" + "\n".join(
            "- " + q["text"] for q in result.get("pending_questions", []))
    if result["status"] in {"error", "busy", "budget_exhausted", "stopped"}:
        return result.get("message", "The request did not complete.")
    if result.get('recommendation_scope') == 'broad':
        count = len(result.get('preliminary_recommendations', [])) + len(result.get('recommendations', []))
        return (f"Profile v{result['profile_version']}: {count} recommendations selected from a {result['recommendation_catalog_count']}-program pool. "
            "Preliminary recommendations use labelled community facts; missing eligibility, cost and admission-tier evidence remains unresolved. "
            + (result.get('message') or ''))
    counts = len(result.get("recommendations", [])), len(result.get("pending_verification", [])), len(result.get("excluded", []))
    conclusion = {"infeasible": "Every program in the current catalog has at least one verified hard failure under your conditions.",
        "completed": "The shortlist passed the automated checks. Admission outcomes remain uncertain.",
        "insufficient_evidence": "Evidence is insufficient for a complete tiered shortlist. Pending candidates are not formal recommendations."}[result["status"]]
    return (f"Profile v{result['profile_version']}: {counts[0]} formal recommendations, {counts[1]} pending candidates, {counts[2]} excluded. "
            + conclusion + ("\n\n" + result["message"] if result.get("message") else "")
            + ("\n\n" + result["followup_answer"] if result.get("followup_answer") else ""))


def export_session(session: Session):
    return {"session_id": session.session_id, "profile": session.profile.model_dump(mode="json"),
        "declared_unknown_fields": sorted(session.unknown_fields), "messages": session.messages,
        "events": session.events, "usage": session.usage, "result": session.current_result,
        "agent_task": session.agent_task.summary() if session.agent_task else None,
        "notice": "Includes the profile and conversation you supplied. Model keys and raw provider errors are never exported."}
