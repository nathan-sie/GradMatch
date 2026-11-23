"""M1 verification UI. Does not make LLM calls or issue recommendations."""

from datetime import date
import json

import streamlit as st
from pydantic import ValidationError

from gradmatch.catalog import coverage_rows, read_catalog
from gradmatch.constraints import check_constraints, estimate_tuition
from gradmatch.schemas import GPA_SCOPE_LABELS, ApplicantProfile
from gradmatch.coursework import TOPICS


STATUS = {"pass": "Meets checked requirement", "fail": "Does not meet requirement", "unknown": "Needs verification", "not_applicable": "Not applicable"}
RULE_NAMES = {"identity": "Program identity", "intake": "Intake", "gpa": "GPA",
    "english": "English proficiency", "prerequisites": "Prerequisite coursework", "tuition": "Tuition budget",
    "deadline": "Application deadline", "degree": "Bachelor's degree / equivalency", "gre": "GRE",
    "remaining_eligibility": "Other reviewed planning requirements"}
MISSING_NAMES = {**RULE_NAMES, "admission_risk_evidence": "Admission-tier evidence", "tuition_not_computable": "Full-program tuition basis",
    "hard_gpa_minimum_not_verified": "Hard GPA minimum", "prerequisites_need_review": "Prerequisites need review",
    "final_deadline_schedule_partial": "Complete applicable deadline schedule"}


