"""English applicant workflow; only explicit submissions can invoke the model."""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
import streamlit as st

from gradmatch.admission_history import (
    MINIMUM_BAND_REPORTS, OPENCS_DP_SOURCE, OPENCS_DP_URL, PLANNING_TIERS,
    load_bundled_preview, load_preview, planning_tier,
)
from gradmatch.catalog import read_catalog
from gradmatch.config import ConfigurationError, load_settings
from gradmatch.schemas import GPA_SCOPE_LABELS, ApplicantProfile
from gradmatch.service import export_session, start_task
from gradmatch.session import Session, synthetic_profile, tiering_profile
from gradmatch.ui_m1 import RULE_NAMES, STATUS, TOPICS, show_table


PRIOR_DEGREE_LABELS = {
    "unknown": "Unknown",
    "none": "None",
    "held_or_expected": "Already hold one or expect to complete one",
}
ASSESSMENT_INTERRUPTED = {"error", "stopped", "budget_exhausted"}
TUITION_LIMIT_CODES = {"TUITION_EXCEEDS_BUDGET", "TUITION_MINIMUM_EXCEEDS_BUDGET"}
TUITION_LABELS = {"pass": "Within budget", "fail": "Fails budget check", "unknown": "Budget fit unverified"}


def render_m2(database, *, directory=None):
    programs, sources = read_catalog(database)
    try:
        settings = load_settings()
    except ConfigurationError as error:
        st.error(str(error))
        return
    if "m2_session" not in st.session_state:
        st.session_state["m2_session"] = Session()
    session = st.session_state["m2_session"]
    history_snapshot = load_preview() or load_bundled_preview()
    st.subheader("Applicant profile")
    left, right = st.columns(2)
    if left.button("Try a sample profile", key="m35_load_example", disabled=session.active):
        session.update(tiering_profile().model_dump(exclude={"profile_version"}), unknown_fields=set())
        st.session_state.pop("m2_form_version", None)
    generate = right.button("Generate from saved profile", key="m2_generate", disabled=session.active,
                            type="primary" if session.current_result else "secondary")
    with st.expander("Assessment settings"):
        allow_model = st.checkbox("Use AI ranking (paid)", value=False,
            key="m2_allow_model", disabled=not settings.ready)
        st.caption("AI ranking sends your profile and submitted messages to OpenAI."
                   if settings.ready else "Rule-based screening is available. Configure the model to enable AI ranking.")
        strategy_label = st.selectbox("Execution method", ["ReAct agent", "Plan-and-replan agent", "Fixed baseline"],
                                      key="m4_strategy", disabled=session.active)
        if st.session_state.get("m4_mode") == "Reviewed snapshots":
            st.session_state["m4_mode"] = "Catalog snapshots"
        mode_label = st.selectbox("Evidence mode", ["Catalog snapshots", "Live official pages"],
                                  key="m4_mode", disabled=session.active)
        pool_label = st.selectbox("Recommendation pool", ["All 83 programs (official + community data)", "Reviewed official records only"],
                                  key="m63_pool", disabled=session.active)
        if st.button("Load synthetic example", key="m2_load_example", disabled=session.active):
            session.update(synthetic_profile().model_dump(exclude={"profile_version"}), unknown_fields=set())
            st.session_state.pop("m2_form_version", None)
        if st.button("Start new session", key="m2_reset", disabled=session.active):
            st.session_state["m2_session"] = Session()
            for key in list(st.session_state):
                if key.startswith("m2_input_") or key in {"m2_form_version", "m2_allow_model", "m2_last_response", "m6_show_exploration"}:
                    del st.session_state[key]
            st.rerun()
    strategy = {"ReAct agent": "react", "Plan-and-replan agent": "plan", "Fixed baseline": "fixed"}[strategy_label]
    data_mode = "live" if mode_label == "Live official pages" else "snapshot"
    recommendation_scope = "broad" if pool_label.startswith("All 83") else "reviewed"
    active_settings = replace(settings, enabled=settings.enabled and allow_model)
    # Restore form widgets from the authoritative profile after chat or sample updates.
    if st.session_state.get("m2_form_version") != session.profile.profile_version:
        sync_profile_inputs(session.profile)
        st.session_state["m2_form_version"] = session.profile.profile_version
    gpa_summary = (f"{session.profile.gpa.value} / {session.profile.gpa.scale} ({session.profile.gpa.scope.replace('_', ' ')})"
        if session.profile.gpa else "Unknown")
    if session.profile.gpa or session.profile.major:
        st.caption(f"GPA: {gpa_summary} · {session.profile.major or 'Major unknown'} · "
                   f"Tuition budget: {format_usd(session.profile.tuition_budget_usd)}")
    st.caption("AI ranking enabled." if allow_model else "Free screening. Enable AI ranking in Assessment settings.")
    with st.expander("Applicant information", expanded=session.current_result is None):
        form = profile_form(session.profile)
    def run(**kwargs):
        with st.spinner("Checking the current profile and evidence..."):
            response = start_task(session, request_id=str(uuid4()), programs=programs, sources=sources,
                settings=active_settings, as_of=datetime.now(ZoneInfo("America/Los_Angeles")).date(),
                strategy=strategy,data_mode=data_mode,recommendation_scope=recommendation_scope,
                history_preview=history_snapshot,**kwargs)
        st.session_state["m2_last_response"] = response
        st.rerun()
    if form:
        try:
            changes, unknown, action = form
            ApplicantProfile.model_validate(changes)
            if action == 'explore':
                session.update(changes, unknown_fields=unknown)
                st.session_state['m6_show_exploration'] = True
                st.rerun()
            else:
                run(changes=changes, unknown_fields=unknown)
        except ValidationError:
            st.error("A GPA, test score, budget or date is invalid for the selected format. Correct the form and submit again.")
    if generate:
        run()
    latest = st.session_state.get("m2_last_response")
    interrupted = (latest and latest.get("profile_version") == session.profile.profile_version
                   and latest.get("status") in ASSESSMENT_INTERRUPTED)
    if interrupted:
        if latest["status"] == "budget_exhausted":
            st.warning("The assessment stopped at an execution limit. Any validated checks from this run are shown as a partial assessment.")
        else:
            st.warning(latest["message"])
        st.caption(f"Saved profile v{session.profile.profile_version} · Tuition budget {format_usd(session.profile.tuition_budget_usd)}")
        usage = latest["task_usage"]
        plan = usage.get("plan") or {}
        revisions = plan.get("revisions", [])
        needs_new_task = bool(usage["stop_reason"] not in {None, "finished"}
                              or (revisions and revisions[-1]["status"] == "stopped"))
        session_limit = active_settings.ready and len(session.usage) >= active_settings.limits["max_model_calls_per_session"]
        if session_limit:
            st.info("The session model-call limit has been reached. Turn off model calls to run deterministic checks.")
        retry_label = "Start new assessment with saved profile" if needs_new_task else "Retry with saved profile"
        if st.button(retry_label, key="m2_retry", disabled=session.active or session_limit):
            run(new_task=needs_new_task)
    if latest and latest.get("status") == "needs_input" and latest.get("profile_version") == session.profile.profile_version:
        st.warning(latest.get("message", "More information is needed."))
        for question in latest.get("pending_questions", []):
            st.write(question["text"])
    result = session.current_result
    if result and result["profile_version"] == session.profile.profile_version:
        evidence_sources=session.agent_task.sources if session.agent_task and result.get('task_id')==session.agent_task.task_id else sources
        history = history_snapshot.compare(session.profile) if history_snapshot else None
        render_result(result, programs, evidence_sources, history=history, previous=session.previous_result,
                      earlier_run=bool(interrupted and result.get("run_id") != latest["run_id"]))
    elif session.previous_result:
        previous = session.previous_result
        previous_budget = previous.get("profile_summary", {}).get("tuition_budget_usd")
        st.info(f"Previous assessment used profile v{previous['profile_version']} with a tuition budget of "
                f"{format_usd(previous_budget)}. Generate an assessment for the saved profile to see updated results.")
    st.caption("Update your profile in chat with “Change my GPA to 3.8” or “Change my tuition budget to 50000.”")
    if session.messages:
        with st.expander("Conversation"):
            for message in session.messages:
                with st.chat_message(message["role"]):
                    st.write(message["content"])
    if directory:
        from gradmatch.ui_directory import render_exploration
        with st.expander("Browse candidates", expanded=bool(st.session_state.get("m6_show_exploration"))):
            render_exploration(directory, session.profile, programs, sources)
    render_session_details(session, settings, latest, result)
    if message := st.chat_input("Ask a question or update your profile", key="m2_chat", disabled=session.active):
        run(message=message)


