"""Scope, cost boundaries and conservative qualification checks for batch two."""
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json

import pytest

from gradmatch.catalog import M61C_SEED as DEFAULT_SEED, M61B_SEED, import_catalog, load_seed as latest_load_seed, read_catalog
from gradmatch.config import load_settings
from gradmatch.constraints import check_constraints
from gradmatch.schemas import EnglishScore, GPA
from gradmatch.service import start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import data_hash
from scripts.audit_catalog import build_report
from scripts.m5_fixtures import FixtureProvider
from scripts.verify_m61c import verify_receipts

AS_OF=date(2026,11,20)


def load_seed(path=DEFAULT_SEED):
    """Keep this historical batch's original facts and expected counts frozen."""
    return latest_load_seed(path)
NYU='nyu-mscs-tandon-brooklyn'
CORNELL='cornell-meng-cs-ithaca'
WISC='wisc-ms-cs-professional-madison'
TAMU='tamu-mcs-college-station'


def checked(pid,profile=None):
    programs,sources=load_seed()
    program=next(p for p in programs if p.program_id==pid)
    report=check_constraints(profile or tiering_profile(),program,sources,as_of=AS_OF)
    return program,report,{c.rule_id:c for c in report.checks}


def test_second_batch_preserves_sources_and_survives_sqlite_roundtrip(tmp_path):
    programs,sources=load_seed()
    prior,prior_sources=load_seed(M61B_SEED)
    assert len(programs)==16 and len(sources)==62
    assert len(programs)-len(prior)==4 and len(sources)-len(prior_sources)==19
    assert all(sources[sid]==source for sid,source in prior_sources.items())
    path=tmp_path/'catalog.db'
    import_catalog(DEFAULT_SEED,path)
    assert data_hash(*read_catalog(path))==data_hash(programs,sources)
    import_catalog(DEFAULT_SEED,path)
    assert data_hash(*read_catalog(path))==data_hash(programs,sources)


@pytest.mark.parametrize('pid,total',[(NYU,'78780'),(CORNELL,'73946')])
@pytest.mark.parametrize('delta,expected',[('0','pass'),('-0.01','fail')])
def test_tuition_boundaries_use_complete_credit_or_academic_year_units(pid,total,delta,expected):
    profile=tiering_profile()
    profile.tuition_budget_usd=Decimal(total)+Decimal(delta)
    _,report,checks=checked(pid,profile)
    assert report.tuition.lower_usd==report.tuition.upper_usd==Decimal(total)
    assert checks['tuition'].status==expected
    assert report.tuition.rate_year=='2026-2027'
    assert not report.recommendation_ready


@pytest.mark.parametrize('pid',[NYU,CORNELL])
def test_published_rates_never_guarantee_the_future_final_bill(pid):
    profile=tiering_profile()
    profile.budget_basis='guaranteed_final'
    _,_,checks=checked(pid,profile)
    assert checks['tuition'].status=='unknown'
    assert checks['tuition'].reason_code=='FINAL_TUITION_NOT_GUARANTEED'


def test_nyu_credit_mismatch_invalidates_an_otherwise_present_rate():
    programs,sources=load_seed()
    nyu=next(p for p in programs if p.program_id==NYU)
    nyu.required_credits=31
    report=check_constraints(tiering_profile(),nyu,sources,as_of=AS_OF)
    assert report.tuition.upper_usd is None
    assert next(c for c in report.checks if c.rule_id=='tuition').status=='unknown'


@pytest.mark.parametrize('score,status',[('89','fail'),('90','pass')])
def test_nyu_uses_its_own_english_minimum(score,status):
    profile=tiering_profile()
    profile.english=EnglishScore(version='toefl_120',total=score,test_date=date(2025,5,1))
    _,_,checks=checked(NYU,profile)
    assert checks['english'].status==status


@pytest.mark.parametrize('day,status',[(19,'fail'),(20,'pass')])
def test_nyu_application_time_validity_boundary_keeps_published_anniversary_semantics(day,status):
    profile=tiering_profile()
    profile.english=EnglishScore(version='ielts_9',total='7',test_date=date(2024,11,day))
    _,_,checks=checked(NYU,profile)
    assert checks['english'].status==status


