"""Priority eligibility repairs and source-bound, non-personal cohort context."""
from dataclasses import asdict
from datetime import date
import json

import pytest
from streamlit.testing.v1 import AppTest

from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import DEFAULT_SEED, M61I_SEED, load_seed
from gradmatch.catalog_audit import audit_catalog
from gradmatch.constraints import check_constraints
from gradmatch.directory import build_directory
from gradmatch.ranking import RankingDraft
from gradmatch.schemas import Intake
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.tiers import reviewed_cohort_context
from gradmatch.validation import validate_shortlist

AS_OF=date(2026,11,21)
MCDS='cmu-mcds-pittsburgh'
NYU='nyu-mscs-tandon-brooklyn'

def report(pid,profile=None,programs=None,sources=None,as_of=AS_OF):
    if programs is None:programs,sources=load_seed()
    p=next(p for p in programs if p.program_id==pid)
    r=check_constraints(profile or tiering_profile(),p,sources,as_of=as_of)
    return r,{c.rule_id:c for c in r.checks}

def test_priority_batch_preserves_every_previous_source_and_prices():
    programs,sources=load_seed(DEFAULT_SEED);old_programs,old_sources=load_seed(M61I_SEED)
    assert len(programs)==20 and len(sources)==145
    assert all(sources[k]==v for k,v in old_sources.items())
    assert {p.program_id:p.tuition for p in programs}=={p.program_id:p.tuition for p in old_programs}
    manifest=json.loads((PROJECT_ROOT/'data/review/m61j_field_reviews.json').read_text(encoding='utf-8'))
    assert len(manifest['programs_enriched'])==2 and len(manifest['new_source_ids'])==7

def test_mcds_only_english_remains_unknown_for_the_reference_profile():
    r,checks=report(MCDS)
    assert {c.rule_id for c in r.checks if c.status=='unknown'}=={'english'}
    assert checks['prerequisites'].status=='not_applicable'
    assert checks['remaining_eligibility'].status=='pass' and not r.recommendation_ready
    assert checks['english'].reason_code=='ENGLISH_RULE_NOT_VERIFIED'
    assert set(checks['english'].source_ids)=={MCDS+'-mcds_program-m61j',MCDS+'-scs_admissions-m61j'}
    assert 'Historical or typical' in checks['english'].explanation

@pytest.mark.parametrize('test,total',[('toefl_120','100'),('toefl_120','120'),('ielts_9','9'),('det_160','160')])
def test_cached_threshold_or_perfect_score_cannot_create_a_current_english_pass(test,total):
    from gradmatch.schemas import EnglishScore
    profile=tiering_profile()
    profile.english=EnglishScore(version=test,total=total,test_date=date(2025,11,1))
    r,checks=report(MCDS,profile)
    assert checks['english'].status=='unknown' and not r.recommendation_ready

def test_other_mcds_background_keeps_preparation_and_extended_track_review():
    profile=tiering_profile();profile.degree.field='other'
    r,checks=report(MCDS,profile)
    assert checks['prerequisites'].reason_code=='BACKGROUND_EQUIVALENCY_REQUIRES_REVIEW'
    assert not r.recommendation_ready

def test_nyu_materials_and_dated_cycle_do_not_invent_a_gpa_scope_or_tier():
    r,checks=report(NYU)
    assert {c.rule_id for c in r.checks if c.status=='unknown'}=={'gpa'}
    assert checks['gpa'].reason_code=='GPA_SCOPE_NOT_VERIFIED'
    assert checks['intake'].status=='pass' and checks['deadline'].status=='pass'
    assert checks['remaining_eligibility'].status=='pass' and not r.recommendation_ready
    programs,_=load_seed();p=next(p for p in programs if p.program_id==NYU)
    assert any('optional' in text.lower() for text in p.application_materials)
    assert not p.admission_evidence

@pytest.mark.parametrize('intake,status',[(Intake(year=2027,term='spring'),'fail'),(Intake(year=2028,term='fall'),'unknown')])
def test_nyu_closed_spring_and_later_cycle_are_not_the_open_fall_2027_route(intake,status):
    profile=tiering_profile();profile.intake=intake
    _,checks=report(NYU,profile)
    assert checks['intake'].status==status

@pytest.mark.parametrize('as_of,status',[(date(2026,12,2),'pass'),(date(2027,2,15),'unknown'),(date(2027,2,16),'fail')])
def test_nyu_final_round_remains_after_priority_and_then_closes(as_of,status):
    _,checks=report(NYU,as_of=as_of)
    assert checks['deadline'].status==status
    if as_of==date(2027,2,15):assert checks['deadline'].reason_code=='DEADLINE_TODAY_TIME_UNKNOWN'

