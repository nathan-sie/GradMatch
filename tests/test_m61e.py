"""Twelve-program repair coverage, policy boundaries and hot-update recovery."""

from contextlib import closing
from datetime import date
import hashlib
import json
import sqlite3

import pytest

import gradmatch.catalog as catalog
from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import M61C_SEED, M61E_SEED, load_seed as latest_load_seed, read_catalog
from gradmatch.constraints import check_constraints
from gradmatch.directory import build_directory, comparison_rows
from gradmatch.schemas import GPA
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import data_hash


def load_seed(path=M61E_SEED):
    return latest_load_seed(path)


def record(pid):
    programs, sources = load_seed()
    p = next(p for p in programs if p.program_id == pid)
    profile = tiering_profile()
    report = check_constraints(profile, p, sources, as_of=date(2026, 11, 20))
    return p, {c.rule_id: c for c in report.checks}


def test_twelve_programs_gain_twenty_sources_without_changing_historical_evidence():
    programs, sources = load_seed()
    _, prior_sources = load_seed(M61C_SEED)
    assert len(programs) == 16 and len(sources) == 82
    assert all(sources[sid] == source for sid, source in prior_sources.items())
    review = json.loads((PROJECT_ROOT/'data/review/m61e_field_reviews.json').read_text(encoding='utf-8'))
    assert len(review['programs_enriched']) == 12
    assert set(review['new_source_ids']) == set(sources) - set(prior_sources)
    receipts = json.loads((PROJECT_ROOT/'data/review/m61e_capture_receipts.json').read_text(encoding='utf-8'))
    for sid in review['new_source_ids']:
        source = sources[sid]
        matches = [r for r in receipts['captures'] if r.get('url') == str(source.url)
                   and r.get('raw_response_sha256') == source.raw_response_sha256]
        assert len(matches) == 1 and matches[0]['status'] == 'captured' and matches[0]['http_status'] == 200
        raw = PROJECT_ROOT/'work/m61e_research'/(matches[0]['key']+'.html')
        if raw.exists():
            assert hashlib.sha256(raw.read_bytes()).hexdigest() == source.raw_response_sha256


@pytest.mark.parametrize('pid', [
    'uw-ece-msece-pmp-seattle', 'uiuc-mcs-urbana', 'uci-mcs-irvine',
    'rice-mcs-houston', 'umass-mscs-amherst', 'usc-mscs-general-los-angeles', 'neu-mscs-boston',
])
def test_new_optional_gre_policies_have_actual_automatic_support(pid):
    p, checks = record(pid)
    assert p.gre_policy == 'not_required' and checks['gre'].status == 'not_applicable'
    assert checks['gre'].source_ids


def test_uw_stem_degree_rule_and_future_cycle_limit_remain_explicit():
    p, checks = record('uw-ece-msece-pmp-seattle')
    assert p.accepted_degree_fields == ['CS','ECE','STEM']
    assert checks['degree'].status == 'pass' and checks['degree'].source_ids
    programs, sources = load_seed()
    usc = next(p for p in programs if p.program_id == 'usc-mscs-general-los-angeles')
    profile = tiering_profile()
    profile.intake.year = 2028
    checks = {c.rule_id:c for c in check_constraints(profile,usc,sources,as_of=date(2026,11,20)).checks}
    assert checks['gre'].status == 'unknown'


