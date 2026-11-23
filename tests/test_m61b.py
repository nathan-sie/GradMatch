"""Verify partial official records, conservative rules and catalog upgrades."""
from dataclasses import replace
from datetime import date
import hashlib
import json

import pytest

from gradmatch.bootstrap import bootstrap_public_catalog, resolve_app_database
from gradmatch.catalog import DEFAULT_SEED, M35_SEED, M61B_SEED, import_catalog, load_seed, read_catalog
from gradmatch.catalog_audit import audit_catalog
from gradmatch.config import load_settings
from gradmatch.constraints import check_constraints
from gradmatch.schemas import EnglishScore, GPA
from gradmatch.service import start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.ui_m1 import TOPICS
from gradmatch.validation import data_hash
from scripts.audit_catalog import build_report
from scripts.m5_fixtures import FixtureProvider

AS_OF = date(2026, 11, 20)


def checked(pid, profile=None):
    programs, sources = load_seed(M61B_SEED)
    p = next(p for p in programs if p.program_id == pid)
    report = check_constraints(profile or tiering_profile(), p, sources, as_of=AS_OF)
    return p, report, {c.rule_id: c for c in report.checks}


def test_batch_roundtrip_preserves_field_bindings_and_old_sources(tmp_path):
    programs, sources = load_seed(M61B_SEED)
    old_programs, old_sources = load_seed(M35_SEED)
    assert len(programs) == 12 and len(sources) == 43
    assert set(old_sources) < set(sources)
    assert all(sources[sid] == source for sid, source in old_sources.items())
    assert {p.program_id for p in old_programs} < {p.program_id for p in programs}
    database = tmp_path / 'catalog.db'
    import_catalog(M61B_SEED, database)
    restored, restored_sources = read_catalog(database)
    assert data_hash(restored, restored_sources) == data_hash(programs, sources)
    import_catalog(M61B_SEED, database)
    repeated, repeated_sources = read_catalog(database)
    assert len(repeated) == 12 and len(repeated_sources) == 43
    assert data_hash(repeated, repeated_sources) == data_hash(programs, sources)


@pytest.mark.parametrize('pid', ['ncsu-mcs-raleigh','rice-mcs-houston','uci-mcs-irvine',
    'uiuc-mcs-urbana','umass-mscs-amherst'])
def test_partial_price_observations_never_become_complete_budget_checks(pid):
    profile = tiering_profile()
    profile.tuition_budget_usd = '9999999'
    program, report, checks = checked(pid, profile)
    assert program.field_sources['tuition_review']
    assert report.tuition.upper_usd is None
    assert checks['tuition'].status == 'unknown'
    assert not report.recommendation_ready


def test_mcds_degree_review_does_not_invent_english_or_complete_eligibility():
    program, report, checks = checked('cmu-mcds-pittsburgh')
    assert checks['degree'].status == 'pass'
    assert checks['english'].status == checks['prerequisites'].status == 'unknown'
    assert program.recommended_topics and not program.required_topics
    assert not program.eligibility_review_complete and report.hard_checks_status == 'unknown'


def test_unknown_gpa_scope_is_a_catalog_gap_even_for_high_overall_gpa():
    profile = tiering_profile()
    profile.gpa = GPA(value='3.99', scale='4', scope='overall')
    program, report, checks = checked('uiuc-meng-ece-urbana', profile)
    assert checks['gpa'].status == 'unknown'
    assert checks['gpa'].reason_code == 'GPA_SCOPE_NOT_VERIFIED'
    audit = build_report(as_of=AS_OF)
    row = next(r for r in audit['catalog']['programs'] if r['program_id'] == program.program_id)
    assert not row['field_coverage']['gpa']['rule_usable']
    assert 'gpa' in row['catalog_gaps']


def test_tacoma_pathway_and_discretionary_requirements_stay_unresolved():
    profile = tiering_profile()
    profile.gpa = GPA(value='2.8',scale='4')
    profile.coursework['science'] = False
    program, report, checks = checked('uw-mscss-tacoma', profile)
    assert program.required_credits is None and report.tuition.upper_usd is None
    assert checks['gpa'].status == checks['prerequisites'].status == 'unknown'
    assert set(program.required_topics) <= set(TOPICS)


def test_tacoma_ielts_minimum_retains_below_recommended_conditions():
    profile = tiering_profile()
    profile.english = EnglishScore(version='ielts_9',total='6.5',test_date=date(2026,5,1))
    _, report, checks = checked('uw-mscss-tacoma', profile)
    assert checks['english'].status == 'pass' and checks['english'].warnings
    assert report.hard_checks_status == 'unknown' and not report.recommendation_ready


def test_stale_local_database_uses_new_cache_without_modifying_old_file(tmp_path, monkeypatch):
    import gradmatch.bootstrap as bootstrap
    legacy = tmp_path / 'old.db'
    import_catalog(M35_SEED, legacy)
    before = hashlib.sha256(legacy.read_bytes()).hexdigest()
    monkeypatch.setattr(bootstrap, 'DEFAULT_DATABASE', legacy)
    monkeypatch.delenv('GRADMATCH_DB_PATH', raising=False)
    monkeypatch.setenv('GRADMATCH_PUBLIC_CACHE_DIR', str(tmp_path / 'cache'))
    current = resolve_app_database()
    assert current != legacy and read_catalog(current)[0] == sorted(load_seed()[0], key=lambda p: p.program_id)
    assert hashlib.sha256(legacy.read_bytes()).hexdigest() == before
    # Explicit database selections retain their original, user-chosen semantics.
    monkeypatch.setenv('GRADMATCH_DB_PATH', str(legacy))
    assert resolve_app_database() == legacy and len(read_catalog(legacy)[0]) == 10


@pytest.mark.parametrize('strategy', ['fixed','react','plan'])
def test_all_strategies_use_the_same_expanded_catalog_with_offline_fixtures(strategy):
    programs, sources = load_seed(M61B_SEED)
    session = Session(profile=tiering_profile())
    result = start_task(session, request_id='m61b-' + strategy,
        programs=programs, sources=sources, settings=replace(load_settings(),enabled=False,api_key=''),
        as_of=AS_OF, strategy=strategy, provider=FixtureProvider())
    assert len(session.agent_task.programs) == 12
    assert result['data_hash'] == data_hash(programs, sources)
    assert not result['validation_errors']
    assert {r['program_id'] for r in result['recommendations']} == {'cmu-msaii-pittsburgh'}


def test_capture_failures_are_not_imported_as_verified_sources():
    receipts = json.loads((PROJECT_ROOT/'data/review/m61b_capture_receipts.json').read_text(encoding='utf-8'))
    _, sources = load_seed(M61B_SEED)
    failures = {r['raw_response_sha256'] for r in receipts['captures'] if r['status'] != 'captured'}
    assert len(failures) == 2
    assert not any(s.raw_response_sha256 in failures for s in sources.values())