def render_session_details(session, settings, latest, result):
    with st.expander("Session and execution details"):
        st.caption(f"Model {settings.model} · Model requests in this session: {len(session.usage)}")
        if session.usage:
            show_table([{"Purpose": u["purpose"], "Status": u["status"], "Input tokens": u["input_tokens"],
                "Output tokens": u["output_tokens"], "Cached input tokens": u["cached_input_tokens"],
                "Elapsed ms": u["duration_ms"], "Estimated USD": u["estimated_cost_usd"] or "Unknown"} for u in session.usage])
        if result:
            st.caption(f"Result method {result['strategy']} · Evidence mode {result['data_mode']}")
            if result.get("evidence_notice"):
                st.caption(result["evidence_notice"])
        if task := session.agent_task:
            st.caption(f"Tools {task.tools}/{task.limits['max_tools']} · Model calls {task.models}/{task.limits['max_models']} "
                       f"· Page requests {task.pages}/{task.limits['max_pages']} · User turns {task.turns}/{task.limits['max_turns']}")
            if task.plan_state:
                plan = task.plan_state.public()
                st.write("**Execution plan**")
                st.caption(f"Replans {plan['replans']}/{task.limits['max_replans']}")
                if plan["revisions"]:
                    revision = plan["revisions"][-1]
                    st.write(revision["summary"])
                    st.caption(f"Revision {revision['revision']} · {revision['reason_code']} · {revision['status']}")
                    show_table([{"Step": step["step_id"], "Action": step["tool"], "Status": step["status"]}
                                for step in revision["steps"]])
                st.json(plan, expanded=False)
            if st.button("Start new task (keep profile)", key="m4_new_task", disabled=session.active):
                session.agent_task = None
                st.info("The next submission starts a fresh task. Your profile and session model limit are retained.")
        if latest:
            st.write(f"Status: {latest['status']} · Model: {latest['model_status']} · Model calls: {latest['model_calls']} · Service time: {latest['service_latency_ms']:,.0f} ms")
            st.json({key: latest.get(key) for key in ["request_id", "run_id", "profile_version", "validation_errors", "model_config"]},
                    expanded=False)
        st.download_button("Download current session JSON", json.dumps(export_session(session), ensure_ascii=False, indent=2),
            file_name="gradmatch_m2_session.json", mime="application/json", key="m2_export")
        st.caption("The download includes the profile and messages from this browser session.")