@pytest.mark.parametrize('pid',[TAMU,NYU,WISC])
def test_yearless_deadlines_are_not_relabelled_as_verified_fall_2027(pid):
    p,_,checks=checked(pid)
    assert not p.supported_intakes and not p.deadlines
    assert checks['intake'].status==checks['deadline'].status=='unknown'


def test_tamu_quick_admit_and_likelihood_scores_are_not_general_hard_cutoffs():
    profile=tiering_profile()
    profile.gpa=GPA(value='2.9',scale='4')
    p,_,checks=checked(TAMU,profile)
    assert p.gpa is None and checks['gpa'].status=='unknown'
    assert checks['gre'].status=='not_applicable'
    assert p.required_credits==30


def test_cornell_continuation_gpa_does_not_become_an_admission_cutoff():
    profile=tiering_profile()
    profile.gpa=GPA(value='2.6',scale='4')
    p,report,checks=checked(CORNELL,profile)
    assert p.gpa is None and checks['gpa'].status=='unknown'
    assert checks['intake'].status=='pass' and checks['deadline'].status=='unknown'
    assert checks['english'].status=='unknown' and report.hard_checks_status=='unknown'


def test_wisconsin_goal_context_retains_the_current_cpt_restriction():
    p,_,_=checked(WISC)
    assert '2026-08-24' in ' '.join(p.notes)
    assert all('CPT' in f.statement and 'not guaranteed' in f.statement for f in p.goal_features)
    assert p.field_sources['internship_policy']


@pytest.mark.parametrize('scope,value,status',[
    ('overall','3.5','unknown'),('last_60_semester','3.5','pass'),('last_60_semester','2.8','unknown')])
def test_wisconsin_gpa_scope_and_alternative_master_route_remain_distinct(scope,value,status):
    profile=tiering_profile()
    profile.gpa=GPA(value=value,scale='4',scope=scope)
    _,_,checks=checked(WISC,profile)
    assert checks['gpa'].status==status


def test_wisconsin_enrollment_anchored_english_policy_is_not_passed_using_assessment_date():
    p,report,checks=checked(WISC)
    assert not p.english and p.field_sources['english_policy']
    assert checks['english'].status=='unknown'
    assert report.tuition.upper_usd is None


def test_batch_audit_separates_more_computable_prices_from_recommendation_readiness():
    report=build_report(seed=DEFAULT_SEED,as_of=AS_OF)
    summary=report['catalog']['summary']
    assert summary['programs']==16 and summary['sources']==62
    assert summary['computable_verified_tuition']==7
    assert summary['reference_formal_evidence_ready']==1
    assert report['candidates']['summary']['screening_counts']['already_linked_identity']==16
    assert len(report['candidates']['first_expansion_batch'])==4
    assert not any(c['recommendation_eligible'] for c in report['candidates']['inventory'])


def test_receipt_chain_excludes_forbidden_pages_and_checks_new_source_bytes():
    programs,sources=load_seed()
    proof=verify_receipts(programs,sources)
    assert proof['new_sources_checked']==19
    assert proof['historical_source_objects_preserved']==43
    receipts=json.loads((PROJECT_ROOT/'data/review/m61c_capture_receipts.json').read_text(encoding='utf-8'))
    failures={r['raw_response_sha256'] for r in receipts['captures'] if r['status']!='captured'}
    assert len(failures)==2
    assert not any(s.raw_response_sha256 in failures for s in sources.values())


@pytest.mark.parametrize('strategy',['fixed','react','plan'])
def test_three_strategies_share_new_data_without_promoting_partial_records(strategy):
    programs,sources=load_seed()
    session=Session(profile=tiering_profile())
    result=start_task(session,request_id='m61c-'+strategy,programs=programs,sources=sources,
        settings=replace(load_settings(),enabled=False,api_key=''),as_of=AS_OF,
        strategy=strategy,provider=FixtureProvider())
    assert result['data_hash']==data_hash(programs,sources)
    assert not result['validation_errors']
    assert {r['program_id'] for r in result['recommendations']}=={'cmu-msaii-pittsburgh'}
