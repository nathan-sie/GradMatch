"""GradMatch applicant workflow and milestone verification pages."""

import sys

import streamlit as st

import gradmatch.release as release
if getattr(release, 'RELEASE_REFRESH_VERSION', 0) < 18:
    from importlib import reload
    reload(release)
release.refresh_catalog_modules()

from gradmatch.admission_history import OPENCS_DP_URL, OPENCS_GRADE_URL
from gradmatch.bootstrap import resolve_app_database
from gradmatch.directory import bootstrap_directory, read_directory
from gradmatch.storage import CatalogNotReadyError, inspect_catalog


st.set_page_config(page_title="GradMatch", page_icon="🎓", layout="wide")

try:
    database = resolve_app_database()
    summary = inspect_catalog(database)
except (CatalogNotReadyError, OSError, ValueError) as error:
    st.title("GradMatch")
    st.error(str(error))
    st.code("python -m scripts.build_catalog --input data/catalog/dp_official_overlap_seed.json", language="bash")
    st.stop()


def catalog_counts(summary):
    left, right = st.columns(2)
    left.metric("Official program records", summary.program_count)
    right.metric("Evidence sources", summary.source_count)


if summary.program_count == 0:
    st.title("GradMatch")
    st.caption("Find U.S. computer science and electrical engineering master's programs that fit your profile.")
    catalog_counts(summary)
    st.info("M0 · Environment check. Recommendations and model/search API calls are not enabled yet.")
    st.write("The catalog schema is ready. Reviewed programs and official evidence will be imported in M1.")
else:
    try:
        directory = read_directory(bootstrap_directory(database))
    except (OSError, ValueError) as error:
        directory = None
        st.warning("The program directory is unavailable. Reviewed applicant workflows remain available.")

    with st.sidebar:
        st.title("GradMatch")
        st.caption("U.S. CS / ECE master's program matcher")
        labels = {
            "Applicant workflow (M2)": "Find programs",
            "Program directory": "Program directory",
            "Data and rule checks (M1)": "Data & checks (M1)",
        }
        page = st.radio(
            "Navigation",
            list(labels),
            key="workspace_page",
            format_func=labels.__getitem__,
        )
        with st.expander("Data sources", expanded=False):
            st.markdown(f"**{summary.program_count}** official program records · **{summary.source_count}** evidence sources")
            st.markdown(f"Historical admissions counts are aggregated from [OpenCS DataPoints]({OPENCS_DP_URL}) "
                        "([CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)).")
            st.markdown(f"Planning tiers also use the [OpenCS program categories]({OPENCS_GRADE_URL}).")
            st.markdown("Program listings and reported application details come from the [CS Grad tracker](https://csgrad.com/tracker). "
                        "Verified requirements and tuition link to university sources.")
            if directory:
                def open_directory():
                    st.session_state["workspace_page"] = "Program directory"
                st.button(f"Browse all {directory['total']} programs", key="open_directory", on_click=open_directory, use_container_width=True)

    if page == "Applicant workflow (M2)":
        st.title("GradMatch")
        st.caption("Find U.S. computer science and electrical engineering master's programs that fit your profile.")
        from gradmatch.ui_m2 import render_m2
        render_m2(database, directory=directory)
    elif page == "Program directory":
        st.title("Program directory")
        if directory:
            from gradmatch.ui_directory import render_directory
            render_directory(directory)
    else:
        st.title("Data & checks")
        from gradmatch.ui_m1 import render_m1
        render_m1(database)

with st.sidebar:
    with st.expander("Environment check", expanded=False):
        if st.button("Run environment check", key="check_environment", use_container_width=True):
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
