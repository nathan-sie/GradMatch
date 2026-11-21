"""M3.5: real evidence bindings, transparent tiers and profile-update boundaries."""
from datetime import date
from decimal import Decimal
import json
import pytest
from streamlit.testing.v1 import AppTest
from gradmatch.catalog import load_seed as current_load_seed, import_catalog, M1_SEED, M35_SEED
from gradmatch.constraints import check_constraints, evidence_ids
from gradmatch.schemas import AdmissionEvidence, ApplicantProfile
from gradmatch.session import Session, tiering_profile
from gradmatch.ranking import RankingDraft
from gradmatch.service import start_task
from gradmatch.config import load_settings
from gradmatch.tiers import selectivity_tier
from gradmatch.validation import validate_shortlist
from gradmatch.storage import PROJECT_ROOT
from dataclasses import replace

AS_OF=date(2026,11,16)

def load_seed(path=M35_SEED):
    return current_load_seed(path)

def draft(profile, programs):
    return RankingDraft(profile_version=profile.profile_version,status="insufficient_evidence",recommendations=[{
        "program_id":p.program_id,"tier":selectivity_tier(p.admission_evidence[0]),
        "goal_feature_ids":[p.goal_features[0].feature_id],"tier_evidence_ids":[p.admission_evidence[0].evidence_id],
        "comparison_dimensions":["selectivity"],"lower_risk_rationale":None,
        "limitations":["Cohort evidence is not a personal probability; minimum requirements do not establish competitiveness."]}
        for p in programs if p.program_id=="cmu-msaii-pittsburgh"],pending_order=[],observations=[])

def validated(profile=None):
    programs,sources=load_seed()
    profile=profile or tiering_profile()
    return validate_shortlist(draft(profile,programs),profile,programs,programs,sources,as_of=AS_OF)

def test_pilot_real_evidence_authorizes_only_msaii_not_incomplete_mcds():
    result=validated()
    assert [x["program_id"] for x in result["recommendations"]]==["cmu-msaii-pittsburgh"]
    item=result["recommendations"][0]
    assert item["tier"]=="Lottery" and "58 offers from 526" in item["planning_reason"]
    assert "not your admission probability" in item["planning_reason"]
    assert item["checks"]["tuition"]["upper_usd"]=="137400"
    assert any(x["program_id"]=="cmu-mcds-pittsburgh" for x in result["pending_verification"])
    assert not any(x["tier"] in {"Target","Safer"} for x in result["recommendations"])

@pytest.mark.parametrize("offers,expected",[(0,"Lottery"),(15,"Lottery"),(16,"Reach"),(35,"Reach"),(36,None)])
def test_exact_planning_thresholds(offers,expected):
    e=AdmissionEvidence(evidence_id="synthetic",kind="program_selectivity",source_ids=[],cycle_year=2025,
        independence_key="test",permitted_tiers=[],statement="Synthetic test",reviewed=True,applications=100,offers=offers)
    assert selectivity_tier(e)==expected

@pytest.mark.parametrize("budget,expected",[("137400","pass"),("137399.99","fail"),("100000","fail")])
def test_required_summer_tuition_is_in_budget_upper_bound(budget,expected):
    programs,sources=load_seed(); p=next(x for x in programs if x.degree=="MSAII")
    profile=tiering_profile(); profile.tuition_budget_usd=Decimal(budget)
    report=check_constraints(profile,p,sources,as_of=AS_OF)
    assert report.tuition.lower_usd==133500 and report.tuition.upper_usd==137400
    assert next(c for c in report.checks if c.rule_id=="tuition").status==expected

@pytest.mark.parametrize("mutation",["degree_unknown","degree_late","gre_missing","gre_old","gre_future","gre_home","courses_missing","cohort_old","fake_counts","wrong_tier"])
def test_unknown_ineligible_or_unsupported_claims_cannot_enter_formal_tiers(mutation):
    programs,sources=load_seed(); profile=tiering_profile(); p=next(x for x in programs if x.degree=="MSAII")
    d=draft(profile,programs)
    if mutation=="degree_unknown":profile.degree=None
    if mutation=="degree_late":profile.degree.completion="not_before_enrollment"
    if mutation=="gre_missing":profile.gre=None
    if mutation=="gre_old":profile.gre.test_date=date(2020,1,1)
    if mutation=="gre_future":profile.gre.test_date=date(2027,1,1)
    if mutation=="gre_home":profile.gre.format="at_home"
    if mutation=="courses_missing":profile.coursework={}
    if mutation=="cohort_old":p.admission_evidence[0].cycle_year=2000
    if mutation=="fake_counts":p.admission_evidence[0].offers=400
    if mutation=="wrong_tier":d.recommendations[0].tier="Target"
    result=validate_shortlist(d,profile,programs,programs,sources,as_of=AS_OF)
    assert not result["recommendations"] and result["validation_errors"]

