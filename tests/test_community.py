"""Bulk coverage, source boundaries and free profile-based exploration."""
from copy import deepcopy
from datetime import date
import json

import pytest
from streamlit.testing.v1 import AppTest

from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import load_seed
from gradmatch.community import COMMUNITY_FILE, application_fee_label, compile_community, exploration_rows, load_community
from gradmatch.directory import INDEX, bootstrap_directory, build_directory, comparison_rows, read_directory
from gradmatch.providers import OpenAIProvider
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import data_hash

AS_OF = date(2026, 11, 21)


def test_all_83_records_have_usable_reported_fields_and_pinned_provenance():
    p,s=load_seed(); before=data_hash(p,s)
    d=build_directory(p,s);rows=d['records']
    assert d['community_records']==d['total']==83 and d['official_records']==20
    assert all(len(r['community_facts']['language'])==4 for r in rows)
    assert sum(r['community_facts']['reported_gre']!='unknown' for r in rows)==82
    assert sum(bool(r['community_facts']['rounds']) for r in rows)==80
    assert sum(r['community_facts']['application_fee'] is not None for r in rows)==82
    assert all(r['community_facts']['application_url'].startswith('https://') for r in rows)
    assert all(r['community_facts']['verification_status']=='community_unverified' for r in rows)
    assert d['source_sha256']==json.loads(INDEX.read_text(encoding='utf-8'))['source_sha256']
    assert data_hash(p,s)==before and all(not r['recommendation_eligible'] for r in rows)


@pytest.mark.parametrize('mutation',['different_source','missing_row','duplicate_row','credentials','promoted'])
def test_runtime_rejects_mismatched_or_unsafe_community_input(tmp_path,mutation):
    index=json.loads(INDEX.read_text(encoding='utf-8'))
    d=json.loads(COMMUNITY_FILE.read_text(encoding='utf-8'))
    if mutation=='different_source':d['source_sha256']='0'*64
    elif mutation=='missing_row':d['rows'].pop()
    elif mutation=='duplicate_row':d['rows'][-1]=deepcopy(d['rows'][0])
    elif mutation=='credentials':d['rows'][0]['application_url']='https://user:secret@example.com/'
    else:d['rows'][0]['verification_status']='verified'
    path=tmp_path/'community.json';path.write_text(json.dumps(d),encoding='utf-8')
    with pytest.raises(ValueError):load_community(index,path)


def test_builder_rejects_a_different_source_file_before_any_import():
    with pytest.raises(ValueError,match='pinned source hash'):
        compile_community(b'{"rows": []}',json.loads(INDEX.read_text(encoding='utf-8')))


def test_application_fees_and_recommended_scores_never_become_tuition_or_minima():
    d=build_directory(*load_seed())
    for row in d['records']:
        facts=row['community_facts']
        assert facts['fee_currency'] is None
        assert all(r['reported_total'] is None for r in facts['language'] if r['kind']!='hard_min')
        if not row['linked_program_id']:
            assert row['tuition_upper_usd'] is None and row['tuition_lower_usd'] is None
            assert row['requirements']['GPA policy']=='Needs verification'
    zero=next(r['community_facts'] for r in d['records'] if r['community_facts']['application_fee']==0)
    assert application_fee_label(zero).startswith('0 ') and 'currency unverified' in application_fee_label(zero)
    fields={r['Field'] for r in comparison_rows(d['records'][:2])}
    assert {'Reported English (community)','Listed rounds (community)','Application fee (community)'}<=fields


def test_preliminary_pool_uses_reviewed_rules_and_never_creates_tiers():
    p,s=load_seed();d=build_directory(p,s);profile=tiering_profile()
    before=profile.model_dump(mode='json')
    rows=exploration_rows(d,profile,p,s,as_of=AS_OF)
    assert len(rows)==83 and any(r['status']=='Explore' for r in rows)
    assert all(r['personalized_tier'] is None and not r['recommendation_eligible'] for r in rows)
    assert profile.model_dump(mode='json')==before
    official={r['source_id'] for r in d['records'] if r['linked_program_id']}
    assert all(r['english_note'].startswith('Reviewed English check:') for r in rows if r['source_id'] in official)
    assert next(r for r in rows if r['source_id']=='sss-mit-eecs')['status']=='Availability / degree-route review'
    assert sum(r['status']=='Availability / degree-route review' for r in rows)>=4


def test_reported_score_comparison_keeps_versions_and_cycles_separate():
    p,s=load_seed();d=build_directory(p,s);profile=tiering_profile()
    profile.english.total=80
    rows=exploration_rows(d,profile,p,s,as_of=AS_OF)
    stanford=next(r for r in rows if r['source_id']=='sss-stanford-mscs')
    assert stanford['english_note'].startswith('Below reported overall minimum')
    profile.english.total=110
    assert next(r for r in exploration_rows(d,profile,p,s,as_of=AS_OF) if r['source_id']=='sss-stanford-mscs')['english_note'].startswith('At/above reported overall minimum')
    profile.intake.year=2028
    row=next(r for r in exploration_rows(d,profile,p,s,as_of=AS_OF) if r['source_id']=='sss-stanford-mscs')
    assert 'selected intake needs review' in row['english_note']


def test_preliminary_fields_survive_readonly_sqlite_recovery(tmp_path):
    database=bootstrap_public_catalog(tmp_path/'official')
    path=bootstrap_directory(database,tmp_path)
    before=read_directory(path)
    assert before['community_records']==83
    path.unlink()
    assert read_directory(bootstrap_directory(database,tmp_path))==before


def test_actual_form_saves_latest_profile_and_previews_83_without_a_model(tmp_path,monkeypatch):
    monkeypatch.setenv('GRADMATCH_DB_PATH',str(bootstrap_public_catalog(tmp_path/'public')))
    monkeypatch.setenv('GRADMATCH_PUBLIC_CACHE_DIR',str(tmp_path/'public'))
    monkeypatch.setenv('MODEL_ENABLED','false')
    def deny(*args,**kwargs):raise AssertionError('Free exploration requested a model')
    monkeypatch.setattr(OpenAIProvider,'generate',deny)
    app=AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=30).run()
    app.button(key='m35_load_example').click().run()
    app.text_input(key='m2_input_budget').set_value('50000')
    app.number_input(key='m2_input_english_total').set_value(80.0)
    app.button(key='m6_save_exploration').click().run()
    assert not app.exception
    session=app.session_state['m2_session']
    assert session.profile.tuition_budget_usd==50000 and session.profile.english.total==80
    assert len(app.dataframe[0].value)==83 and not session.usage and session.current_result is None
    assert any('Below reported overall minimum' in str(x) for x in app.dataframe[0].value.values.flatten())
    app.button(key='open_directory').click().run()
    app.text_input(key='directory_query').set_value('sss-stanford-mscs').run()
    assert not app.exception
    assert any('TOEFL /120 Reported minimum: 90' in m.value for m in app.markdown)
    assert session.profile.tuition_budget_usd==50000 and not session.usage
