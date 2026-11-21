"""Preparation, enrollment validity, immutable field history and actual form inputs."""
from dataclasses import asdict
from datetime import date
from decimal import Decimal
import json

import pytest
from streamlit.testing.v1 import AppTest

from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import M61G_SEED, load_seed
from gradmatch.constraints import check_constraints, evidence_ids
from gradmatch.coursework import TOPICS
from gradmatch.directory import build_directory
from gradmatch.schemas import EnglishScore
from gradmatch.session import Session, ProfilePatch, apply_patch, tiering_profile
from gradmatch.storage import PROJECT_ROOT


def assess(pid,profile=None,programs=None,sources=None):
    if programs is None:programs,sources=load_seed()
    p=next(p for p in programs if p.program_id==pid)
    report=check_constraints(profile or tiering_profile(),p,sources,as_of=date(2026,11,21))
    return report,{c.rule_id:c for c in report.checks}


def test_seven_reviews_preserve_112_sources_and_use_distinct_current_bindings():
    programs,sources=load_seed();_,old=load_seed(M61G_SEED)
    assert len(programs)==20 and len(sources)==125
    assert all(sources[sid]==source for sid,source in old.items())
    review=json.loads((PROJECT_ROOT/'data/review/m61h_field_reviews.json').read_text(encoding='utf-8'))
    assert len(review['programs_enriched'])==7 and len(review['new_source_ids'])==13
    for p in programs:
        for group,ids in p.field_sources.items():
            if not group.startswith('history:'):continue
            active=p.field_sources.get(group[8:],p.field_sources.get('english',[]) if group=='history:english_minimum' else [])
            assert active and not set(ids)&set(active)
            assert all(i not in evidence_ids(p,group[8:],sources,tiering_profile()) for i in ids)


@pytest.mark.parametrize('tamper',['no_replacement','cross_program','same_active_and_history','changed_active_value','unbound_original'])
def test_history_never_weakens_current_catalog_validation(tmp_path,tamper):
    seed=json.loads((PROJECT_ROOT/'data/catalog/m61h_seed.json').read_text(encoding='utf-8'))
    p=next(p for p in seed['programs'] if p['program_id']=='uci-mcs-irvine')
    if tamper=='no_replacement':p['field_sources'].pop('prerequisites')
    elif tamper=='cross_program':p['field_sources']['history:prerequisites']=[seed['sources'][0]['source_id']]
    elif tamper=='same_active_and_history':p['field_sources']['history:prerequisites']=p['field_sources']['prerequisites'][:]
    elif tamper=='changed_active_value':p['prerequisites_complete']=False
    else:p['field_sources'].pop('history:prerequisites')
    path=tmp_path/'invalid.json';path.write_text(json.dumps(seed),encoding='utf-8')
    with pytest.raises(ValueError):load_seed(path)


def test_uci_cs_preparation_can_pass_without_turning_recommendations_into_cutoffs():
    profile=tiering_profile();profile.coursework['programming']=False
    report,checks=assess('uci-mcs-irvine',profile)
    assert checks['prerequisites'].status=='not_applicable' and checks['remaining_eligibility'].status=='pass'
    assert report.recommendation_ready
    profile.degree.field='other'
    report,checks=assess('uci-mcs-irvine',profile)
    assert checks['prerequisites'].reason_code=='BACKGROUND_EQUIVALENCY_REQUIRES_REVIEW'
    assert not report.recommendation_ready


def test_uci_hard_check_readiness_does_not_authorize_an_invented_target_tier():
    from gradmatch.ranking import RecommendationDraft
    from gradmatch.validation import tier_errors
    programs,sources=load_seed();p=next(p for p in programs if p.program_id=='uci-mcs-irvine')
    profile=tiering_profile();report,_=assess(p.program_id,profile,programs,sources)
    assert report.recommendation_ready
    item=RecommendationDraft(program_id=p.program_id,tier='Target',goal_feature_ids=[p.goal_features[0].feature_id],
        tier_evidence_ids=[],comparison_dimensions=['gpa'],lower_risk_rationale='A test-only unsupported label',limitations=['No admission evidence'])
    assert tier_errors(item,profile,p,sources,date(2026,11,21))