def sync_profile_inputs(profile):
    """Send authoritative values to existing keyed browser widgets.

    Deleting a key and changing its default does not update an existing
    Streamlit 1.67 browser widget. Explicit assignments also preserve the
    paid-call checkbox, which is outside this form.
    """
    english, degree, gre = profile.english, profile.degree, profile.gre
    values = {
        "has_gpa": profile.gpa is not None,
        "gpa": float(profile.gpa.value) if profile.gpa else 0.0,
        "scale": float(profile.gpa.scale) if profile.gpa else 4.0,
        "scope": profile.gpa.scope if profile.gpa else "overall",
        "institution": profile.institution or "", "country": profile.institution_country or "",
        "major": profile.major or "", "goal": profile.goal,
        "degree_completion": degree.completion if degree else "unknown",
        "degree_recognition": degree.recognition if degree else "unknown",
        "degree_field": degree.field if degree else "unknown",
        "degree_country": (degree.country or "") if degree else "",
        "degree_prior_academic_graduate_degree": getattr(degree, "prior_academic_graduate_degree", "unknown"),
        "has_budget": profile.tuition_budget_usd is not None,
        "budget": str(profile.tuition_budget_usd) if profile.tuition_budget_usd is not None else "",
        "basis": profile.budget_basis, "has_intake": profile.intake is not None,
        "year": profile.intake.year if profile.intake else 2027,
        "term": profile.intake.term if profile.intake else "fall",
        "category": profile.applicant_category, "mode": profile.study_mode,
        "english_version": english.version if english else profile.english_status,
        "english_total": float(english.total) if english else 0.0,
        "has_date": bool(english and english.test_date), "test_date": english.test_date if english else None,
        "has_gre": gre is not None,
        "gre_verbal": gre.verbal if gre else 130,
        "gre_quantitative": gre.quantitative if gre else 130,
        "gre_writing": float(gre.writing) if gre else 0.0,
        "gre_date": gre.test_date if gre else None,
        "gre_format": gre.format if gre else "unknown",
        "courses": [name for name, complete in profile.coursework.items() if complete is True and name in TOPICS],
        "absent_courses": [name for name, complete in profile.coursework.items() if complete is False and name in TOPICS],
    }
    for name in ["reading", "listening", "speaking", "writing"]:
        values[name] = str(english.subscores.get(name, "")) if english else ""
    for field in ["research", "work_experience"]:
        values[field + "_known"] = getattr(profile, field) is not None
        values[field] = "\n".join(getattr(profile, field) or [])
    st.session_state.update({"m2_input_" + name: value for name, value in values.items()})


