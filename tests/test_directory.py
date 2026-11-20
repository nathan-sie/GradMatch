"""Directory coverage, evidence boundaries, cache recovery and actual page interactions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest
from streamlit.testing.v1 import AppTest

from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import load_seed
from gradmatch.directory import (
    INDEX, LINKS, bootstrap_directory, build_directory, comparison_rows,
    filter_records, read_directory,
)
from gradmatch.providers import OpenAIProvider
from gradmatch.storage import PROJECT_ROOT, connect_read_only
from gradmatch.validation import data_hash


def test_all_83_leads_are_explorable_without_promoting_community_claims():
    programs, sources = load_seed()
    before = data_hash(programs, sources)
    document = build_directory(programs, sources)
    records = document["records"]
    assert document["total"] == len({r["source_id"] for r in records}) == 83
    assert document["official_records"] == 16
    assert sum(r["source_reports_halted"] for r in records) == 4
    assert sum(r["tuition_upper_usd"] is not None for r in records) == 7
    assert all(not r["recommendation_eligible"] for r in records)
    assert data_hash(programs, sources) == before
    assert {r["source_id"] for r in records} == {r["source_id"] for r in json.loads(INDEX.read_text(encoding="utf-8"))["rows"]}
    mit = next(r for r in records if r["source_id"] == "sss-mit-eecs")
    assert mit["tuition_upper_usd"] is None and not mit["official_sources"]
    assert "doctoral" in " ".join(mit["review_flags"]).lower()
    assert mit["eligibility_review"] == "Needs verification"


def test_only_exact_reviewed_links_enrich_a_lead_and_unknown_intake_stays_unknown():
    programs, sources = load_seed()
    rows = build_directory(programs, sources)["records"]
    nyu = next(r for r in rows if r["source_id"] == "b-plus-nyu-tandon")
    assert nyu["linked_program_id"] == "nyu-mscs-tandon-brooklyn"
    assert nyu["campus"] == "Brooklyn" and nyu["tuition_upper_usd"] == "78780"
    assert "Intake" in nyu["missing_fields"]
    assert "GPA policy" in nyu["missing_fields"]
    # Another NYU program must not inherit Tandon tuition or scope.
    other_nyu = [r for r in rows if "New York University" in r["university"] and not r["linked_program_id"]]
    assert other_nyu and all(r["tuition_upper_usd"] is None for r in other_nyu)


def test_duplicate_identity_links_are_rejected_and_legacy_catalog_does_not_invent_links():
    programs, sources = load_seed()
    links = json.loads(LINKS.read_text(encoding="utf-8"))
    duplicate = deepcopy(links)
    duplicate["catalog_links"].append(duplicate["catalog_links"][0])
    with pytest.raises(ValueError, match="Ambiguous"):
        build_directory(programs, sources, links=duplicate)
    legacy = build_directory(programs[:1], {sid:s for sid,s in sources.items() if s.program_id == programs[0].program_id})
    assert legacy["total"] == 83 and legacy["official_records"] == 1


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "https://user:secret@example.com/"])
def test_directory_rejects_non_public_link_schemes_and_embedded_credentials(bad_url):
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    index["rows"][0]["program_url"] = bad_url
    with pytest.raises(ValueError, match="Invalid public"):
        build_directory(*load_seed(), index=index)


def test_search_filters_and_comparison_keep_unknowns_and_source_halt_flags():
    rows = build_directory(*load_seed())["records"]
    assert len(filter_records(rows, review="Official snapshots available")) == 16
    assert len(filter_records(rows, review="Needs official review")) == 67
    assert len(filter_records(rows, review="Source-reported halt")) == 4
    assert len(filter_records(rows, "NYU BROOKLYN")) == 1
    assert not filter_records(rows, "this university does not exist")
    halted = filter_records(rows, review="Source-reported halt")[0]
    nyu = filter_records(rows, "NYU BROOKLYN")[0]
    comparison = comparison_rows([halted, nyu])
    tuition = next(r for r in comparison if r["Field"] == "Estimated full-program tuition")
    assert "Needs verification" in tuition.values()
    assert any("78,780" in str(v) and "estimate" in str(v) for v in tuition.values())
    assert any("official confirmation needed" in str(v) for r in comparison for v in r.values())


def test_directory_sqlite_is_read_only_rebuildable_and_preserves_official_database(tmp_path):
    database = bootstrap_public_catalog(tmp_path / "official")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with ThreadPoolExecutor(max_workers=3) as pool:
        paths = list(pool.map(lambda _: bootstrap_directory(database, tmp_path), range(3)))
    assert len(set(paths)) == 1
    path = paths[0]
    assert read_directory(path)["total"] == 83
    with closing(connect_read_only(path)) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM directory_records")
    path.write_bytes(b"corrupt app-managed directory cache")
    assert read_directory(bootstrap_directory(database, tmp_path))["official_records"] == 16
    path.unlink()
    assert read_directory(bootstrap_directory(database, tmp_path))["total"] == 83
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_actual_page_browses_searches_compares_and_preserves_applicant_session(tmp_path, monkeypatch):
    database = bootstrap_public_catalog(tmp_path / "official")
    monkeypatch.setenv("GRADMATCH_DB_PATH", str(database))
    monkeypatch.setenv("GRADMATCH_PUBLIC_CACHE_DIR", str(tmp_path / "public"))
    monkeypatch.setenv("MODEL_ENABLED", "false")
    def deny_model(*args, **kwargs):
        raise AssertionError("Directory must not request a model")
    monkeypatch.setattr(OpenAIProvider, "generate", deny_model)
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
    app.button(key="m2_load_example").click().run()
    profile = app.session_state["m2_session"].profile.model_dump(mode="json")
    app.button(key="open_directory").click().run()
    assert not app.exception
    assert [m.value for m in app.metric][-3:] == ["83", "16", "67"]
    assert len(app.dataframe[0].value) == 83
    app.multiselect(key="directory_compare").set_value(["sss-mit-eecs", "b-plus-nyu-tandon"]).run()
    assert not app.exception and len(app.dataframe) == 2
    assert any("78,780" in str(v) for v in app.dataframe[1].value.values.flatten())
    app.text_input(key="directory_query").set_value("nyu brooklyn").run()
    assert not app.exception and len(app.dataframe[0].value) == 1
    assert len(app.multiselect(key="directory_compare").value) == 2
    app.text_input(key="directory_query").set_value("no matching university here").run()
    assert not app.exception and any("No directory entries" in i.value for i in app.info)
    app.text_input(key="directory_query").set_value("").run()
    app.selectbox(key="directory_review").set_value("Source-reported halt").run()
    assert not app.exception and len(app.dataframe[0].value) == 4
    assert app.session_state["m2_session"].profile.model_dump(mode="json") == profile
    assert not app.session_state["m2_session"].usage
    app.radio(key="workspace_page").set_value("Applicant workflow (M2)").run()
    assert not app.exception and app.text_input(key="m2_input_budget").value == "70000"