@pytest.mark.parametrize('pid,missing',[
    ('nyu-mscs-tandon-brooklyn','university_science_year'),
    ('wisc-ms-cs-professional-madison','college_mathematics_year'),
    ('cornell-meng-cs-ithaca','advanced_data_structures'),
    ('uw-mscss-tacoma','computer_architecture'),
])
def test_preparation_needs_exact_topics_and_does_not_assume_an_exception(pid,missing):
    profile=tiering_profile();profile.coursework=dict.fromkeys(TOPICS,True)
    _,checks=assess(pid,profile)
    assert checks['prerequisites'].status=='pass'
    profile.coursework.pop(missing)
    _,checks=assess(pid,profile)
    assert checks['prerequisites'].reason_code=='COURSEWORK_NOT_PROVIDED'
    profile.coursework[missing]=False
    _,checks=assess(pid,profile)
    assert checks['prerequisites'].status=='unknown' and checks['prerequisites'].reason_code=='COURSEWORK_DEFICIENCY_REQUIRES_REVIEW'


@pytest.mark.parametrize('pid,cutoff,day_before',[
    ('uiuc-mcs-urbana','2025-08-23','2025-08-22'),
    ('uiuc-meng-ece-urbana','2025-08-23','2025-08-22'),
    ('wisc-ms-cs-professional-madison','2025-09-03','2025-09-02'),
])
def test_enrollment_validity_is_not_assessment_day_validity(pid,cutoff,day_before):
    profile=tiering_profile();profile.english.test_date=date.fromisoformat(day_before)
    _,checks=assess(pid,profile)
    assert checks['english'].reason_code=='ENGLISH_BEFORE_INTAKE_CUTOFF'
    profile.english.test_date=date.fromisoformat(cutoff)
    _,checks=assess(pid,profile)
    assert checks['english'].status=='pass' and checks['english'].warnings
    profile.english.test_date=None
    _,checks=assess(pid,profile)
    assert checks['english'].status=='unknown'
    profile.english.test_date=date.fromisoformat(cutoff);profile.intake.year=2028
    _,checks=assess(pid,profile)
    assert checks['english'].status=='unknown' and not checks['english'].source_ids


@pytest.mark.parametrize('pid,total', [('uiuc-mcs-urbana','90'),('uiuc-meng-ece-urbana','90'),('wisc-ms-cs-professional-madison','85'),('uw-mscss-tacoma','85')])
def test_conditional_scores_remain_unknown_despite_being_above_a_floor(pid,total):
    profile=tiering_profile();profile.english.total=Decimal(total)
    _,checks=assess(pid,profile)
    assert checks['english'].status=='unknown' and checks['english'].reason_code=='ENGLISH_CONDITIONAL_REVIEW'


@pytest.mark.parametrize('pid',['uiuc-mcs-urbana','uiuc-meng-ece-urbana','wisc-ms-cs-professional-madison'])
def test_missing_calendar_cannot_fall_back_to_retired_score_floor(pid):
    programs,sources=load_seed();p=next(p for p in programs if p.program_id==pid)
    sources.pop(p.field_sources['english'][-1])
    _,checks=assess(pid,programs=programs,sources=sources)
    assert checks['english'].status=='unknown' and not checks['english'].source_ids


def test_tacoma_uses_application_date_validity_and_does_not_infer_det_acceptance():
    profile=tiering_profile();profile.english.test_date=date(2025,1,1)
    _,checks=assess('uw-mscss-tacoma',profile)
    assert checks['english'].status=='pass'  # Valid now; its future enrollment anniversary is irrelevant.
    profile.english.test_date=date(2024,11,21)
    _,checks=assess('uw-mscss-tacoma',profile)
    assert checks['english'].reason_code=='ENGLISH_EXPIRED'
    profile.english=EnglishScore(version='det_160',total='150',test_date=date(2026,1,1))
    _,checks=assess('uw-mscss-tacoma',profile)
    assert checks['english'].status=='unknown'


