"""All 83 programs enter actual shared recommendation tools and validated output."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
import subprocess
import sys
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from gradmatch import admission_history
from gradmatch.agent import Execution, Task
from gradmatch.broad_catalog import build_broad_catalog, screen_program, finish_broad_result
from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import load_seed
from gradmatch.config import load_settings
from gradmatch.constraints import check_constraints
from gradmatch.providers import ModelUnavailable, OpenAIProvider
from gradmatch.ranking import RankingDraft, PreliminaryRecommendationDraft
from gradmatch.schemas import Intake
from gradmatch.service import export_session, start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import data_hash, validate_shortlist
from scripts.m5_fixtures import FixtureProvider

AS_OF=date(2026,11,21)
STANFORD='community-sss-stanford-mscs'


class BroadFixture(FixtureProvider):
    def generate(self,kind,purpose,payload,session):
        value=super().generate(kind,purpose,payload,session)
        if purpose=='rank' and payload.get('recommendation_scope')=='broad':
            ids=[pid for pid in payload['allowed_preliminary_program_ids'] if pid.startswith('community-')]
            ids.sort(key=lambda pid:(pid!=STANFORD,pid))
            value.suggestions=[PreliminaryRecommendationDraft(program_id=pid,reason_check_ids=['english','deadline','gre']) for pid in ids[:8]]
        return value


def run(session=None,strategy='react',provider=None,**kwargs):
    p,s=load_seed()
    return start_task(session or Session(profile=tiering_profile()),request_id=str(uuid4()),programs=p,sources=s,
        settings=replace(load_settings(),enabled=False,api_key=''),as_of=AS_OF,
        strategy=strategy,provider=provider,recommendation_scope='broad',**kwargs)


def screen(pid=STANFORD,profile=None,as_of=AS_OF,mutate=None):
    p,s=load_seed();pool,context=build_broad_catalog(p,s)
    profile=profile or tiering_profile()
    program=next(p for p in pool if p.program_id==pid)
    if mutate:mutate(context['entries'][pid]['facts'])
    report=check_constraints(profile,program,s,as_of=as_of)
    value=screen_program(profile,program,report,context,as_of=as_of)
    return value,{c['rule_id']:c for c in value['checks']}


def test_pool_has_83_exact_ids_without_changing_official_facts_or_registering_community_as_official():
    p,s=load_seed();before=data_hash(p,s);pool,ctx=build_broad_catalog(p,s)
    assert len(pool)==len({p.program_id for p in pool})==83
    assert sum(p.program_id.startswith('community-') for p in pool)==63
    assert {item.program_id:item for item in pool if not item.program_id.startswith('community-')}=={item.program_id:item for item in p}
    assert data_hash(p,s)==before
    assert all(not p.allowed_official_hosts and not p.field_sources for p in pool if p.program_id.startswith('community-'))
    assert ctx['snapshot_date']=='2026-10-25'
    assert len(ctx['data_hash'])==64


@pytest.mark.parametrize('strategy',['fixed','react','plan'])
def test_every_strategy_searches_checks_and_ranks_all_83_with_real_community_fields(strategy):
    provider=BroadFixture();session=Session(profile=tiering_profile())
    result=run(session,strategy,provider)
    assert result['catalog_program_count']==83 and len(result['retrieved_program_ids'])==83
    assert result['validation_passed'] and result['preliminary_recommendations']
    assert len(result['community_data_hash'])==len(result['recommendation_data_hash'])==64
    assert result['model_status']=='test_stub'
    assert STANFORD in {r['program_id'] for r in result['preliminary_recommendations']}
    payload=next(payload for purpose,payload in provider.calls if purpose=='rank')
    assert payload['recommendation_catalog_count']==83
    assert any(p['program_id']==STANFORD for p in payload['programs'])
    report=next(r for r in payload['preliminary_reports'] if r['program_id']==STANFORD)
    assert report['next_listed_round']['date']=='2026-12-08'
    assert any(r['test']=='toefl_120' and '90' in r['summary'] for r in report['reported_language'])
    assert all(r['personalized_tier'] is None for r in result['preliminary_recommendations'])
    assert export_session(session)['result']['recommendation_scope']=='broad'
    if strategy == "react":
        first_purpose, first_payload = provider.calls[0]
        assert first_purpose == "act"
        assert set(first_payload["retrieved_program_ids"]) == set(result["retrieved_program_ids"])
        first_tool = result["task_usage"]["tool_log"][0]
        assert first_tool["tool"] == "search_programs"
        assert first_tool["result"]["usage"]["model_calls"] == 0
    if strategy=='plan':assert session.agent_task.plan_state.revisions[-1]['status']=='completed'


def test_explicit_search_finds_a_program_outside_the_old_top_ten():
    p,s=load_seed();pool,ctx=build_broad_catalog(p,s)
    t=Task('react','snapshot',pool,s,json.loads((PROJECT_ROOT/'config/agent.json').read_text()),broad_context=ctx)
    driver=Execution(t,Session(profile=tiering_profile()),replace(load_settings(),enabled=False),AS_OF)
    r=driver.dispatch('search_programs',{'program_ids':[STANFORD],'limit':1})
    assert r['ok'] and r['data']['programs'][0]['program_id']==STANFORD
    assert r['data']['programs'][0]['community_application_details']['reported_rounds'][0]['date']=='2026-12-08'


@pytest.mark.parametrize("strategy", ["react", "plan"])
def test_general_assessment_checks_and_ranks_full_pool_despite_model_filters(strategy):
    class NarrowingFixture(BroadFixture):
        def generate(self, kind, purpose, payload, session):
            value = super().generate(kind, purpose, payload, session)
            if purpose == "act":
                if value.tool in {"check_constraints", "rank_programs"}:
                    args = json.loads(value.arguments_json)
                    args["program_ids"] = [STANFORD]
                    return value.model_copy(update={"arguments_json": json.dumps(args)})
            if purpose == "plan":
                for step in value.steps:
                    if step.tool in {"search_programs", "check_constraints", "rank_programs"}:
                        step.program_ids = [STANFORD]
            return value

    provider, session = NarrowingFixture(), Session(profile=tiering_profile())
    first = run(session, strategy, provider)
    updated = run(session, strategy, provider, message="Change my tuition budget to 50000.")
    assert first["task_id"] == updated["task_id"]
    for result in (first, updated):
        assert result["validation_passed"] and result["all_catalog_retrieved"]
        current = [event for event in result["task_usage"]["tool_log"]
                   if event["tool"] == "check_constraints" and event["profile_version"] == result["profile_version"]]
        assert set(result["retrieved_program_ids"]) == {
            report["program_id"] for report in current[-1]["result"]["data"]["reports"]
        }
        assert len(result["retrieved_program_ids"]) == 83
    assert all(payload["all_catalog_retrieved"] for purpose, payload in provider.calls if purpose == "rank")
    assert any(item["program_id"] == "cmu-msaii-pittsburgh" for item in updated["excluded"])


def test_score_concerns_block_preliminary_recommendations_without_turning_community_into_verified_rules():
    profile=tiering_profile();profile.english.total=80
    r,c=screen(profile=profile)
    assert c['english']['status']=='fail' and not r['eligible_for_preliminary']
    profile.english.total=110
    r,c=screen(profile=profile)
    assert c['english']['status']=='reported_floor_met' and c['english']['basis']=='community_reported'
    assert c['tuition']['status']=='unknown'


def test_recommended_scores_and_other_intakes_do_not_become_hard_minimum_passes():
    r,c=screen(mutate=lambda f:f['language'][0].update(kind='recommended',reported_total=None,summary='Recommended: 115'))
    assert c['english']['status']=='unknown' and r['eligible_for_preliminary']
    profile=tiering_profile();profile.intake=Intake(year=2028,term='fall')
    _,c=screen(profile=profile)
    assert c['english']['status']==c['deadline']['status']=='unknown'


@pytest.mark.parametrize('as_of,status',[(date(2026,12,7),'reported_date_available'),(date(2026,12,8),'unknown'),(date(2026,12,9),'fail')])
def test_reported_only_deadline_has_date_boundaries_and_keeps_cutoff_time_unknown(as_of,status):
    _,checks=screen(as_of=as_of)
    assert checks['deadline']['status']==status


def test_past_priority_or_scholarship_round_does_not_close_admission():
    for label in ['Priority deadline','Scholarship consideration deadline']:
        _,checks=screen(mutate=lambda f:f.update(rounds=[{'date':'2026-11-01','label':label}]))
        assert checks['deadline']['status']=='unknown'


def test_applicable_official_checks_override_a_conflicting_reported_score():
    pid='cmu-msaii-pittsburgh'
    _,checks=screen(pid=pid,mutate=lambda f:f['language'][0].update(reported_total='120'))
    assert checks['english']['basis']=='reviewed_official' and checks['english']['status']=='pass'


def test_blocked_halt_and_doctoral_routes_are_not_suggested():
    for pid in ['community-sss-mit-cse','community-sss-mit-eecs']:
        r,c=screen(pid=pid)
        assert not r['eligible_for_preliminary'] and c['availability']['status']=='fail'


@pytest.mark.parametrize('attack',['invented','unretrieved','blocked','duplicate','failed_reason'])
def test_validator_rejects_unsupported_preliminary_choices(attack):
    p,s=load_seed();pool,ctx=build_broad_catalog(p,s);profile=tiering_profile()
    selected=[next(p for p in pool if p.program_id==STANFORD)]
    base=validate_shortlist(None,profile,pool,selected,s,as_of=AS_OF)
    screens={p.program_id:screen_program(profile,p,check_constraints(profile,p,s,as_of=AS_OF),ctx,as_of=AS_OF) for p in selected}
    pid='invented' if attack=='invented' else 'community-sss-mit-eecs' if attack=='unretrieved' else STANFORD
    if attack=='blocked':screens[STANFORD]['eligible_for_preliminary']=False
    if attack=='failed_reason':screens[STANFORD]['checks'][2]['status']='fail'
    suggestion=dict(program_id=pid,reason_check_ids=['english'])
    draft=RankingDraft(profile_version=profile.profile_version,status='insufficient_evidence',recommendations=[],pending_order=[],observations=[],suggestions=[suggestion]*(2 if attack=='duplicate' else 1))
    result=finish_broad_result(base,draft,profile,pool,selected,ctx,screens)
    assert not result['validation_passed']


def test_budget_followup_rechecks_the_broad_pool_and_preserves_other_profile_fields():
    session=Session(profile=tiering_profile());initial=run(session)
    assert any(r['program_id']=='cmu-msaii-pittsburgh' for r in initial['preliminary_recommendations'])
    gpa=session.profile.gpa.model_dump();second=run(session,message='Change my tuition budget to 50000')
    assert second['catalog_program_count']==83 and second['profile_version']>initial['profile_version']
    assert all(r['program_id']!='cmu-msaii-pittsburgh' for r in second['preliminary_recommendations'])
    assert session.profile.gpa.model_dump()==gpa and not session.usage


def test_plan_and_rank_inputs_stay_compact_after_full_pool_checks():
    provider = BroadFixture()
    session = Session(profile=tiering_profile())
    first = run(session, strategy='plan', provider=provider)
    second = run(session, strategy='plan', provider=provider, message='Change my tuition budget to 50000')
    assert first['validation_passed'] and second['validation_passed']
    assert [purpose for purpose, _ in provider.calls] == ['plan', 'rank', 'plan', 'rank']
    for purpose, payload in provider.calls:
        # The provider wraps the serialized applicant input in a JSON request body.
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if purpose == 'plan':
            assert len(encoded) < 32_000
            assert len(payload['catalog_index']) == 83
        else:
            assert len(encoded) < 95_000
            stanford = next(row for row in payload['preliminary_reports'] if row['program_id'] == STANFORD)
            assert stanford['next_listed_round']['date'] == '2026-12-08'
            assert stanford['reported_language'] and stanford['reported_gre']
    full_log = second['task_usage']['tool_log']
    assert any(entry['tool'] == 'check_constraints' and len(entry['result']['data']['reports']) == 83
               for entry in full_log)


def test_valid_formal_recommendation_takes_precedence_over_its_preliminary_duplicate():
    class CrossListedFixture(BroadFixture):
        def generate(self, kind, purpose, payload, session):
            draft = super().generate(kind, purpose, payload, session)
            if purpose == 'rank':
                draft.suggestions = [*draft.suggestions[:2], PreliminaryRecommendationDraft(
                    program_id=draft.recommendations[0].program_id, reason_check_ids=['english'],
                )]
            return draft

    result = run(strategy='plan', provider=CrossListedFixture())
    assert result['validation_passed']
    assert [item['program_id'] for item in result['recommendations']] == ['cmu-msaii-pittsburgh']
    assert len(result['preliminary_recommendations']) == 2
    assert result['validation_warnings'] == [{
        'program_id': 'cmu-msaii-pittsburgh', 'code': 'PRELIMINARY_DUPLICATE_OF_FORMAL',
    }]


def test_reviewed_scope_remains_the_original_catalog_for_existing_benchmarks():
    p,s=load_seed()
    r=start_task(Session(profile=tiering_profile()),request_id=str(uuid4()),programs=p,sources=s,
        settings=replace(load_settings(),enabled=False),as_of=AS_OF,strategy='fixed',provider=FixtureProvider())
    assert r['catalog_program_count']==20 and 'preliminary_recommendations' not in r


def test_hot_upgrade_keeps_session_and_provider_classes_in_an_isolated_process():
    code="""