def profile_form(profile):
    def key(name): return "m2_input_" + name
    with st.form("m2_profile_form"):
        basics, tests, preparation = st.tabs(["Basics", "Degree and tests", "Preparation"])
        with basics:
            major = st.text_input("Undergraduate major (blank means unknown)", value=profile.major or "", key=key("major"))
            has_gpa = st.checkbox("GPA is known", value=profile.gpa is not None, key=key("has_gpa"))
            left, right = st.columns(2)
            gpa = left.number_input("GPA (original scale)", min_value=0.0,
                value=float(profile.gpa.value) if profile.gpa else 0.0, key=key("gpa"))
            scale = right.number_input("GPA scale maximum", min_value=0.1,
                value=float(profile.gpa.scale) if profile.gpa else 4.0, key=key("scale"))
            scopes = list(GPA_SCOPE_LABELS)
            scope = st.selectbox("GPA calculation scope", scopes, index=scopes.index(profile.gpa.scope) if profile.gpa else 0,
                format_func=GPA_SCOPE_LABELS.__getitem__, key=key("scope"))
            goals = [None, "employment", "research", "mixed"]
            goal = st.selectbox("Main goal", goals, index=goals.index(profile.goal),
                format_func=lambda value: value.title() if value else "Unknown", key=key("goal"))
            has_budget = st.checkbox("Tuition budget is known", value=profile.tuition_budget_usd is not None, key=key("has_budget"))
            budget = st.text_input("Full-program tuition budget (USD, excluding living costs)",
                value=str(profile.tuition_budget_usd) if profile.tuition_budget_usd is not None else "", key=key("budget"),
                help="Enter an exact USD amount such as 50000 or 50000.25, without commas.")
            bases = ["published_rate_estimate", "guaranteed_final"]
            basis = st.selectbox("Budget basis", bases, index=bases.index(profile.budget_basis),
                format_func=lambda value: "Published-rate estimate; future increases not guaranteed" if value == "published_rate_estimate" else "Require a guaranteed final tuition price", key=key("basis"))
            has_intake = st.checkbox("Intake is known", value=profile.intake is not None, key=key("has_intake"))
            year = st.number_input("Intake year", min_value=2020, max_value=2100,
                value=profile.intake.year if profile.intake else 2027, key=key("year"))
            terms = ["fall", "spring", "summer", "winter"]
            term = st.selectbox("Intake term", terms, index=terms.index(profile.intake.term) if profile.intake else 0, format_func=str.title, key=key("term"))
            categories = ["international", "domestic"]
            category = st.selectbox("Applicant category", categories, index=categories.index(profile.applicant_category),
                format_func=lambda value: "International applicant" if value == "international" else "U.S. domestic applicant", key=key("category"))
            modes = ["full_time", "part_time"]
            mode = st.selectbox("Study mode", modes, index=modes.index(profile.study_mode),
                format_func=lambda value: "Full-time" if value == "full_time" else "Part-time", key=key("mode"))
        with tests:
            institution = st.text_input("Undergraduate institution (optional)", value=profile.institution or "", key=key("institution"))
            country = st.text_input("Institution country (optional)", value=profile.institution_country or "", key=key("country"))
            st.write("**Degree background**")
            degree = profile.degree
            degree_values = {}
            for field, label, options in [
                ("completion", "Degree completion", ["unknown", "completed", "expected_before_enrollment", "not_before_enrollment"]),
                ("recognition", "Credential status (self-reported)", ["unknown", "recognized_bachelors_or_equivalent", "not_recognized"]),
                ("field", "Degree field", ["unknown", "CS", "ECE", "STEM", "other"])]:
                selected = getattr(degree, field) if degree else "unknown"
                degree_values[field] = st.selectbox(label, options, index=options.index(selected),
                    format_func=lambda v: v.replace("_", " ").capitalize() if v not in {"CS", "ECE", "STEM"} else v, key=key("degree_"+field))
            degree_values["country"] = st.text_input("Degree country (ISO code, e.g. US; blank means unknown)",
                value=degree.country or "" if degree else "", key=key("degree_country")).strip().upper() or None
            previous = getattr(degree, "prior_academic_graduate_degree", "unknown")
            degree_values["prior_academic_graduate_degree"] = st.selectbox("Previous academic graduate degree",
                list(PRIOR_DEGREE_LABELS), index=list(PRIOR_DEGREE_LABELS).index(previous),
                format_func=PRIOR_DEGREE_LABELS.__getitem__, key=key("degree_prior_academic_graduate_degree"),
                help="Include an academic master's or doctoral degree already held or expected before enrollment. Professional degrees are excluded from this check.")
            st.caption("The university makes the final credential-equivalency decision. Application document preparation is listed separately.")
            versions = ["unknown", "not_taken", "toefl_120", "toefl_6", "ielts_9", "det_160"]
            labels = ["Unknown", "Not taken yet", "TOEFL legacy (120-point scale)", "TOEFL new (6-point scale)", "IELTS Academic (9-point scale)", "Duolingo English Test (160-point scale)"]
            version = st.selectbox("English test / status", versions,
                index=versions.index(profile.english.version if profile.english else profile.english_status),
                format_func=lambda value: labels[versions.index(value)], key=key("english_version"))
            total = st.number_input("English overall score (selected test's original scale)", min_value=0.0,
                value=float(profile.english.total) if profile.english else 0.0, step=0.5, key=key("english_total"))
            has_date = st.checkbox("English test date is known", value=bool(profile.english and profile.english.test_date), key=key("has_date"))
            test_date = st.date_input("English test date", value=profile.english.test_date if profile.english else None,
                min_value=date(2000, 1, 1), max_value=date(2100, 12, 31), key=key("test_date"))
            st.caption("Fill only subscores you know. Blank means unknown; use the selected test's original scale.")
            subscores = {}
            for name in ["reading", "listening", "speaking", "writing"]:
                raw = st.text_input(f"English {name} subscore", value=str(profile.english.subscores.get(name, "")) if profile.english else "", key=key(name))
                if raw.strip(): subscores[name] = raw.strip()
            st.write("**GRE (needed only by some programs)**")
            has_gre = st.checkbox("GRE result is known", value=profile.gre is not None, key=key("has_gre"))
            gre_values = {}
            for field, label, minimum, maximum, default in [("verbal", "GRE Verbal",130,170,130), ("quantitative", "GRE Quantitative",130,170,130)]:
                gre_values[field] = st.number_input(label, min_value=minimum, max_value=maximum,
                    value=getattr(profile.gre,field) if profile.gre else default, key=key("gre_"+field))
            gre_values["writing"] = str(st.number_input("GRE Analytical Writing", min_value=0.0,max_value=6.0,step=0.5,
                value=float(profile.gre.writing) if profile.gre else 0.0,key=key("gre_writing")))
            gre_values["test_date"] = st.date_input("GRE test date (leave blank if unknown)", value=profile.gre.test_date if profile.gre else None,
                min_value=date(2000,1,1),max_value=date(2100,12,31),key=key("gre_date"))
            formats=["unknown","in_person","at_home"]
            gre_values["format"] = st.selectbox("GRE test format",formats,index=formats.index(profile.gre.format) if profile.gre else 0,
                format_func=lambda v:v.replace("_"," ").title(),key=key("gre_format"))
        with preparation:
            st.caption("Only confirmed completed courses are marked present. Unselected topics remain unknown.")
            courses = st.multiselect("Completed coursework / demonstrated skills", list(TOPICS),
                default=[name for name, complete in profile.coursework.items() if complete and name in TOPICS], format_func=TOPICS.get, key=key("courses"))
            absent = st.multiselect("Explicitly missing coursework", list(TOPICS),
                default=[name for name, complete in profile.coursework.items() if complete is False and name in TOPICS], format_func=TOPICS.get, key=key("absent_courses"))
            experiences = {}
            for field, label in [("research", "Research experience"), ("work_experience", "Work / internship experience")]:
                known = st.checkbox(label + " is known", value=getattr(profile, field) is not None, key=key(field + "_known"))
                text = st.text_area(label + " (one item per line; blank with Known checked means none)", value="\n".join(getattr(profile, field) or []), key=key(field))
                experiences[field] = [line.strip() for line in text.splitlines() if line.strip()] if known else None
        submit, preview = st.columns(2)
        submitted = submit.form_submit_button("Save and generate", key="m2_save_profile", type="primary")
        explore = preview.form_submit_button("Save and preview programs", key="m6_save_exploration")
    if not (submitted or explore):
        return None
    if set(courses) & set(absent):
        st.error("A course cannot be both completed and explicitly missing.")
        return None
    changes = {"gpa": {"value": str(gpa), "scale": str(scale), "scope": scope} if has_gpa else None,
        "institution": institution.strip() or None, "institution_country": country.strip() or None,
        "major": major.strip() or None, "goal": goal, "degree": degree_values,
        "gre": gre_values if has_gre else None,
        "tuition_budget_usd": str(budget) if has_budget else None, "budget_basis": basis,
        "intake": {"year": year, "term": term} if has_intake else None,
        "applicant_category": category, "study_mode": mode,
        "english_status": version if version in {"unknown", "not_taken"} else "known",
        "english": None if version in {"unknown", "not_taken"} else {"version": version, "total": str(total),
            "test_date": test_date if has_date else None, "subscores": subscores},
        "coursework": {**dict.fromkeys(courses, True), **dict.fromkeys(absent, False)}, **experiences}
    unknown = {field for field in ["gpa", "major", "goal", "tuition_budget_usd", "intake"] if changes[field] is None}
    if version in {"unknown", "not_taken"}: unknown.add("english")
    if not has_date: unknown.add("english.test_date")
    if degree_values["completion"] == "unknown" or degree_values["recognition"] == "unknown": unknown.add("degree")
    if not has_gre or not gre_values["test_date"]: unknown.add("gre")
    unknown |= {"english.subscores." + name for name in ["reading", "listening", "speaking", "writing"] if name not in subscores}
    return changes, unknown, 'explore' if explore else 'generate'