def test_cornell_department_speaking_floor_overrides_general_table_without_a_false_pass():
    profile=tiering_profile();profile.english=EnglishScore(version='toefl_6',total='5.5',test_date=date(2026,2,1),
        subscores={'reading':'5','listening':'5','speaking':'5','writing':'5'})
    _,checks=assess('cornell-meng-cs-ithaca',profile)
    assert checks['english'].reason_code=='ENGLISH_SUBSCORE_BELOW_MINIMUM'
    profile.english.subscores['speaking']=Decimal('5.5')
    _,checks=assess('cornell-meng-cs-ithaca',profile)
    assert checks['english'].reason_code=='ENGLISH_MINIMUM_ONLY'
    profile.english=EnglishScore(version='toefl_120',total='110',test_date=date(2025,11,1))
    _,checks=assess('cornell-meng-cs-ithaca',profile)
    assert checks['english'].reason_code=='ENGLISH_RULE_NOT_VERIFIED'


def test_directory_distinguishes_current_fields_from_immutable_history():
    document=build_directory(*load_seed());row=next(r for r in document['records'] if r['linked_program_id']=='uci-mcs-irvine')
    assert document['total']==83 and document['official_records']==20
    assert any('prerequisites' in s['historical_field_groups'] for s in row['official_sources'])
    assert 'Prerequisites' in row['verified_fields'] and 'Other eligibility' in row['verified_fields']
    assert not row['recommendation_eligible']


def test_explicit_coursework_patches_share_the_form_vocabulary_and_preserve_other_fields():
    session=Session(profile=tiering_profile());before=session.profile.tuition_budget_usd
    message='I completed computer organization.'
    patch=ProfilePatch(intent='update_profile',operations=[dict(field='coursework.computer_organization',value_json='true',explicit_span=message)],referenced_program_ids=[],ambiguous_fields=[])
    session.profile.coursework.pop('computer_organization',None)
    apply_patch(session,patch,message)
    assert session.profile.coursework['computer_organization'] is True and session.profile.tuition_budget_usd==before


def test_hot_update_expands_whitelist_without_recreating_applicant_state(monkeypatch):
    import gradmatch.session as session_module
    import gradmatch.release as release
    session=Session(profile=tiering_profile());session.messages.append({'role':'user','content':'Keep this conversation'})
    original=asdict(session);session_class=type(session)
    monkeypatch.setattr(session_module,'TOPICS',{'programming'})
    monkeypatch.setattr(session_module,'LEAF_FIELDS',{'coursework.programming'})
    monkeypatch.setattr(release,'_signature',None)
    release.refresh_catalog_modules()
    assert 'coursework.advanced_data_structures' in session_module.LEAF_FIELDS
    assert set(TOPICS)<=session_module.TOPICS and type(session) is session_class
    assert asdict(session)==original


def test_actual_form_can_save_new_specific_topics_without_any_model_request(tmp_path,monkeypatch):
    monkeypatch.setenv('GRADMATCH_DB_PATH',str(bootstrap_public_catalog(tmp_path/'public')))
    monkeypatch.setenv('GRADMATCH_PUBLIC_CACHE_DIR',str(tmp_path/'public'))
    monkeypatch.setenv('MODEL_ENABLED','false')
    app=AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=30).run()
    app.button(key='m2_load_example').click().run()
    keys=['university_science_year','college_mathematics_year','advanced_data_structures','documented_cs_preparation','computer_organization']
    app.multiselect(key='m2_input_courses').set_value(keys).run()
    app.button(key='m2_save_profile').click().run()
    assert not app.exception
    session=app.session_state['m2_session']
    assert all(session.profile.coursework[k] for k in keys) and not session.usage
