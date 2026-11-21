"""Conservative tuition ceilings, dated scope and source dependencies."""
from datetime import date
from decimal import Decimal
import json

import pytest
from streamlit.testing.v1 import AppTest

from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import M61H_SEED, M61I_SEED, load_seed as current_load_seed
from gradmatch.catalog_audit import audit_catalog
from gradmatch.constraints import check_constraints, estimate_tuition
from gradmatch.directory import build_directory, tuition_label
from gradmatch.schemas import Intake, TuitionPolicy
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT

CEILINGS={
    'wisc-ms-cs-professional-madison':'45102.00',
    'uiuc-meng-ece-urbana':'60666',
    'cmu-ms-ece-pittsburgh':'92265',
    'ncsu-mcs-raleigh':'67983',
}

def load_seed(path=M61I_SEED):
    """Keep the pricing checkpoint pinned to its reviewed dataset."""
    return current_load_seed(path)

def assess(pid,profile=None,p=None,sources=None):
    if sources is None:
        programs,sources=load_seed()
        p=next(p for p in programs if p.program_id==pid)
    report=check_constraints(profile or tiering_profile(),p,sources,as_of=date(2026,11,21))
    return report,{c.rule_id:c for c in report.checks}

def test_seven_programs_preserve_every_old_source_and_add_thirteen():
    programs,sources=load_seed();_,previous=load_seed(M61H_SEED)
    assert len(programs)==20 and len(sources)==138
    assert all(sources[k]==v for k,v in previous.items())
    manifest=json.loads((PROJECT_ROOT/'data/review/m61i_field_reviews.json').read_text(encoding='utf-8'))
    assert len(manifest['programs_enriched'])==7 and len(manifest['new_source_ids'])==13
    assert manifest['prior_sources_preserved']==125

@pytest.mark.parametrize('pid,ceiling',CEILINGS.items())
@pytest.mark.parametrize('delta,expected',[('0','pass'),('0.01','unknown'),('-0.01','pass')])
def test_budget_can_cover_a_ceiling_but_a_lower_budget_does_not_prove_failure(pid,ceiling,delta,expected):
    profile=tiering_profile();profile.tuition_budget_usd=Decimal(ceiling)-Decimal(delta)
    report,checks=assess(pid,profile)
    assert report.tuition.reason_code=='MAXIMUM_ONLY_TUITION_BOUND'
    assert report.tuition.lower_usd is None and report.tuition.upper_usd==Decimal(ceiling)
    assert checks['tuition'].status==expected
    if expected=='unknown':assert checks['tuition'].reason_code=='TUITION_CEILING_ABOVE_BUDGET'
    else:assert checks['tuition'].warnings

@pytest.mark.parametrize('pid',CEILINGS)
def test_zero_budget_and_final_price_guarantee_are_not_supported_by_a_ceiling(pid):
    profile=tiering_profile();profile.tuition_budget_usd=Decimal('0')
    _,checks=assess(pid,profile)
    assert checks['tuition'].status=='unknown'
    profile.tuition_budget_usd=Decimal('200000');profile.budget_basis='guaranteed_final'
    _,checks=assess(pid,profile)
    assert checks['tuition'].reason_code=='FINAL_TUITION_NOT_GUARANTEED'

@pytest.mark.parametrize('pid',CEILINGS)
def test_ceiling_never_carries_into_another_intake_or_unsupported_study_schedule(pid):
    profile=tiering_profile();profile.intake=Intake(year=2028,term='fall')
    report,checks=assess(pid,profile)
    assert report.tuition.upper_usd is None and checks['tuition'].status=='unknown'
    if pid in {'cmu-ms-ece-pittsburgh','uiuc-meng-ece-urbana'}:
        profile=tiering_profile();profile.study_mode='part_time'
        report,checks=assess(pid,profile)
        assert report.tuition.upper_usd is None and checks['tuition'].reason_code=='TUITION_SCHEDULE_SCOPE_UNVERIFIED'

@pytest.mark.parametrize('pid',CEILINGS)
def test_every_rate_scope_and_unit_dependency_is_required(pid):
    programs,sources=load_seed();original=next(p for p in programs if p.program_id==pid)
    for sid in original.field_sources['tuition_upper']:
        p=original.model_copy(deep=True)
        p.field_sources['tuition_upper'].remove(sid)
        report,checks=assess(pid,p=p,sources=sources)
        assert report.tuition.upper_usd is None and checks['tuition'].status=='unknown'
    p=original.model_copy(deep=True);p.tuition.unit_rate_lower=Decimal('0')
    report,checks=assess(pid,p=p,sources=sources)
    assert report.tuition.upper_usd is None  # Unknown minimum must not become a source-free point/range price.

