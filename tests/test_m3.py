"""Cloud cold starts, private sessions, secret handling, and bounded concurrency."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from threading import Event
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from gradmatch.bootstrap import bootstrap_public_catalog, resolve_app_database
from gradmatch.catalog import load_seed, read_catalog
from gradmatch.config import ConfigurationError, load_settings
from gradmatch.providers import ModelUnavailable, OpenAIProvider
from gradmatch.ranking import RankingDraft
from gradmatch.session import Session
from gradmatch.storage import CatalogNotReadyError, PROJECT_ROOT, connect_read_only, inspect_catalog
from gradmatch.validation import data_hash


def test_cold_bootstrap_rebuilds_valid_public_records_and_stays_read_only(tmp_path):
    database = bootstrap_public_catalog(tmp_path)
    assert inspect_catalog(database).program_count == 8
    expected, expected_sources = load_seed()
    actual, actual_sources = read_catalog(database)
    assert data_hash(actual, actual_sources) == data_hash(expected, expected_sources)
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    assert bootstrap_public_catalog(tmp_path) == database
    assert hashlib.sha256(database.read_bytes()).hexdigest() == digest
    with closing(connect_read_only(database)) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM programs")
    database.unlink()
    restored = bootstrap_public_catalog(tmp_path)
    assert inspect_catalog(restored).source_count == 20


def test_concurrent_cold_start_and_corrupt_managed_cache_are_recoverable(tmp_path):
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: bootstrap_public_catalog(tmp_path), range(3)))
    assert len(set(results)) == 1
    results[0].write_bytes(b"corrupt managed cache")
    assert inspect_catalog(bootstrap_public_catalog(tmp_path)).program_count == 8


def test_explicit_missing_database_is_not_replaced_by_automatic_bootstrap(tmp_path, monkeypatch):
    missing = tmp_path / "user-selected.db"
    monkeypatch.setenv("GRADMATCH_DB_PATH", str(missing))
    with pytest.raises(CatalogNotReadyError): resolve_app_database()
    assert not missing.exists()


def test_two_app_connections_are_isolated_and_reconnect_is_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_ENABLED", "false")
    monkeypatch.setenv("GRADMATCH_DB_PATH", str(bootstrap_public_catalog(tmp_path)))
    first = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=20).run()
    first.button(key="m2_load_example").click().run()
    first.button(key="m2_generate").click().run()
    first.chat_input(key="m2_chat").set_value("Change my tuition budget to 50000").run()
    second = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=20).run()
    assert not first.exception and not second.exception
    assert second.session_state["m2_session"].profile.tuition_budget_usd is None
    second.button(key="m2_load_example").click().run()
    assert second.session_state["m2_session"].profile.tuition_budget_usd == 70000
    assert first.session_state["m2_session"].profile.tuition_budget_usd == 50000
    assert not second.session_state["m2_session"].messages
    assert first.session_state["m2_session"].session_id != second.session_state["m2_session"].session_id
    reconnect = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=20).run()
    assert not reconnect.exception and reconnect.session_state["m2_session"].current_result is None
    assert reconnect.session_state["m2_session"].profile.tuition_budget_usd is None


def test_cloud_secrets_support_and_malformed_secrets_do_not_expose_values(tmp_path, monkeypatch):
    for key in ["MODEL_PROVIDER", "MODEL_NAME", "MODEL_ENABLED", "MODEL_API_KEY", "OPENAI_API_KEY"]:
        monkeypatch.delenv(key, raising=False)
    (tmp_path / "config").mkdir()
    shutil.copyfile(PROJECT_ROOT / "config/app.json", tmp_path / "config/app.json")
    secret_dir = tmp_path / ".streamlit"
    secret_dir.mkdir()
    secret_file = secret_dir / "secrets.toml"
    secret_file.write_text('MODEL_ENABLED="true"\nOPENAI_API_KEY="SYNTHETIC-PRIVATE-VALUE"\n', encoding="utf-8")
    settings = load_settings(tmp_path)
    assert settings.ready and "SYNTHETIC-PRIVATE-VALUE" not in repr(settings)
    assert "SYNTHETIC-PRIVATE-VALUE" not in json.dumps(settings.public())
    secret_file.write_text('OPENAI_API_KEY="SYNTHETIC-PRIVATE-VALUE" [invalid', encoding="utf-8")
    with pytest.raises(ConfigurationError) as error: load_settings(tmp_path)
    assert "SYNTHETIC-PRIVATE-VALUE" not in str(error.value)


def test_loading_example_preserves_explicit_model_opt_in_without_calling_api(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "SYNTHETIC-TEST-ONLY")
    monkeypatch.setenv("GRADMATCH_DB_PATH", str(bootstrap_public_catalog(tmp_path)))
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=20).run()
    app.checkbox(key="m2_allow_model").check().run()
    assert app.checkbox(key="m2_allow_model").value
    app.button(key="m2_load_example").click().run()
    assert not app.exception and app.checkbox(key="m2_allow_model").value
    assert app.session_state["m2_session"].profile.tuition_budget_usd == 70000
    assert not app.session_state["m2_session"].usage


def test_third_paid_request_is_refused_while_two_are_active(monkeypatch):
    entered = [Event(), Event()]
    release = Event()
    config = replace(load_settings(), enabled=True, api_key="TEST-ONLY")
    draft = RankingDraft(profile_version=1, status="insufficient_evidence", recommendations=[], pending_order=[], observations=[])
    def invoke(index):
        def create(**kwargs):
            entered[index].set()
            assert release.wait(5)
            return SimpleNamespace(model=config.model, id=f"test-{index}", status="completed", output_text=draft.model_dump_json(), usage=None)
        return OpenAIProvider(config, client=SimpleNamespace(responses=SimpleNamespace(create=create))).generate(RankingDraft, "rank", {}, Session())
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(invoke, index) for index in range(2)]
        try:
            assert all(event.wait(3) for event in entered)
            with pytest.raises(ModelUnavailable, match="slots are busy"):
                OpenAIProvider(config).generate(RankingDraft, "rank", {}, Session())
        finally:
            release.set()
        assert all(future.result() == draft for future in pending)
