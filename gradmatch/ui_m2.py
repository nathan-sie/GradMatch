"""English applicant workflow; only explicit submissions can invoke the model."""

from dataclasses import replace
from datetime import date, datetime
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
import streamlit as st

from gradmatch.catalog import read_catalog
from gradmatch.config import ConfigurationError, load_settings
from gradmatch.schemas import ApplicantProfile
from gradmatch.service import export_session, start_task
from gradmatch.session import Session, synthetic_profile
from gradmatch.ui_m1 import RULE_NAMES, STATUS, TOPICS, show_table


def render_m2(database):
    programs, sources = read_catalog(database)
    try:
        settings = load_settings()
    except ConfigurationError as error:
        st.error(str(error))
        return
    if "m2_session" not in st.session_state:
        st.session_state["m2_session"] = Session()
    session = st.session_state["m2_session"]
    st.subheader("M2 · Applicant profile and conversation")
    st.caption("Fixed baseline · official snapshots · no live website retrieval · no adaptive agent yet")
    st.info("The current catalog has incomplete eligibility and admission-tier evidence. Expect pending candidates and honest shortfalls, rather than four populated tiers.")
    st.caption("When you enable model calls, your profile and submitted messages are sent to OpenAI. Use synthetic information for milestone testing. Session history lasts only for this browser connection and is not stored in the public catalog.")
    left, right = st.columns(2)
    if left.button("Load synthetic example", key="m2_load_example", disabled=session.active):
        session.update(synthetic_profile().model_dump(exclude={"profile_version"}), unknown_fields=set())
    if right.button("Start new session", key="m2_reset", disabled=session.active):
        st.session_state["m2_session"] = Session()
        for key in list(st.session_state):
            if key.startswith("m2_input_") or key in {"m2_form_version", "m2_allow_model", "m2_last_response"}:
                del st.session_state[key]
        st.rerun()
    with st.expander("Model setup and usage", expanded=not settings.ready):
        st.write("Model:", settings.model)
        if not settings.ready:
            st.warning("Model not configured / enabled. Profile forms, clarification, and deterministic checks remain available. No model response is simulated.")
            st.code("# In the local .env file\nOPENAI_API_KEY=<your key, kept locally>\nMODEL_ENABLED=true", language="text")
        allow_model = st.checkbox("Allow paid model calls for this session", value=False,
            key="m2_allow_model", disabled=not settings.ready)
        st.caption("Only Save profile and generate, Generate / rerun, and chat submission can start requests. Maximum two model calls per turn and twenty per session; automatic retries are disabled.")
        st.write(f"Model requests in this session: {len(session.usage)}")
        if session.usage:
            show_table([{"Purpose": u["purpose"], "Status": u["status"], "Input tokens": u["input_tokens"],
                "Output tokens": u["output_tokens"], "Cached input tokens": u["cached_input_tokens"],
                "Elapsed ms": u["duration_ms"], "Estimated USD": u["estimated_cost_usd"] or "Unknown"} for u in session.usage])
            st.caption("Costs are estimates from dated published token rates; unknown usage/prices remain unknown. They are not an invoice.")
    active_settings = replace(settings, enabled=settings.enabled and allow_model)
    # Restore form widgets from the authoritative profile after chat or sample updates.
    if st.session_state.get("m2_form_version") != session.profile.profile_version:
        for key in list(st.session_state):
            if key.startswith("m2_input_"):
                del st.session_state[key]
        st.session_state["m2_form_version"] = session.profile.profile_version
    st.caption(f"Current profile version: {session.profile.profile_version} · Tuition budget: "
        + (f"USD {session.profile.tuition_budget_usd:,.2f}" if session.profile.tuition_budget_usd is not None else "Unknown"))
    with st.expander("Applicant information", expanded=session.profile.tuition_budget_usd is None):
        form = profile_form(session.profile)
    def run(**kwargs):
        with st.spinner("Checking the current profile and evidence..."):
            response = start_task(session, request_id=str(uuid4()), programs=programs, sources=sources,
                settings=active_settings, as_of=datetime.now(ZoneInfo("America/Los_Angeles")).date(), **kwargs)
        st.session_state["m2_last_response"] = response
        st.rerun()
    if form:
        try:
            changes, unknown = form
            ApplicantProfile.model_validate(changes)
            run(changes=changes, unknown_fields=unknown)
        except ValidationError:
            st.error("The GPA or English score exceeds the selected scale, or a required date is invalid. Correct the form and submit again.")
    if st.button("Generate / rerun", key="m2_generate", disabled=session.active):
        run()
    with st.expander("Current structured profile", expanded=False):
        st.json(session.profile.model_dump(mode="json"))
    st.subheader("Conversation")
    st.caption("Try: Change my tuition budget to 50000. With the model configured, you can also ask: Which remaining candidates fit employment goals?")
    for message in session.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    if message := st.chat_input("Ask a question or explicitly update your profile", key="m2_chat", disabled=session.active):
        run(message=message)
    latest = st.session_state.get("m2_last_response")
    if latest and latest.get("status") in {"error", "needs_input"}:
        st.warning(latest.get("message", "More information is needed."))
    result = session.current_result
    if result and result["profile_version"] == session.profile.profile_version:
        render_result(result, programs, sources)
    elif session.previous_result:
        st.info("Previous checks belong to an older profile and are no longer current. Submit the updated profile to recompute them.")
    if latest:
        with st.expander("Last request details", expanded=False):
            st.write(f"Status: {latest['status']} · Model: {latest['model_status']} · Model calls: {latest['model_calls']} · Service time: {latest['service_latency_ms']:,.0f} ms")
            st.json({key: latest.get(key) for key in ["request_id", "run_id", "profile_version", "validation_errors", "model_config"]})
    st.download_button("Download current session JSON", json.dumps(export_session(session), ensure_ascii=False, indent=2),
        file_name="gradmatch_m2_session.json", mime="application/json", key="m2_export")
    st.caption("The download contains the profile and messages you entered. Keep it private if you used personal information.")