def test_intake_cutoffs_and_us_degree_exception_do_not_become_waivers():
    programs,sources=load_seed(); p=next(x for x in programs if x.degree=="MSAII")
    profile=tiering_profile(); profile.english.test_date=date(2022,9,1)
    def code():return next(c.reason_code for c in check_constraints(profile,p,sources,as_of=AS_OF).checks if c.rule_id=="english")
    assert code()=="ENGLISH_MEETS_MINIMUM"
    profile.degree.country="CN"
    assert code()=="ENGLISH_BEFORE_INTAKE_CUTOFF"
    profile.english.test_date=date(2024,9,1)
    assert code()=="ENGLISH_MEETS_MINIMUM"
    profile.english.test_date=None
    assert code()=="MISSING_ENGLISH_TEST_DATE"

def test_historic_snapshots_use_conservative_defaults_but_not_unbound_new_values():
    programs,sources=load_seed(M1_SEED); p=programs[0]; profile=tiering_profile()
    assert evidence_ids(p,"english",sources,profile)
    p.english[0].minimum_test_date=date(2025,1,1)
    assert not evidence_ids(p,"english",sources,profile)

def test_form_preserves_new_fields_exact_budget_and_english_ui(tmp_path,monkeypatch):
    database=tmp_path/'catalog.db'; import_catalog(database=database)
    monkeypatch.setenv('GRADMATCH_DB_PATH',str(database)); monkeypatch.setenv('MODEL_ENABLED','false')
    app=AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=20).run()
    app.button(key='m35_load_example').click().run()
    before=app.session_state['m2_session'].profile.model_dump(mode='json')
    app.text_input(key='m2_input_budget').set_value('100000.25')
    app.button(key='m2_save_profile').click().run()
    assert not app.exception
    after=app.session_state['m2_session'].profile.model_dump(mode='json')
    assert ApplicantProfile.model_validate(after)==ApplicantProfile.model_validate({**before,'tuition_budget_usd':'100000.25','profile_version':before['profile_version']+1})
    assert not app.session_state['m2_session'].usage

def test_full_service_recomputes_budget_without_changing_background():
    programs,sources=load_seed(); session=Session(profile=tiering_profile())
    class Stub:
        def generate(self,kind,purpose,payload,session):
            assert payload['allowed_recommendation_program_ids']==(['cmu-msaii-pittsburgh'] if session.profile.tuition_budget_usd==140000 else [])
            return draft(session.profile,[p for p in programs if p.program_id in {r['program_id'] for r in payload['reports'] if r['recommendation_ready']}])
    settings=replace(load_settings(),enabled=False,api_key='')
    first=start_task(session,request_id='first',programs=programs,sources=sources,settings=settings,as_of=AS_OF,provider=Stub())
    before=session.profile.model_dump(mode='json')
    second=start_task(session,request_id='budget',message='Change my tuition budget to 100000',programs=programs,sources=sources,settings=settings,as_of=AS_OF,provider=Stub())
    assert first['recommendations'] and not second['recommendations']
    assert session.profile.model_dump(mode='json')=={**before,'tuition_budget_usd':'100000','profile_version':2}
    removed=next(x for x in second['changes_from_previous']['removed'] if x['program_id']=='cmu-msaii-pittsburgh')
    assert any('budget' in r for r in removed['reasons'])


def test_reloading_same_example_discards_unsaved_form_edits_and_preserves_model_opt_in(tmp_path,monkeypatch):
    database=tmp_path/'catalog.db'; import_catalog(database=database)
    monkeypatch.setenv('GRADMATCH_DB_PATH',str(database))
    monkeypatch.setenv('MODEL_ENABLED','true')
    monkeypatch.setenv('OPENAI_API_KEY','SYNTHETIC-TEST-ONLY')
    app=AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=20).run()
    app.checkbox(key='m2_allow_model').check().run()
    app.button(key='m35_load_example').click().run()
    expected=app.session_state['m2_session'].profile.model_copy(deep=True)
    app.number_input(key='m2_input_gpa').set_value(2.0)
    app.text_input(key='m2_input_budget').set_value('1')
    app.button(key='m35_load_example').click().run()
    assert not app.exception
    assert app.number_input(key='m2_input_gpa').value==3.5
    assert app.text_input(key='m2_input_budget').value=='140000'
    assert app.number_input(key='m2_input_english_total').value==110
    assert app.number_input(key='m2_input_gre_quantitative').value==165
    assert app.checkbox(key='m2_allow_model').value is True
    assert app.session_state['m2_session'].profile==expected
    app.checkbox(key='m2_allow_model').uncheck().run()
    app.button(key='m2_save_profile').click().run()
    saved=app.session_state['m2_session'].profile
    assert saved.model_dump(exclude={'profile_version'})==expected.model_dump(exclude={'profile_version'})
    assert not app.session_state['m2_session'].usage