from dataclasses import asdict,replace
from datetime import date
from gradmatch.session import Session,tiering_profile
from gradmatch.providers import OpenAIProvider,INSTRUCTIONS
from gradmatch.catalog import load_seed
from gradmatch.config import load_settings
import gradmatch.service,gradmatch.agent,gradmatch.planning,gradmatch.release as release
session=Session(profile=tiering_profile());session.messages.append({'role':'user','content':'Preserve this fictional conversation'})
before=asdict(session);session_kind=type(session);provider_kind=OpenAIProvider
for name in release._ENGINE_MODULES:
    module=__import__(name,fromlist=[''])
    module.BROAD_ENGINE_VERSION=0
for purpose in ['rank','act','plan']:
    INSTRUCTIONS[purpose]=INSTRUCTIONS[purpose].split(' M6.3 BROAD CONTRACT:')[0]
release._signature=None
release.refresh_catalog_modules()
from gradmatch.providers import OpenAIProvider as after_provider
from gradmatch.service import start_task
assert type(session) is session_kind and asdict(session)==before and after_provider is provider_kind
assert INSTRUCTIONS['rank'].count('M6.3 BROAD CONTRACT:')==1
p,s=load_seed()
r=start_task(session,request_id='isolated-upgrade',programs=p,sources=s,settings=replace(load_settings(),enabled=False,api_key=''),as_of=date(2026,11,21),strategy='react',recommendation_scope='broad')
assert r['catalog_program_count']==83 and r['preliminary_recommendations'] and not session.usage
print('hot-upgrade passed')
"""
    result=subprocess.run([sys.executable,'-c',code],cwd=PROJECT_ROOT,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


def test_actual_generate_uses_all_83_by_default_and_renders_unreviewed_recommendations(tmp_path,monkeypatch):
    monkeypatch.setenv('GRADMATCH_DB_PATH',str(bootstrap_public_catalog(tmp_path/'public')))
    monkeypatch.setenv('GRADMATCH_PUBLIC_CACHE_DIR',str(tmp_path/'public'))
    monkeypatch.setenv('MODEL_ENABLED','false')
    def deny(*args,**kwargs):raise AssertionError('No paid call in page verification')
    monkeypatch.setattr(OpenAIProvider,'generate',deny)
    app=AppTest.from_file(str(PROJECT_ROOT/'app.py'),default_timeout=30).run()
    app.button(key='m35_load_example').click().run()
    app.button(key='m2_generate').click().run()
    assert not app.exception
    r=app.session_state['m2_session'].current_result
    assert r['recommendation_scope']=='broad' and r['catalog_program_count']==83
    assert any(x['program_id'].startswith('community-') for x in r['preliminary_recommendations'])
    assert any('Recommendation pool: 83 programs' in c.value for c in app.caption)
    assert not app.session_state['m2_session'].usage
    app.selectbox(key='m63_pool').set_value('Reviewed official records only').run()
    app.button(key='m2_generate').click().run()
    assert not app.exception and app.session_state['m2_session'].current_result['catalog_program_count']==20

    session = app.session_state["m2_session"]
    task = session.agent_task
    task.turns = task.limits["max_turns"]
    app.button(key="m2_generate").click().run()
    assert not app.exception and session.current_result["status"] == "budget_exhausted"
    assert any(item.value == "Partial assessment" for item in app.subheader)
    assert app.button(key="m2_retry").label == "Start new assessment with saved profile"
    app.button(key="m2_retry").click().run()
    assert not app.exception and session.agent_task.task_id != task.task_id
    assert session.profile.tuition_budget_usd == 140000 and not session.usage


@pytest.mark.parametrize("method,decision,restarts_task", [
    ("ReAct agent", "act", False),
    ("Plan-and-replan agent", "plan", True),
])
def test_saved_budget_can_be_retried_after_model_failure(tmp_path, monkeypatch, method, decision, restarts_task):
    monkeypatch.setenv("GRADMATCH_DB_PATH", str(bootstrap_public_catalog(tmp_path / "public")))
    monkeypatch.setenv("GRADMATCH_PUBLIC_CACHE_DIR", str(tmp_path / "public"))
    monkeypatch.setenv("MODEL_ENABLED", "true")
    monkeypatch.setenv("MODEL_API_KEY", "test-key")
    fixture = BroadFixture()
    failed = False

    def generate(_provider, kind, purpose, payload, session):
        nonlocal failed
        reply = fixture.generate(kind, purpose, payload, session)
        if purpose == decision and session.profile.tuition_budget_usd == 50000 and not failed:
            failed = True
            session.usage[-1]["status"] = "error"
            raise ModelUnavailable("Simulated model failure.")
        return reply

    monkeypatch.setattr(OpenAIProvider, "generate", generate)
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
    app.selectbox(key="m4_strategy").set_value(method).run()
    app.checkbox(key="m2_allow_model").check().run()
    app.button(key="m35_load_example").click().run()
    app.button(key="m2_generate").click().run()
    assert not app.exception
    session = app.session_state["m2_session"]
    original = session.current_result
    assert any(item["program_id"] == "cmu-msaii-pittsburgh" for item in original["recommendations"])

    app.chat_input(key="m2_chat").set_value("Change my tuition budget to 50000.").run()
    assert not app.exception and failed
    assert app.session_state["m2_last_response"]["status"] == "error"
    assert session.profile.tuition_budget_usd == 50000
    assert session.current_result is None and session.previous_result == original
    assert any("USD 50,000" in caption.value and "Saved profile" in caption.value for caption in app.caption)
    assert any("USD 140,000" in info.value and "Previous assessment" in info.value for info in app.info)
    task_id = session.agent_task.task_id
    usage_before_retry = list(session.usage)
    user_messages = [message for message in session.messages if message["role"] == "user"]
    app.run()
    assert session.usage == usage_before_retry
    expected_label = "Start new assessment with saved profile" if restarts_task else "Retry with saved profile"
    assert app.button(key="m2_retry").label == expected_label

    app.button(key="m2_retry").click().run()
    assert not app.exception
    assert (session.agent_task.task_id != task_id) is restarts_task
    assert session.usage[:len(usage_before_retry)] == usage_before_retry
    assert [message for message in session.messages if message["role"] == "user"] == user_messages
    assert session.current_result["validation_passed"]
    exclusions = {item["program_id"]: item["reason_codes"] for item in session.current_result["excluded"]}
    assert "TUITION_EXCEEDS_BUDGET" in exclusions["cmu-msaii-pittsburgh"]
    assert any("USD 140,000 → USD 50,000" in item.value for item in app.markdown)
    assert any("Removed with a tuition budget failure" in item.value and "MSAII" in item.value for item in app.markdown)
    counts = {metric.label: int(metric.value) for metric in app.metric}
    assert counts["Fails budget check"] >= 1 and counts["Budget fit unverified"] >= 1
    assert not any(button.key == "m2_retry" for button in app.button)


def test_cloud_profile_uses_bundled_dp_and_assigns_every_recommendation_a_tier(tmp_path, monkeypatch):
    public = tmp_path / "public"
    monkeypatch.setenv("GRADMATCH_DB_PATH", str(bootstrap_public_catalog(public)))
    monkeypatch.setenv("GRADMATCH_PUBLIC_CACHE_DIR", str(public))
    monkeypatch.setenv("MODEL_ENABLED", "false")
    monkeypatch.setattr(admission_history, "PREVIEW_FILE", tmp_path / "local-preview-not-present.json")

    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
    app.button(key="m35_load_example").click().run()
    app.number_input(key="m2_input_gpa").set_value(3.80)
    app.button(key="m2_save_profile").click().run()
    assert not app.exception
    session = app.session_state["m2_session"]
    result = session.current_result
    assert len(result["retrieved_program_ids"]) == 83
    suggestions = result["preliminary_recommendations"]
    assert suggestions and all(item["planning_tier"]["label"] in admission_history.PLANNING_TIERS for item in suggestions)
    assert any(item["planning_tier"]["label"] == "Target" for item in suggestions)
    assert any("Matched historical reports" in line.value for line in app.markdown)
    assert not session.usage

    app.chat_input(key="m2_chat").set_value("Change my tuition budget to 50000.").run()
    assert not app.exception
    rows = session.current_result["preliminary_recommendations"]
    assert all(item["program_id"] not in {"nyu-mscs-tandon-brooklyn", "usc-mscs-general-los-angeles"} for item in rows)
    assert all(item["planning_tier"]["label"] in admission_history.PLANNING_TIERS for item in rows)


def test_planning_tier_requires_stronger_evidence_and_verified_checks_for_safer():
    assert admission_history.planning_tier(None, hard_checks_passed=True)["label"] == "Reach"
    history = {"admitted": 10, "rejected": 2}
    assert admission_history.planning_tier(history, hard_checks_passed=False)["label"] == "Target"
    assert admission_history.planning_tier(history, hard_checks_passed=True)["label"] == "Safer"