def profile_form(profile):
    def key(name): return "m2_input_" + name
    with st.form("m2_profile_form"):
        has_gpa = st.checkbox("GPA is known", value=profile.gpa is not None, key=key("has_gpa"))
        left, right = st.columns(2)
        gpa = left.number_input("GPA (original scale)", min_value=0.0,
            value=float(profile.gpa.value) if profile.gpa else 0.0, key=key("gpa"))
        scale = right.number_input("GPA scale maximum", min_value=0.1,
            value=float(profile.gpa.scale) if profile.gpa else 4.0, key=key("scale"))
        scopes = ["overall", "last_60_semester", "last_90_quarter"]
        scope = st.selectbox("GPA calculation scope", scopes, index=scopes.index(profile.gpa.scope) if profile.gpa else 0,
            format_func=lambda value: {"overall": "All undergraduate coursework", "last_60_semester": "Last 60 semester credits", "last_90_quarter": "Last 90 quarter credits"}[value], key=key("scope"))
        institution = st.text_input("Undergraduate institution (optional)", value=profile.institution or "", key=key("institution"))
        country = st.text_input("Institution country (optional)", value=profile.institution_country or "", key=key("country"))
        major = st.text_input("Undergraduate major (blank means unknown)", value=profile.major or "", key=key("major"))
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
        submitted = st.form_submit_button("Save profile and generate", key="m2_save_profile")
    if not submitted:
        return None
    if set(courses) & set(absent):
        st.error("A course cannot be both completed and explicitly missing.")
        return None
    changes = {"gpa": {"value": str(gpa), "scale": str(scale), "scope": scope} if has_gpa else None,
        "institution": institution.strip() or None, "institution_country": country.strip() or None,
        "major": major.strip() or None, "goal": goal,
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
    unknown |= {"english.subscores." + name for name in ["reading", "listening", "speaking", "writing"] if name not in subscores}
    return changes, unknown


def render_result(result, programs, sources):
    names = {p.program_id: f"{p.university} — {p.degree}, {p.campus}" for p in programs}
    st.subheader("Current assessment")
    st.caption(f"Profile v{result['profile_version']} · Assessed {result['as_of_date']} · Model: {result['model_status']}")
    if result["model_status"] == "not_configured": st.warning(result["message"])
    if result["status"] == "infeasible":
        st.warning("Every program in this catalog has a verified hard failure under your current conditions. This conclusion applies only to this catalog.")
    elif result["status"] == "insufficient_evidence":
        st.warning("The evidence does not support a complete tiered shortlist. Unknown requirements are not passes, and pending candidates are not recommendations.")
    if result["changes_from_previous"].get("previous_profile_version") is not None:
        delta = result["changes_from_previous"]
        with st.expander("Changes from the previous assessment", expanded=True):
            st.write("Added:", "; ".join(names.get(pid, pid) for pid in delta["added"]) or "None")
            st.write("Retained:", "; ".join(names.get(pid, pid) for pid in delta["retained"]) or "None")
            for item in delta["removed"]:
                st.write("Removed: " + names.get(item["program_id"], item["program_id"]))
                for reason in item["reasons"]: st.caption(reason)
    st.write("**Formal recommendations**")
    for tier in ["Lottery", "Reach", "Target", "Safer"]:
        items = [item for item in result["recommendations"] if item["tier"] == tier]
        st.write(f"{tier}: {len(items)}")
        for item in items:
            st.markdown(f"[{names[item['program_id']]}]({item['identity']['official_url']})")
            for feature in item["goal_features"]: st.write(feature["statement"])
            st.caption("Automated validation checks structure and evidence bindings; admission comparisons still need human review. No outcome is guaranteed.")
            for c in item["citations"]: show_citation(c)
        if len(items) < 3: st.caption("Shortfall: insufficient verified eligibility, goal-fit, admission-tier evidence, or validated ranking.")
    st.write(f"**Pending verification ({len(result['pending_verification'])})**")
    for item in result["pending_verification"]:
        with st.expander(names[item["program_id"]]):
            st.markdown(f"[Official program website]({item['identity']['official_url']})")
            st.write("Needs verification:", ", ".join(item["missing_fields"]))
            report = item["report"]
            tuition = report["tuition"]
            st.write("Estimated full-program tuition (USD):", tuition["upper_usd"] or "Unknown")
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
    if result["observations"]:
        st.write("**Evidence-backed follow-up observations**")
        for item in result["observations"]:
            st.write(f"{names[item['program_id']]} — {RULE_NAMES.get(item['rule_id'], item['rule_id'])}: {item['explanation']}")
            for c in item["citations"]: show_citation(c)
    if result["validation_errors"]:
        with st.expander("Blocked or corrected model output"):
            st.json(result["validation_errors"])


def show_citation(citation):
    st.markdown(f"[Official source]({citation['url']})")
    st.caption(f"Retrieved: {citation['retrieved_at']} · Source ID: {citation['source_id']}")
    st.code(citation["quote"], language=None)
