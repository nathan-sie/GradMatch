"""Search and compare all pinned program leads without making model requests."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from gradmatch.directory import UNKNOWN, comparison_rows, filter_records, tuition_label
from gradmatch.community import application_fee_label, exploration_rows, reported_language_label, reported_rounds_label


def render_directory(document):
    records = document["records"]
    by_id = {r["source_id"]: r for r in records}
    st.subheader("Program directory")
    st.write("Explore 83 programs with community-reported application details. Official snapshots supply reviewed policies where available.")
    columns = st.columns(3)
    columns[0].metric("Programs to explore", document["total"])
    columns[1].metric("With official snapshots", document["official_records"])
    columns[2].metric("Awaiting official review", document["total"] - document["official_records"])
    st.caption(f"Community snapshot: {document['upstream_generated']} · Reported intake: {document['source_intake']}. Field coverage is checked against {document['coverage_intake']}; this does not confirm every program's intake or current availability.")
    st.caption(f"Preliminary details maintained: {document['community_records']} programs · Language tests, GRE, application rounds, fees and application links · Community facts need confirmation.")
    st.info("Directory entries are leads for exploration. Admission tiers and applicant eligibility require the applicant workflow and supporting evidence. An unknown requirement does not mean it is waived.")
    query = st.text_input("Search programs", placeholder="University, program, campus or keyword", key="directory_query")
    left, right = st.columns(2)
    university = left.selectbox("University", ["All universities"] + sorted({r["university"] for r in records}), key="directory_university")
    review = right.selectbox("Review status", ["All programs", "Official snapshots available", "Needs official review", "Source-reported halt"], key="directory_review")
    visible = filter_records(records, query, review, university)
    st.caption(f"Showing {len(visible)} of {len(records)} programs")
    if visible:
        st.dataframe([{
            "University": r["university"], "Program": r["program_name"], "Campus": r["campus"],
            "Review status": r["review_status"], "Tuition estimate": tuition_label(r),
            "Reported GRE (community)": r['community_facts']['reported_gre'].replace('_', ' '),
            "Listed rounds (community)": reported_rounds_label(r['community_facts']),
            "Availability note": "Source reports a halt; verify officially" if r["source_reports_halted"] else "Current availability needs verification",
            "Program page": r["program_url"],
        } for r in visible], hide_index=True, width="stretch", height=420,
            column_config={"Program page": st.column_config.LinkColumn("Program page", display_text="Open page")})
    else:
        st.info("No directory entries match these filters. Try a broader search.")

    def label(sid):
        row = by_id[sid]
        return f"{row['university']} — {row['program_name']}"

    st.subheader("Compare programs")
    st.caption("Select up to four programs. Choices remain available when search filters change.")
    selected = st.multiselect("Programs to compare", list(by_id), format_func=label, max_selections=4, key="directory_compare")
    if selected:
        compared = [by_id[sid] for sid in selected]
        st.dataframe(comparison_rows(compared), hide_index=True, width="stretch")
        st.caption("Tuition estimates use the stated rate year and assumptions. They exclude living costs and unverified charges; future bills may differ.")
        st.download_button("Download comparison JSON", json.dumps({
            **{k: v for k, v in document.items() if k != "records"},
            "records": compared, "export_scope": "Selected directory entries; not recommendations",
        }, ensure_ascii=False, indent=2), "gradmatch_program_comparison.json", "application/json", key="directory_download")

    st.subheader("Program details")
    options = [r["source_id"] for r in visible]
    if options:
        # A prior detail selection may disappear after filtering.
        if st.session_state.get("directory_detail") not in options:
            st.session_state["directory_detail"] = options[0]
        sid = st.selectbox("Explore a program", options, format_func=label, key="directory_detail")
        row = by_id[sid]
        st.write(row["program_name"])
        st.link_button("Open program page", row["program_url"])
        st.caption("Community-reported URL; official identity and scope need review." if not row["linked_program_id"]
                   else f"Officially scoped record: {row['degree']} · {row['campus']} · {row['track']}")
        if row["source_reports_halted"]:
            st.warning("The imported community source reports a halt. This is unverified; confirm the current admission status on the program's website.")
        st.write("Estimated full-program tuition:", tuition_label(row))
        st.write("Fields usable for automatic checks:", ", ".join(row["verified_fields"]) or "None yet")
        st.write("Needs verification:", ", ".join(row["missing_fields"]) or "Applicant-specific checks still required")
        with st.expander('Community-reported application details', expanded=not bool(row['official_sources'])):
            facts = row['community_facts']
            st.caption(f"CS Grad tracker · {document['source_intake']} · Snapshot {document['upstream_generated']}. These reported values are preliminary. Reviewed official policies above take precedence.")
            st.write('English tests:', reported_language_label(facts))
            st.write('Reported GRE:', facts['reported_gre'].replace('_', ' '))
            st.write('Listed application rounds:', reported_rounds_label(facts))
            st.write('Reported application fee:', application_fee_label(facts))
            st.caption('Listed rounds can have different audiences or purposes. They do not establish a complete deadline schedule. No GPA or tuition amount is supplied by this tracker snapshot.')
            st.link_button('Open reported application portal', facts['application_url'], key='directory_apply_' + sid)
            st.markdown(f"[Tracker source snapshot]({document['source_url']}) · [CS Grad tracker](https://csgrad.com/tracker)")
        if row.get('cohort_context'):
            st.markdown('**Program-level admission context**')
            st.caption('These reviewed cohort statistics are not your admission probability. They do not establish applicant eligibility, goal fit or a formal recommendation.')
            source_map = {source['source_id']: source for source in row['official_sources']}
            for cohort in row['cohort_context']:
                st.write(f"{cohort['cycle_year']} cohort: {cohort['offers']} admission offers from {cohort['applications']} applications.")
                if cohort['cohort_planning_label']:
                    st.caption(f"Cohort-only planning label: {cohort['cohort_planning_label']}. Applicant checks and complete recommendation evidence are still required.")
                for sid in cohort['source_ids']:
                    st.markdown(f"[Cohort source]({source_map[sid]['url']})")
        details = [{"Field": label, "Reviewed policy": value} for label, value in row["requirements"].items() if value != UNKNOWN]
        if details:
            st.markdown("**Reviewed policy details**")
            st.caption("Policy details may require manual review even when the published values are known. They do not establish applicant eligibility.")
            st.dataframe(details, hide_index=True, width="stretch")
        with st.expander('Snapshot notes and review history'):
            st.caption('Earlier review limitations may be retained here. Current policy summaries and checks use the active evidence bindings.')
            for note in row['notes']:
                st.caption(note)
        for note in row["tuition_assumptions"]:
            st.caption(note)
        for source in row["official_sources"]:
            with st.expander("Official evidence · " + source["locator"]):
                st.link_button("Open source", source["url"], key="directory_source_" + source["source_id"])
                st.caption(f"Retrieved: {source['retrieved_at']} · Period: {source['effective_period'] or 'See field notes'}")
                if source.get('historical_field_groups'):
                    st.caption('Superseded fields: ' + ', '.join(source['historical_field_groups']) + '. These earlier bindings do not drive current checks.')
                st.write(source["fact_summary"])
                st.code(source["source_excerpt"], language=None)
        if not row["official_sources"]:
            st.caption("No reviewed official evidence is available for this entry yet. GPA, English requirements, tuition, deadlines and admission tiers remain unverified.")

    attribution = document["attribution"]
    st.caption(f"Community facts: [{attribution['creator']}]({attribution['project_url']}) · [{attribution['license']}]({attribution['license_url']}). Identity and reported application fields normalized into English and joined to separately reviewed official records. Source ranking labels and admissions datapoints are not used.")


def render_exploration(document, profile, programs, sources):
    st.subheader('Broader candidate exploration')
    st.caption('Uses your saved profile and all 83 maintained records. No model request. Explore means a lead for further review; GPA, costs and other missing requirements remain unresolved. Programs are listed alphabetically, without personal admission tiers.')
    if not st.session_state.get('m6_show_exploration'):
        if st.button('Preview all 83 programs (no model call)', key='m6_preview'):
            st.session_state['m6_show_exploration'] = True
    if not st.session_state.get('m6_show_exploration'):
        return
    rows = exploration_rows(document, profile, programs, sources,
        as_of=datetime.now(ZoneInfo('America/Los_Angeles')).date())
    st.caption(f"Profile version {profile.profile_version} · Community snapshot {document['upstream_generated']} · {document['source_intake']}")
    st.write(f"{sum(r['status'] == 'Explore' for r in rows)} exploration leads · {sum(r['status'] == 'Review reported concerns' for r in rows)} with issues to review · {sum(r['status'] == 'Availability / degree-route review' for r in rows)} with availability or degree-route flags")
    st.dataframe([{'University': r['university'], 'Program': r['program'], 'Exploration status': r['status'],
        'English note': r['english_note'], 'GRE': r['gre_note'], 'Reviewed tuition': r['tuition'],
        'Listed rounds (community)': r['listed_rounds'], 'Application portal': r['application_url']} for r in rows],
        hide_index=True, width='stretch', height=420,
        column_config={'Application portal': st.column_config.LinkColumn('Application portal', display_text='Open portal')})
    st.download_button('Download preliminary candidate pool', json.dumps({
        'scope': 'Preliminary exploration; not formal recommendations', 'profile_version': profile.profile_version,
        'source_url': document['source_url'], 'source_sha256': document['source_sha256'],
        'snapshot_date': document['upstream_generated'], 'intake': document['source_intake'], 'records': rows,
    }, ensure_ascii=False, indent=2), 'gradmatch_preliminary_candidates.json', 'application/json', key='m6_exploration_download')
