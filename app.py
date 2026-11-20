"""GradMatch applicant workflow and milestone verification pages."""

import sys

import streamlit as st

from gradmatch.bootstrap import resolve_app_database
from gradmatch.storage import CatalogNotReadyError, inspect_catalog


st.set_page_config(page_title="GradMatch", page_icon="🎓", layout="centered")
st.title("GradMatch")
st.caption("U.S. CS / ECE master's program matching for international applicants")

try:
    database = resolve_app_database()
    summary = inspect_catalog(database)
except (CatalogNotReadyError, OSError, ValueError) as error:
    st.error(str(error))
    st.code("python -m scripts.build_catalog --input data/catalog/m35_seed.json", language="bash")
    st.stop()

left, right = st.columns(2)
left.metric("Programs in catalog", summary.program_count)
right.metric("Evidence sources", summary.source_count)
st.caption("Release M5-2026-11-19 · Read-only public catalog · Profile and chat memory are private to this browser session")
if summary.program_count == 0:
    st.info("M0 · Environment check. Recommendations and model/search API calls are not enabled yet.")
    st.write("The catalog schema is ready. Reviewed programs and official evidence will be imported in M1.")
else:
    page = st.radio("Workspace", ["Applicant workflow (M2)", "Data and rule checks (M1)"], key="workspace_page", horizontal=True)
    if page == "Applicant workflow (M2)":
        from gradmatch.ui_m2 import render_m2
        render_m2(database)
    else:
        from gradmatch.ui_m1 import render_m1
        render_m1(database)

if st.button("Run environment check", key="check_environment"):
    st.success("Environment check passed: the page is running and SQLite is accessible in read-only mode.")
    st.json(
        {
            "milestone": "M3" if summary.program_count else "M0",
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "database_schema": summary.schema_version,
            "programs": summary.program_count,
            "sources": summary.source_count,
            "application_database_access": "read_only",
            "model_api_calls": len(st.session_state["m2_session"].usage) if "m2_session" in st.session_state else 0,
            "search_api_calls": 0,
        }
    )