def show_table(rows):
    """Eight-row summaries need only Markdown, not a native dataframe library."""
    if not rows:
        return
    def cell(value):
        return str(value if value is not None else "Unknown").replace("|", "\\|").replace("\n", " ")
    columns = list(rows[0])
    lines = ["| " + " | ".join(cell(column) for column in columns) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    lines += ["| " + " | ".join(cell(row.get(column)) for column in columns) + " |" for row in rows]
    st.markdown("\n".join(lines))


def render_m1(database):
    if st.session_state.get("ui_language") != "en":
        st.session_state.pop("m1_result", None)
        st.session_state["ui_language"] = "en"
    try:
        programs, sources = read_catalog(database)
    except (ValidationError, ValueError) as error:
        st.error("Catalog records failed schema validation. Validate or reimport the catalog.")
        st.code(str(error))
        return
    st.subheader("M1 · Data and rule verification")
    st.caption("Uses fixed official evidence snapshots. Default inputs are synthetic examples; live retrieval and admission tiers are planned for later milestones.")
    st.write("Check individual budget, eligibility, and deadline requirements. Unverified fields remain marked as Needs verification.")
    coverage = coverage_rows(programs, sources)
    with st.expander("View initial catalog coverage", expanded=False):
        show_table([{
            "University": row["university"], "Campus": row["campus"],
            "Computable tuition (USD)": row["tuition_estimate_usd"] or "Needs verification",
            "Rate year": row["rate_year"] or "Not verified",
            "Official sources": row["source_count"], "Missing / needs verification": ", ".join(MISSING_NAMES.get(key, key) for key in row["missing_fields"]),
        } for row in coverage])

    st.subheader("Check a synthetic applicant")
    with st.form("m1_profile_form"):
        left, right = st.columns(2)
        gpa = left.number_input("GPA", min_value=0.0, value=3.5, step=0.1, key="m1_gpa")
        scale = right.number_input("GPA scale maximum", min_value=0.1, value=4.0, step=0.1, key="m1_gpa_scale")
        scope = st.selectbox("GPA calculation scope", list(GPA_SCOPE_LABELS),
            format_func=GPA_SCOPE_LABELS.__getitem__, key="m1_gpa_scope")
        budget = st.number_input("Full-program tuition budget (USD, excluding living costs)", min_value=0, value=70000, step=1000, key="m1_budget")
        basis = st.selectbox("Budget assessment basis", ["published_rate_estimate", "guaranteed_final"],
            format_func=lambda value: "Estimate using the stated year's published rates" if value == "published_rate_estimate" else "Require a guaranteed final future price", key="m1_budget_basis")
        year = st.number_input("Intake year", min_value=2020, max_value=2100, value=2027, key="m1_intake_year")
        term = st.selectbox("Intake term", ["fall", "spring", "summer", "winter"], format_func=str.title, key="m1_intake_term")
        category = st.selectbox("Applicant category", ["international", "domestic"],
            format_func=lambda value: "International applicant" if value == "international" else "U.S. domestic applicant", key="m1_category")
        mode = st.selectbox("Study mode", ["full_time", "part_time"],
            format_func=lambda value: "Full-time" if value == "full_time" else "Part-time", key="m1_study_mode")
        version = st.selectbox("English test version", ["toefl_120", "toefl_6", "ielts_9", "unknown", "not_taken"],
            format_func=lambda value: {"toefl_120": "TOEFL legacy version (120-point scale)", "toefl_6": "TOEFL new version (6-point scale)", "ielts_9": "IELTS Academic (9-point scale)", "unknown": "Unknown", "not_taken": "Not taken yet"}[value], key="m1_english_version")
        total = st.number_input("English overall score (use the selected test's original scale)", min_value=0.0, value=100.0, step=0.5, key="m1_english_total")
        knows_date = st.checkbox("Test date is known", value=True, key="m1_has_test_date")
        test_date = st.date_input("Test date", value=date(2025, 11, 1), key="m1_test_date")
        provide_subscores = st.checkbox("Provide required subscores (IELTS subscores in this example)", key="m1_has_subscores")
        subscores = {}
        for field, label in [("reading", "Reading"), ("listening", "Listening"), ("speaking", "Speaking"), ("writing", "Writing")]:
            subscores[field] = st.number_input(f"IELTS {label}", min_value=0.0, max_value=9.0, value=7.0, step=0.5, key=f"m1_{field}")
        courses = st.multiselect("Completed coursework / demonstrated skills (self-reported)", list(TOPICS),
            default=[key for key in TOPICS if key != "discrete_math"], format_func=TOPICS.get, key="m1_courses")
        as_of = st.date_input("Assessment date (does not refresh source data)", value=date(2026, 11, 13), key="m1_as_of")
        submit = st.form_submit_button("Run M1 checks", key="run_m1")
    if submit:
        try:
            english = None if version in {"unknown", "not_taken"} else {
                "version": version, "total": str(total), "test_date": test_date if knows_date else None,
                "subscores": {key: str(value) for key, value in subscores.items()} if version == "ielts_9" and provide_subscores else {},
            }
            data = {"gpa": {"value": str(gpa), "scale": str(scale), "scope": scope},
                "tuition_budget_usd": str(budget), "budget_basis": basis,
                "intake": {"year": year, "term": term}, "applicant_category": category, "study_mode": mode,
                "english": english, "english_status": version if version in {"unknown", "not_taken"} else "known",
                "coursework": {key: True for key in courses}}
            fingerprint = json.dumps(data, sort_keys=True, default=str)
            previous = st.session_state.get("m1_fingerprint")
            profile_version = st.session_state.get("m1_profile_version", 0) + (previous != fingerprint)
            profile = ApplicantProfile.model_validate({**data, "profile_version": profile_version})
            reports = [check_constraints(profile, program, sources, as_of=as_of).model_dump(mode="json") for program in programs]
            st.session_state["m1_fingerprint"] = fingerprint
            st.session_state["m1_profile_version"] = profile_version
            st.session_state["m1_result"] = {"profile": profile.model_dump(mode="json"), "as_of": str(as_of), "reports": reports}
        except ValidationError as error:
            st.session_state.pop("m1_result", None)
            st.error("The inputs do not match the selected scale or data format. Check the GPA, English test version, and overall score.")
            st.code(str(error))
    result = st.session_state.get("m1_result")
    if result:
        st.subheader("Assessment results")
        st.caption(f"Profile version {result['profile']['profile_version']} · Tuition budget USD {result['profile']['tuition_budget_usd']} · Assessment date {result['as_of']}")
        result_rows = []
        for program, report in zip(programs, result["reports"]):
            checks = {check["rule_id"]: check for check in report["checks"]}
            result_rows.append({"University": program.university, "Degree / campus": f"{program.degree} / {program.campus}",
                "Published-rate tuition estimate / ceiling (USD)": report["tuition"]["upper_usd"] or "Needs verification",
                **{RULE_NAMES[key]: STATUS[checks[key]["status"]] for key in ["tuition", "gpa", "english", "intake", "deadline"]}})
        show_table(result_rows)
        st.warning("These are individual checks against current evidence. Other eligibility requirements and admission risk still need review; these results are not tiered recommendations or admission guarantees.")
        st.download_button("Download assessment JSON", json.dumps(result, ensure_ascii=False, indent=2),
            file_name="gradmatch_m1_checks.json", mime="application/json", key="download_m1")

    st.subheader("Explore programs and official evidence")
    by_id = {program.program_id: program for program in programs}
    selected = st.selectbox("Program", list(by_id),
        format_func=lambda key: f"{by_id[key].university} — {by_id[key].degree} — {by_id[key].campus}", key="m1_selected_program")
    program = by_id[selected]
    st.markdown(f"**{program.program_name}** · {program.track}")
    st.markdown(f"[Program website]({program.official_url})")
    estimate = estimate_tuition(program.tuition)
    st.write("Tuition formula:", estimate.formula or "A reproducible full-program tuition formula is not available yet")
    st.write("Rate year:", estimate.rate_year or "Not verified")
    for note in program.notes + program.tuition.assumptions:
        st.write("• " + note)
    if result:
        report = next(report for report in result["reports"] if report["program_id"] == selected)
        for check in report["checks"]:
            with st.expander(f"{RULE_NAMES[check['rule_id']]}: {STATUS[check['status']]}"):
                st.write(check["explanation"])
                for warning in check["warnings"]: st.caption(warning)
                st.caption("Source ID:" + (", ".join(check["source_ids"]) or "No applicable evidence yet"))
    for source in sources.values():
        if source.program_id != selected: continue
        with st.expander("Official evidence · " + source.locator):
            st.markdown(f"[Open original page]({source.url})")
            st.caption(f"Retrieved:{source.retrieved_at.isoformat()} · Applicable rate / period:{source.effective_period or 'See field notes'}")
            st.write(source.fact_summary)
            st.code(source.source_excerpt, language=None)
            st.caption("Source ID:" + source.source_id)