@pytest.mark.parametrize('missing',['nyu_cycle','nyu_deadlines'])
def test_nyu_dates_need_both_the_cycle_anchor_and_the_linked_table(missing):
    programs,sources=load_seed();sources=dict(sources)
    sources.pop(NYU+'-'+missing+'-m61j')
    _,checks=report(NYU,programs=programs,sources=sources)
    assert checks['intake'].status=='unknown' and checks['deadline'].status=='unknown'

def test_program_cohort_context_has_counts_and_sources_without_a_personal_recommendation():
    programs,sources=load_seed();profile=tiering_profile()
    p=next(p for p in programs if p.program_id==MCDS)
    rows=reviewed_cohort_context(p,sources,profile,AS_OF)
    assert len(rows)==1 and (rows[0]['applications'],rows[0]['offers'])==(481,145)
    assert rows[0]['cohort_planning_label']=='Reach' and 'not an applicant' in rows[0]['scope']
    draft=RankingDraft(profile_version=profile.profile_version,status='insufficient_evidence',recommendations=[dict(
        program_id=MCDS,tier='Reach',goal_feature_ids=[p.goal_features[0].feature_id],
        tier_evidence_ids=[rows[0]['evidence_id']],comparison_dimensions=['selectivity'],lower_risk_rationale=None,
        limitations=['Program cohort only; current English eligibility remains unverified.'])],pending_order=[],observations=[])
    result=validate_shortlist(draft,profile,programs,programs,sources,as_of=AS_OF)
    assert not result['recommendations']
    assert any('HARD_CHECKS_NOT_PASSED' in error.get('codes',[]) for error in result['validation_errors'])

@pytest.mark.parametrize('mutation',['missing_source','tampered_count','unreviewed','future_cycle','no_intake'])
def test_cohort_context_rejects_unusable_evidence(mutation):
    programs,sources=load_seed();sources=dict(sources);profile=tiering_profile()
    p=next(p for p in programs if p.program_id==MCDS).model_copy(deep=True)
    e=p.admission_evidence[0]
    if mutation=='missing_source':sources.pop(e.source_ids[0])
    elif mutation=='tampered_count':e.offers+=1
    elif mutation=='unreviewed':e.reviewed=False
    elif mutation=='future_cycle':e.cycle_year=2027
    else:profile.intake=None
    assert not reviewed_cohort_context(p,sources,profile,AS_OF)

def test_directory_counts_readiness_and_context_remain_separate():
    programs,sources=load_seed(DEFAULT_SEED);d=build_directory(programs,sources)
    assert d['total']==83 and d['official_records']==20
    contexts=[r for r in d['records'] if r['cohort_context']]
    assert len(contexts)==2 and all(not r['recommendation_eligible'] for r in contexts)
    row=next(r for r in d['records'] if r['linked_program_id']==MCDS)
    assert 'English policy' in row['missing_fields'] and 'Other eligibility' in row['verified_fields']
    assert any('Confirm the applicable current minimum' in text for text in row['requirements'].values())
    audit=audit_catalog(programs,sources,as_of=AS_OF,intake=Intake(year=2027,term='fall'))
    s=audit['summary']
    assert s['full_eligibility_reviews']==7 and s['fields']['prerequisites']['usable']==10
    assert s['fields']['intake']['usable']==14 and s['fields']['deadline']['usable']==12
    assert s['reference_hard_checks_ready']==2 and s['reference_formal_evidence_ready']==1

def test_actual_directory_displays_mcds_statistics_and_english_gap_without_model_calls(tmp_path,monkeypatch):
    cache=tmp_path/'public'
    monkeypatch.setenv('GRADMATCH_DB_PATH',str(bootstrap_public_catalog(cache)))
    monkeypatch.setenv('GRADMATCH_PUBLIC_CACHE_DIR',str(cache));monkeypatch.setenv('MODEL_ENABLED','false')
    app=AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=30).run()
    app.button(key='open_directory').click().run()
    app.text_input(key='directory_query').set_value('Computational Data Science').run()
    assert not app.exception
    assert any('145 admission offers from 481 applications' in m.value for m in app.markdown)
    assert any('Cohort-only planning label: Reach' in c.value for c in app.caption)
    assert any('not your admission probability' in c.value for c in app.caption)
    assert not app.session_state['m2_session'].usage

def test_hot_update_keeps_the_existing_session_and_profile(monkeypatch):
    import gradmatch.release as release
    session=Session(profile=tiering_profile());session.messages.append({'role':'user','content':'Preserve this test conversation'})
    before=asdict(session);kind=type(session)
    monkeypatch.setattr(release,'_signature',None)
    release.refresh_catalog_modules()
    assert type(session) is kind and asdict(session)==before and release.RELEASE_REFRESH_VERSION>=4