@pytest.mark.parametrize('pid',['wisc-ms-cs-professional-madison','ncsu-mcs-raleigh'])
def test_credit_based_ceiling_requires_the_exact_reviewed_degree_credit_total(pid):
    programs,sources=load_seed();p=next(p for p in programs if p.program_id==pid).model_copy(deep=True)
    p.required_credits+=Decimal('1')
    report,checks=assess(pid,p=p,sources=sources)
    assert report.tuition.upper_usd is None and checks['tuition'].status=='unknown'

def test_ceiling_math_is_decimal_and_still_requires_a_billing_unit_count():
    policy=TuitionPolicy(basis='per_credit',unit_rate_upper='1503.40',required_units_upper='30',rate_year='2026-2027')
    assert estimate_tuition(policy).upper_usd==Decimal('45102.00')
    policy.required_units_upper=None
    assert estimate_tuition(policy).reason_code=='MISSING_TOTAL_UNITS'
    policy.currency='EUR'
    assert estimate_tuition(policy).upper_usd is None

def test_wisconsin_dated_intake_does_not_reuse_a_yearless_deadline_for_other_years():
    _,checks=assess('wisc-ms-cs-professional-madison')
    assert checks['intake'].status=='pass' and checks['deadline'].status=='pass'
    profile=tiering_profile();profile.intake=Intake(year=2028,term='fall')
    _,checks=assess('wisc-ms-cs-professional-madison',profile)
    assert checks['intake'].status=='unknown' and checks['deadline'].status=='unknown'

def test_cmu_new_checklist_and_degree_do_not_turn_score_floors_into_full_english_eligibility():
    report,checks=assess('cmu-ms-ece-pittsburgh')
    assert checks['degree'].status=='pass' and checks['remaining_eligibility'].status=='pass'
    assert checks['prerequisites'].status=='not_applicable'
    assert checks['english'].status=='unknown' and not report.recommendation_ready

def test_minimum_only_price_and_unverified_prices_keep_their_distinct_behavior():
    profile=tiering_profile();profile.tuition_budget_usd=Decimal('100000')
    report,checks=assess('duke-ms-ece-durham',profile)
    assert report.tuition.upper_usd is None and checks['tuition'].reason_code=='TUITION_MINIMUM_EXCEEDS_BUDGET'
    for pid in ['rice-mcs-houston','uw-mscss-tacoma','uiuc-mcs-urbana']:
        report,checks=assess(pid)
        assert report.tuition.upper_usd is None and checks['tuition'].status=='unknown'

def test_directory_and_audit_distinguish_ceilings_from_quotes_and_admission_evidence():
    programs,sources=load_seed();document=build_directory(programs,sources)
    for row in document['records']:
        if row['linked_program_id'] in CEILINGS:
            assert 'At most USD' in tuition_label(row) and 'ceiling' in tuition_label(row)
            assert row['tuition_lower_usd'] is None and not row['recommendation_eligible']
    audit=audit_catalog(programs,sources,as_of=date(2026,11,21),intake=Intake(year=2027,term='fall'))
    summary=audit['summary']
    assert summary['computable_verified_tuition']==12
    assert summary['maximum_only_tuition']==4 and summary['two_sided_tuition_estimates']==8
    assert summary['minimum_only_tuition']==1 and summary['full_eligibility_reviews']==5
    assert summary['reference_hard_checks_ready']==2 and summary['reference_formal_evidence_ready']==1
    assert summary['reviewed_recent_cohorts']==2 and summary['reviewed_recent_admitted_cases']==0

def test_actual_directory_filter_keeps_the_selected_program_and_detail_body_consistent(tmp_path,monkeypatch):
    cache=tmp_path/'public'
    monkeypatch.setenv('GRADMATCH_DB_PATH',str(bootstrap_public_catalog(cache)))
    monkeypatch.setenv('GRADMATCH_PUBLIC_CACHE_DIR',str(cache));monkeypatch.setenv('MODEL_ENABLED','false')
    app=AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=30).run()
    app.button(key='open_directory').click().run()
    for query,pid in [('b-uci-mcs','uci-mcs-irvine'),('a-plus-wisc-cs-pmp','wisc-ms-cs-professional-madison')]:
        app.text_input(key='directory_query').set_value(query).run()
        assert not app.exception
        selected=app.selectbox(key='directory_detail').value
        assert selected==query
        assert app.session_state['directory_detail']==selected
        if pid in CEILINGS:
            assert any('At most USD 45,102.00' in x.value for x in app.markdown)