def format_usd(value):
    if value is None:
        return "Unknown"
    amount = Decimal(value)
    return f"USD {amount:,.0f}" if amount == amount.to_integral_value() else f"USD {amount:,.2f}"


def format_tuition(tuition):
    lower, upper = tuition["lower_usd"], tuition["upper_usd"]
    if lower is None and upper is not None:
        return f"Ceiling {format_usd(upper)}"
    if lower is not None and upper is None:
        return f"Known minimum {format_usd(lower)}"
    if lower != upper:
        return f"Estimated range {format_usd(lower)}–{format_usd(upper)}"
    return format_usd(upper)


def render_tuition_summary(result, names, previous):
    """Summarize the existing tuition checks without re-evaluating a candidate."""
    groups = {status: {} for status in TUITION_LABELS}
    for field, report_key in (("recommendations", "checks"), ("pending_verification", "report")):
        for item in result[field]:
            report = item[report_key]
            check = next(c for c in report["checks"] if c["rule_id"] == "tuition")
            groups[check["status"]][item["program_id"]] = (format_tuition(report["tuition"]), check["explanation"])
    for item in result["excluded"]:
        for code, reason in zip(item["reason_codes"], item["reasons"]):
            if code in TUITION_LIMIT_CODES:
                groups["fail"][item["program_id"]] = ("See budget finding", reason)

    st.write("**Tuition budget check**")
    budget = result.get("profile_summary", {}).get("tuition_budget_usd")
    delta = result["changes_from_previous"]
    if previous and previous["profile_version"] == delta.get("previous_profile_version"):
        old_budget = previous.get("profile_summary", {}).get("tuition_budget_usd")
    else:
        old_budget = budget
    budget_changed = (Decimal(old_budget) if old_budget is not None else None) != (
        Decimal(budget) if budget is not None else None)
    if budget_changed:
        st.write(f"Full-program tuition budget updated: {format_usd(old_budget)} → {format_usd(budget)}")
    else:
        st.write(f"Full-program tuition budget: {format_usd(budget)}")
    for column, (status, label) in zip(st.columns(3), TUITION_LABELS.items()):
        column.metric(label, len(groups[status]))
    st.caption("Counts cover candidates under consideration and exclusions with a tuition finding. Estimates use published rates and exclude living costs. Mandatory fees may be separate or unknown.")
    if budget_changed:
        for item in delta["removed"]:
            pid = item["program_id"]
            if pid in groups["fail"]:
                st.write(f"Removed with a tuition budget failure: {names[pid]}")
    with st.expander("Tuition checks by program"):
        show_table([{"Program": names[pid], "Budget status": TUITION_LABELS[status],
                     "Full-program tuition": amount, "Finding": reason}
                    for status, programs in groups.items()
                    for pid, (amount, reason) in programs.items()])