def test_recommended_scores_and_conditional_policies_are_not_automatic_hard_rules():
    programs, sources = load_seed()
    directory = build_directory(programs, sources)
    rows = {r['source_id']:r for r in directory['records']}
    assert directory['total'] == 83 and directory['official_records'] == 16
    assert 'recommended' in rows['a-uiuc-mcs']['requirements']['GPA policy']
    assert 'recommended' in rows['b-neu-mscs']['requirements']['English policy']
    assert rows['b-neu-mscs']['field_coverage']['english']['rule_usable'] is False
    assert 'international' in rows['b-ncsu-mcs']['requirements']['GRE policy']
    _, checks = record('ncsu-mcs-raleigh')
    assert checks['remaining_eligibility'].status == 'unknown'
    for sid in ['a-uiuc-mcs','b-uiuc-ece-meng']:
        assert 'enrollment' in rows[sid]['requirements']['English policy']
        assert rows[sid]['field_coverage']['english']['rule_usable'] is False
    assert rows['b-umass-mscs']['tuition_upper_usd'] is None
    assert '60,750' in rows['b-umass-mscs']['requirements']['Cost context']
    assert all(not r['recommendation_eligible'] for r in directory['records'])
    compared = comparison_rows([rows['b-neu-mscs'],rows['a-uiuc-mcs']])
    assert any(r['Field'] == 'GPA policy' for r in compared)
    assert any('June 15' in str(v) and 'July 1' in str(v) for r in compared for v in r.values())


def test_tampered_policy_notes_do_not_survive_source_binding_check():
    programs, sources = load_seed()
    neu = next(p for p in programs if p.program_id == 'neu-mscs-boston')
    index = next(i for i,n in enumerate(neu.notes) if n.startswith('English policy:'))
    neu.notes[index] = 'English policy: Guaranteed admission with no English test.'
    row = next(r for r in build_directory(programs,sources)['records'] if r['source_id'] == 'b-neu-mscs')
    assert row['requirements']['English policy'] == 'Needs verification'


def test_active_pointer_changes_are_read_without_reimporting_modules(tmp_path, monkeypatch):
    pointer = tmp_path/'active.json'
    # Symlinks are unnecessary: the pointer may only name a sibling seed.
    old = tmp_path/'old.json'
    new = tmp_path/'new.json'
    old.write_bytes(M61C_SEED.read_bytes())
    new.write_bytes(M61E_SEED.read_bytes())
    monkeypatch.setattr(catalog,'ACTIVE_SEED',pointer)
    pointer.write_text('{"seed":"old.json"}',encoding='utf-8')
    assert len(read_catalog(bootstrap_public_catalog(tmp_path/'cache'))[1]) == 62
    pointer.write_text('{"seed":"new.json"}',encoding='utf-8')
    rebuilt = bootstrap_public_catalog(tmp_path/'cache')
    assert len(read_catalog(rebuilt)[1]) == 82
    assert data_hash(*read_catalog(rebuilt)) == data_hash(*load_seed())
    pointer.write_text('{"seed":"../escape.json"}',encoding='utf-8')
    with pytest.raises(ValueError,match='active catalog pointer'):
        catalog.current_seed()


def test_hosted_cached_old_imports_refresh_without_replacing_applicant_state(tmp_path, monkeypatch):
    import gradmatch.bootstrap as bootstrap
    import gradmatch.release as release
    from gradmatch.session import Session
    session = Session(profile=tiering_profile())
    original = session.profile.model_dump(mode='json')
    monkeypatch.setattr(catalog,'current_seed',lambda:M61C_SEED)
    monkeypatch.setattr(bootstrap,'current_seed',lambda:M61C_SEED)
    assert len(read_catalog(bootstrap.bootstrap_public_catalog(tmp_path/'public'))[1]) == 62
    monkeypatch.setattr(release,'_signature',None)
    release.refresh_catalog_modules()
    assert len(read_catalog(bootstrap.bootstrap_public_catalog(tmp_path/'public'))[1]) == len(latest_load_seed()[1])
    assert session.profile.model_dump(mode='json') == original and not session.usage
    # Ordinary rerenders must not repeatedly reload code or discard session data.
    def deny_reload(*args,**kwargs):
        raise AssertionError('Unchanged release must reuse the existing modules')
    monkeypatch.setattr(release.importlib,'reload',deny_reload)
    release.refresh_catalog_modules()
    assert session.profile.model_dump(mode='json') == original
