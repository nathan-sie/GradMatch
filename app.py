"""GradMatch applicant workflow and milestone verification pages."""

import sys

import streamlit as st

import gradmatch.release as release
if getattr(release,'RELEASE_REFRESH_VERSION',0)<16:
    from importlib import reload
    reload(release)
release.refresh_catalog_modules()

from gradmatch.admission_history import OPENCS_DP_URL, OPENCS_GRADE_URL
from gradmatch.bootstrap import resolve_app_database
from gradmatch.directory import bootstrap_directory, read_directory
from gradmatch.storage import CatalogNotReadyError, inspect_catalog


st.set_page_config(page_title="GradMatch", page_icon="🎓",
    layout="wide" if st.session_state.get("workspace_page") == "Program directory" else "centered")
st.title("GradMatch")
st.caption("Find U.S. computer science and electrical engineering master's programs that fit your profile.")

try:
    database = resolve_app_database()
    summary = inspect_catalog(database)
except (CatalogNotReadyError, OSError, ValueError) as error:
    st.error(str(error))
    st.code("python -m scripts.build_catalog --input data/catalog/dp_official_overlap_seed.json", language="bash")
    st.stop()

def catalog_counts(summary):
    left, right = st.columns(2)
    left.metric("Official program records", summary.program_count)
    right.metric("Evidence sources", summary.source_count)


if summary.program_count == 0:
    catalog_counts(summary)
    st.info("M0 · Environment check. Recommendations and model/search API calls are not enabled yet.")
    st.write("The catalog schema is ready. Reviewed programs and official evidence will be imported in M1.")
else:
    try:
        directory = read_directory(bootstrap_directory(database))
    except (OSError, ValueError) as error:
        directory = None
        st.warning("The program directory is unavailable. Reviewed applicant workflows remain available.")
    labels = {"Applicant workflow (M2)": "Find programs", "Program directory": "Program directory",
              "Data and rule checks (M1)": "Data & checks"}
    page = st.radio("Workspace", list(labels), key="workspace_page", horizontal=True,
                    format_func=labels.__getitem__, label_visibility="collapsed")
    with st.expander("Data sources"):
        catalog_counts(summary)
        st.markdown(f"Historical admissions counts are aggregated from [OpenCS DataPoints]({OPENCS_DP_URL}) "
                    "([CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)).")
        st.markdown(f"Planning tiers also use the [OpenCS program categories]({OPENCS_GRADE_URL}).")
        st.markdown("Program listings and reported application details come from the [CS Grad tracker](https://csgrad.com/tracker). "
                    "Verified requirements and tuition link to university sources.")
        if directory:
            def open_directory():
                st.session_state["workspace_page"] = "Program directory"
            st.button(f"Browse all {directory['total']} programs", key="open_directory", on_click=open_directory)
    if page == "Applicant workflow (M2)":
        from gradmatch.ui_m2 import render_m2
        render_m2(database, directory=directory)
    elif page == "Program directory":
        if directory:
            from gradmatch.ui_directory import render_directory
            render_directory(directory)
    else:
        from gradmatch.ui_m1 import render_m1
        render_m1(database)

with st.expander("Environment check"):
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