def render_result(result, programs, sources, *, history=None, previous=None, earlier_run=False):
    names = {p.program_id: f"{p.university} — {p.degree}, {p.campus}" for p in programs}
    for field in ['recommendations', 'preliminary_recommendations', 'pending_verification', 'excluded', 'preliminary_excluded']:
        for item in result.get(field, []):
            identity=item.get('identity',{})
            names.setdefault(item['program_id'], identity.get('university','') + ' — ' + identity.get('program_name',item['program_id']))
    if result["status"] == "budget_exhausted":
        st.subheader("Partial assessment")
    elif earlier_run:
        st.subheader("Last completed assessment for this profile")
    else:
        st.subheader("Your recommendations")
    if result["model_status"] == "not_configured" and result.get("message"):
        st.caption("Results use rule-based screening.")
    if result["status"] == "infeasible":
        st.warning("Every program in this catalog has a verified hard failure under your current conditions. This conclusion applies only to this catalog.")
    elif result["status"] == "insufficient_evidence" and result.get('recommendation_scope') != 'broad':
        st.warning("The evidence does not support a complete tiered shortlist. Unknown requirements are not passes, and pending candidates are not recommendations.")
    broad = result.get("recommendation_scope") == "broad"
    if broad:
        st.caption(f"Recommendation pool: {result['recommendation_catalog_count']} programs · "
                   f"Programs screened: {len(result['retrieved_program_ids'])}")
    shortlist, budget, evidence = st.tabs(["Shortlist", "Budget and changes", "Checks and sources"])
    with shortlist:
        render_shortlist_overview(result, names)
        if broad:
            render_broad_recommendations(result, history=history)
        render_formal_recommendations(result["recommendations"], names, sources, history)
    with budget:
        render_tuition_summary(result, names, previous)
        if result["changes_from_previous"].get("previous_profile_version") is not None:
            delta = result["changes_from_previous"]
            with st.expander("Changes from the previous assessment"):
                st.write("Added:", "; ".join(names.get(pid, pid) for pid in delta["added"]) or "None")
                st.write("Retained:", "; ".join(names.get(pid, pid) for pid in delta["retained"]) or "None")
                for item in delta["removed"]:
                    st.write("Removed: " + names.get(item["program_id"], item["program_id"]))
                    for reason in item["reasons"]: st.caption(reason)
    with evidence:
        if history and history.snapshot.gpa_bands:
            render_history_coverage(history, result, names)
        render_verification(result, names, sources, history, broad)


def suggested_tier(item):
    return item.get("planning_tier") or planning_tier(None, hard_checks_passed=False)


def render_shortlist_overview(result, names):
    rows = []
    for item in result["recommendations"]:
        rows.append({"Program": names[item["program_id"]], "Tier": f"{item['tier']} · Formal",
                     "Tuition budget": "Within budget", "Next listed round": "See program details"})
    for item in result.get("preliminary_recommendations", []):
        checks = item["checks"]
        tuition = next(check for check in checks["checks"] if check["rule_id"] == "tuition")
        upcoming = checks["next_listed_round"]
        rows.append({"Program": names[item["program_id"]], "Tier": f"{suggested_tier(item)['label']} · Planning",
                     "Tuition budget": TUITION_LABELS[tuition["status"]],
                     "Next listed round": upcoming["date"] if upcoming else "Needs verification"})
    if rows:
        show_table(rows)
        st.caption("Use Reach, Target and Safer as planning labels. Open a program below for its evidence and next steps.")
    else:
        st.info("No recommendations for this profile. Open Checks and sources to see what needs verification.")


def render_formal_recommendations(items, names, sources, history):
    if not items:
        return
    st.markdown("**Formal matches**")
    for item in items:
        with st.expander(f"{item['tier']} · {names[item['program_id']]}"):
            st.markdown(f"[Official program website]({item['identity']['official_url']})")
            st.write(item["planning_reason"])
            render_admission_history(history, item["program_id"])
            tuition = item["checks"]["tuition"]
            st.write(f"Full-program tuition · {format_tuition(tuition)}")
            st.caption(f"Published rate year {tuition['rate_year']} · {tuition['formula']}")
            for assumption in tuition["assumptions"]:
                st.caption(assumption)
            for feature in item["goal_features"]:
                st.write(feature["statement"])
            for limitation in item["limitations"]:
                st.caption(limitation)
            show_table([{"Check": RULE_NAMES.get(check["rule_id"], check["rule_id"]),
                         "Status": STATUS[check["status"]], "Reason": check["explanation"]}
                        for check in item["checks"]["checks"]])
            st.write("**Application checklist**")
            for material in item["application_materials"]:
                st.write("• " + material)
            for sid in sorted({sid for check in item["checks"]["checks"] for sid in check["source_ids"]}):
                source = sources[sid]
                show_citation({"source_id": sid, "url": str(source.url),
                               "retrieved_at": source.retrieved_at.isoformat(), "quote": source.fact_summary})
            for citation in item["citations"]:
                show_citation(citation)


def render_verification(result, names, sources, history, broad):
    st.write(f"**Pending verification ({len(result['pending_verification'])})**")
    pending_details=result['pending_verification']
    shown_on_recommendations = {item["program_id"] for item in result["recommendations"]}
    if broad:
        shown_on_recommendations.update(item["program_id"] for item in result["preliminary_recommendations"])
    excluded = {item["program_id"] for item in result.get("preliminary_excluded", [])}
    pending_history = set(history.snapshot.programs) - shown_on_recommendations - excluded if history else set()
    if broad:
        show_table([{'Program':names[i['program_id']],'Missing evidence':', '.join(i['missing_fields'])} for i in pending_details])
        pending_details = [item for index, item in enumerate(pending_details)
                           if index < 5 or item["program_id"] in pending_history]
        if len(pending_details) > 5:
            st.caption('Detailed checks cover the first five pending records and additional records with local applicant history.')
        else:
            st.caption('Detailed checks cover the first five pending records. The session JSON contains the full assessment.')
    for item in pending_details:
        with st.expander(names[item["program_id"]]):
            program_site_label = "Listed program website" if item["program_id"].startswith("community-") else "Official program website"
            st.markdown(f"[{program_site_label}]({item['identity']['official_url']})")
            st.write("Needs verification:", ", ".join(item["missing_fields"]))
            if item["program_id"] in pending_history:
                render_admission_history(history, item["program_id"])
            report = item["report"]
            tuition = report["tuition"]
            st.write(f"Full-program tuition: {format_tuition(tuition)}")
            st.caption(f"Rate year: {tuition['rate_year'] or 'Unknown'} · {tuition['formula'] or 'Full-program calculation unavailable'}")
            for assumption in tuition["assumptions"]: st.caption(assumption)
            st.caption("Published-rate estimate only. Future increases and living costs are excluded; mandatory fees may be separate or unknown.")
            show_table([{"Check": RULE_NAMES.get(c["rule_id"], c["rule_id"]), "Status": STATUS[c["status"]],
                "Reason": c["explanation"]} for c in report["checks"]])
            for sid in sorted({sid for c in report["checks"] for sid in c["source_ids"]}):
                source = sources[sid]
                show_citation({"source_id": sid, "url": str(source.url), "retrieved_at": source.retrieved_at.isoformat(), "quote": source.source_excerpt})
    with st.expander(f"Excluded by verified hard checks ({len(result['excluded'])})"):
        for item in result["excluded"]:
            st.write(names[item["program_id"]])
            for reason in item["reasons"]: st.caption(reason)
    if result.get('preliminary_excluded'):
        with st.expander(f"Additional screening findings ({len(result['preliminary_excluded'])})"):
            for item in result['preliminary_excluded']:
                st.write(names[item['program_id']])
                for check in item['reasons']:
                    st.caption(check['basis'] + ': ' + check['explanation'])
    if result["observations"]:
        st.write("**Evidence-backed follow-up observations**")
        for item in result["observations"]:
            st.write(f"{names[item['program_id']]} — {RULE_NAMES.get(item['rule_id'], item['rule_id'])}: {item['explanation']}")
            for c in item["citations"]: show_citation(c)
    if result["validation_errors"]:
        with st.expander("Blocked or corrected model output"):
            st.json(result["validation_errors"])


def render_broad_recommendations(result, *, history=None):
    items = result["preliminary_recommendations"]
    if not items:
        return
    st.markdown("**Planning matches**")
    for item in items:
        identity, checks, tier = item["identity"], item["checks"], suggested_tier(item)
        name = f"{identity['university']} — {identity['program_name']}"
        with st.expander(f"{tier['label']} · {name}"):
            st.markdown(f"[Program website]({identity['official_url']})")
            st.markdown(f"**Planning tier · {tier['label']}**")
            st.write(tier["reason"])
            if fit := item.get("research_fit"):
                st.markdown(f"**Research fit · {fit['pathway']}**")
                st.write(fit["summary"])
                st.write(fit["research_areas"])
                st.caption(f"Reviewed {fit['reviewed_on']} · [Program requirements]({fit['program_source']}) "
                           f"· [Research groups and faculty]({fit['research_source']})")
            if evidence := tier["history"] or item.get("admission_history_evidence"):
                cycles = evidence["admission_cycles"]
                years = f"{min(cycles)}–{max(cycles)}"
                st.markdown("**Matched historical reports**")
                st.write(f"GPA band {evidence['gpa_band']} · Reported admits ({evidence['admitted']}) "
                         f"· Reported rejects ({evidence['rejected']})")
                st.caption(f"[{OPENCS_DP_SOURCE}]({OPENCS_DP_URL}) · {years} · Snapshot {evidence['snapshot_date']}")
                if evidence["assumed_overall"]:
                    st.caption(f"Overall GPA was assumed for {evidence['assumed_overall']} of these reports.")
            else:
                render_admission_history(history, item["program_id"])
            if upcoming := checks["next_listed_round"]:
                st.write(f"Next listed application round · {upcoming['date']} — {upcoming['label']}")
            for reason in item["reasons"]:
                st.write(reason["explanation"])
            show_table([{"Check": check["rule_id"].replace("_", " ").title(),
                         "Status": check["status"].replace("_", " "),
                         "Basis": check["basis"].replace("_", " "), "Details": check["explanation"]}
                        for check in checks["checks"]])
            for rule in checks["reported_language"]:
                st.caption(rule["test_label"] + " — " + rule["summary"])
            for row in checks["listed_rounds"]:
                st.caption(row["date"] + " — " + row["label"])
            st.caption(f"Reported application fee · {checks['application_fee'] or 'Unknown'}")
            st.markdown(f"[Reported application portal]({checks['application_url']}) · "
                        f"[CS Grad tracker snapshot]({checks['source_url']})")
            st.caption(f"Tracker snapshot {checks['source_date']} · {checks['source_intake']}")


def render_history_coverage(history, result, names):
    covered = history.covered_candidates(result)
    with st.expander("Compare candidates by historical sample coverage"):
        st.caption(f"GPA band {history.band_label}. Includes candidates with at least {MINIMUM_BAND_REPORTS} "
                   f"reported decisions in this band. [{OPENCS_DP_SOURCE}]({OPENCS_DP_URL})")
        if covered:
            show_table([{"Program": names[program_id], "Assessment": status, "Reports": counts.total,
                         "Reported admits": counts.admitted, "Reported rejects": counts.rejected}
                        for program_id, status, counts in covered])
            if any(counts.assumed_overall for _, _, counts in covered):
                st.caption("Where the calculation scope was missing, overall GPA was assumed.")
        else:
            st.write("The historical sample in this GPA band is too small to order the current candidates.")


def render_admission_history(history, program_id):
    counts = history.snapshot.programs.get(program_id) if history else None
    if counts is None:
        return
    snapshot = history.snapshot
    scope = "overall GPA" if snapshot.gpa_scope == "overall" else GPA_SCOPE_LABELS[snapshot.gpa_scope].lower()
    cycles = "–".join(str(year) for year in sorted({min(snapshot.cycles), max(snapshot.cycles)}))
    term = snapshot.intake.term.title()
    scale = format(snapshot.gpa_scale.normalize(), "f")
    st.markdown("**Historical applicant comparisons**")
    st.caption(f"{term} {cycles} · {scale}-point {scope} · Snapshot {snapshot.snapshot_date} · "
               f"[{OPENCS_DP_SOURCE}]({OPENCS_DP_URL})")
    if not (counts.admitted or counts.rejected):
        st.caption("No explicit admission decisions with this GPA basis in the local sample.")
        return
    st.write(f"Reported admits ({counts.admitted}) · Reported rejects ({counts.rejected})")
    if counts.assumed_overall:
        report_label = "report" if counts.assumed_overall == 1 else "reports"
        st.caption(f"Overall GPA was assumed for {counts.assumed_overall} {report_label} with a missing calculation scope.")
    st.caption("Self-reported sample counts use the GPA scale and calculation scope. Individual admission chances are unknown.")
    band_counts = history.band_counts(program_id)
    if band_counts is not None:
        if band_counts.total >= MINIMUM_BAND_REPORTS:
            st.write(f"GPA band {history.band_label} · Reported admits ({band_counts.admitted}) "
                     f"· Reported rejects ({band_counts.rejected})")
        else:
            st.caption(f"GPA band {history.band_label} has fewer than {MINIMUM_BAND_REPORTS} reported decisions.")


def show_citation(citation):
    st.markdown(f"[Official source]({citation['url']})")
    st.caption(f"Retrieved: {citation['retrieved_at']} · Source ID: {citation['source_id']}")
    st.code(citation["quote"], language=None)
