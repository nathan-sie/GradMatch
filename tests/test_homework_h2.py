"""H2 trajectory/state/budget regressions. Scripted answers are never scores."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from types import SimpleNamespace as NS
import pytest
from gradmatch.homework.dataset import load_candidate_inputs
from gradmatch.homework.engine import CandidateRun
from gradmatch.homework.models import AnswerDraft, Decision, ToolCall
from gradmatch.homework.provider import HomeworkProvider
from gradmatch.homework.runtime import load_runtime
from gradmatch.session import ProfilePatch, PatchOperation
from gradmatch.storage import PROJECT_ROOT


@pytest.fixture
def runtime():return load_runtime()


def candidate(runtime,id='d01'):
    return next(c for c in load_candidate_inputs(PROJECT_ROOT/'homework/dev_tasks.jsonl',date.fromisoformat(runtime.manifest['assessment_date'])) if c.task_id==id)


def answer(text='Snapshot evidence is incomplete.',citations=None,recommendations=None):
    return Decision(answer=AnswerDraft(answer=text,citations=citations or [],recommendations=recommendations or [],needs_clarification=False))


def call(name,**args):return Decision(calls=[ToolCall('call-'+str(call.counter()),name,json.dumps(args))])
call.counter=iter(range(10000)).__next__


class Scripted:
    is_live=False
    def __init__(self,*steps):self.steps,self.inputs=list(steps),[]
    def invoke(self,purpose,payload,history,timeout):
        self.inputs.append(deepcopy((purpose,payload,history,timeout)))
        step=self.steps.pop(0)
        value=step(purpose,payload,history) if callable(step) else step
        return value,{'actual_request':False,'status':'test_double','input_tokens':None,'output_tokens':None,
            'estimated_cost_usd':None,'model':'offline-scripted'}


def test_observation_changes_next_action_and_every_span_is_closed(runtime):
    pid=candidate(runtime).program_ids[0]
    def recover(purpose,payload,history):
        assert json.loads(history[-1]['output'])['error']['code']=='not_found'
        return call('get_program',program_id=pid)
    provider=Scripted(call('get_evidence',source_id='missing'),recover,answer())
    run=CandidateRun(runtime,candidate(runtime),'react',provider=provider).run()
    tools=[s for s in run['trace']['spans'] if s['kind']=='tool']
    assert run['status']=='completed' and run['model_calls']==3 and run['actual_requests']==0
    assert [s['name'] for s in tools]==['get_evidence','get_program']
    model_ids={s['span_id'] for s in run['trace']['spans'] if s['kind']=='model'}
    assert all(s['parent_id'] in model_ids and s['selected_by']=='model' for s in tools)
    assert all(s['finished_at'] and s['duration_ms']>=0 and s['status']!='running' for s in run['trace']['spans'])


@pytest.mark.parametrize('name,args,code',[
    ('get_program',{'program_id':'missing'},'not_found'),
    ('get_program',{'program_id':'x','path':'secret'},'invalid_arguments'),
    ('check_program',{'program_id':'uw-ece-msece-pmp-seattle','profile_version':2},'stale_profile'),
    ('check_program',{'program_id':'uw-ece-msece-pmp-seattle','profile_version':True},'invalid_arguments'),
    ('delete_database',{},'unknown_tool'),
])
def test_errors_are_recoverable_observations(runtime,name,args,code):
    from gradmatch.homework.tools import SnapshotTools
    tools=SnapshotTools(runtime.programs,runtime.sources,date(2026,11,16))
    assert tools.dispatch(name,args,candidate(runtime).profile)['error']['code']==code


def test_source_paths_and_hashes_are_enforced(runtime):
    from gradmatch.homework.tools import SnapshotTools
    tools=SnapshotTools(runtime.programs,runtime.sources,date(2026,11,16))
    sid=next(iter(tools.sources))
    assert tools.dispatch('get_evidence',{'source_id':sid},candidate(runtime).profile)['ok']
    tools.sources[sid].content_hash='0'*64
    assert tools.dispatch('get_evidence',{'source_id':sid},candidate(runtime).profile)['error']['code']=='snapshot_hash_mismatch'
    tools.sources[sid].snapshot_path='../.env'
    assert tools.dispatch('get_evidence',{'source_id':sid},candidate(runtime).profile)['error']['code']=='invalid_snapshot_path'


def test_repeated_actions_hit_cache_then_stop(runtime):
    pid=candidate(runtime).program_ids[0]
    provider=Scripted(*(call('get_program',program_id=pid) for _ in range(3)))
    run=CandidateRun(runtime,candidate(runtime),'react',provider=provider).run()
    spans=[s for s in run['trace']['spans'] if s['kind']=='tool']
    assert run['status']=='repeated_action' and run['tool_calls']==3
    assert [s.get('cache_hit') for s in spans]==[False,True,None]


@pytest.mark.parametrize('limit,status', [('max_model_calls_per_task','model_call_limit'),('max_tool_calls_per_task','tool_call_limit')])
def test_call_budgets_stop_without_another_attempt(runtime,limit,status):
    runtime.manifest=deepcopy(runtime.manifest)
    runtime.manifest['candidate_limits'][limit]=1
    c=candidate(runtime)
    provider=Scripted(call('get_program',program_id=c.program_ids[0]),call('search_programs',university=None,campus=None,discipline=None))
    run=CandidateRun(runtime,c,'react',provider=provider).run()
    assert run['status']==status and run['model_calls']<3 and run['tool_calls']==1


def test_total_time_limit_stops_and_keeps_usage(runtime):
    now=[0.0]
    def slow(*args):now[0]=121;return answer()
    provider=Scripted(slow)
    run=CandidateRun(runtime,candidate(runtime),'react',provider=provider,clock=lambda:now[0]).run()
    assert run['status']=='time_limit' and run['model_calls']==1 and len(run['usage'])==1


def test_budget_update_invalidates_cache_and_other_fields_survive(runtime):
    c=candidate(runtime)
    c.setup_messages=['Remember my current profile.']
    c.question='Change my budget to USD 100000.'
    run=CandidateRun(runtime,c,'fixed',provider=Scripted(answer(),answer())).run()
    before=deepcopy(run['profile_before']);after=deepcopy(run['profile_after'])
    assert run['status']=='completed' and after.pop('tuition_budget_usd')=='100000'
    before.pop('tuition_budget_usd');assert after.pop('profile_version')==2;before.pop('profile_version')
    assert before==after
    checks=[s for s in run['trace']['spans'] if s['name']=='check_program']
    assert [s['inputs']['arguments']['profile_version'] for s in checks]==[1,2]
    assert all(s['cache_hit'] is False for s in checks)


def test_interpreted_goal_update_and_repeat_isolation(runtime):
    c=candidate(runtime,'d07')
    patch=ProfilePatch(intent='update_profile',operations=[PatchOperation(field='goal',value_json='"mixed"',explicit_span='Change only my goal to mixed')],referenced_program_ids=[],ambiguous_fields=[])
    run=CandidateRun(runtime,c,'fixed',provider=Scripted(answer(),patch,answer())).run()
    assert run['status']=='completed' and run['model_calls']==3
    before=deepcopy(run['profile_before']);after=deepcopy(run['profile_after'])
    assert after.pop('goal')=='mixed';before.pop('goal');after.pop('profile_version');before.pop('profile_version')
    assert after==before and c.profile.goal=='employment'
    fresh=CandidateRun(runtime,c,'react',provider=Scripted(answer(),patch,answer())).run()
    assert run['trace_id']!=fresh['trace_id'] and fresh['profile_before']['profile_version']==1


def test_ambiguous_budget_does_not_guess_or_call_model(runtime):
    c=candidate(runtime);c.question='My total budget is USD 100000 including living expenses. Reassess.'
    run=CandidateRun(runtime,c,'react',provider=Scripted()).run()
    assert run['status']=='completed' and run['answer']['needs_clarification'] and run['model_calls']==0
    assert run['profile_after']==run['profile_before']


def test_living_cost_question_is_answered_and_explicit_tuition_update_is_not_ambiguous(runtime):
    c=candidate(runtime);c.question='Does a tuition-only budget exclude living costs?'
    run=CandidateRun(runtime,c,'react',provider=Scripted(answer('Yes, tuition-only excludes living costs.'))).run()
    assert run['model_calls']==1 and not run['answer']['needs_clarification']
    c.question='Set my tuition budget to USD 100000, excluding living costs.'
    patch=ProfilePatch(intent='update_profile',operations=[PatchOperation(field='tuition_budget_usd',value_json='"100000"',explicit_span=c.question)],referenced_program_ids=[],ambiguous_fields=[])
    run=CandidateRun(runtime,c,'react',provider=Scripted(patch,answer())).run()
    assert run['status']=='completed' and run['profile_after']['tuition_budget_usd']=='100000'


def test_unsupported_atomic_patch_changes_nothing(runtime):
    c=candidate(runtime);c.question='Change only my goal to mixed.'
    patch=ProfilePatch(intent='update_profile',operations=[PatchOperation(field='goal',value_json='"mixed"',explicit_span=c.question),
        PatchOperation(field='tuition_budget_usd',value_json='"1"',explicit_span=c.question)],referenced_program_ids=[],ambiguous_fields=[])
    run=CandidateRun(runtime,c,'react',provider=Scripted(patch)).run()
    assert run['answer']['needs_clarification'] and run['profile_after']==run['profile_before']


def test_fixed_pipeline_logs_real_operations_and_one_answer(runtime):
    run=CandidateRun(runtime,candidate(runtime),'fixed',provider=Scripted(answer())).run()
    spans=[s for s in run['trace']['spans'] if s['kind']=='tool']
    assert [s['name'] for s in spans]==['search_programs','get_program','check_program']
    assert all(s['selected_by']=='fixed_pipeline' for s in spans) and run['model_calls']==1


def test_unobserved_citations_and_unsupported_recommendations_are_blocked(runtime):
    sid=next(iter(runtime.sources))
    run=CandidateRun(runtime,candidate(runtime),'react',provider=Scripted(answer(citations=[sid]))).run()
    assert run['status']=='validation_failed' and run['answer'] is None
    from gradmatch.ranking import RecommendationDraft
    rec=RecommendationDraft(program_id=candidate(runtime).program_ids[0],tier='Safer',goal_feature_ids=[],tier_evidence_ids=[],
        comparison_dimensions=[],lower_risk_rationale=None,limitations=[])
    run=CandidateRun(runtime,candidate(runtime),'fixed',provider=Scripted(answer(recommendations=[rec]))).run()
    assert run['status']=='validation_failed' and run['answer'] is None


def test_candidate_modules_never_read_grading_records(runtime):
    for name in ['engine','runtime','provider','tools','prompts']:
        text=(PROJECT_ROOT/f'gradmatch/homework/{name}.py').read_text(encoding='utf-8')
        assert 'homework.dataset' not in text and 'homework.validation' not in text and 'references.jsonl' not in text
    provider=Scripted(answer())
    CandidateRun(runtime,candidate(runtime),'react',provider=provider).run()
    payload=provider.inputs[0][1]
    assert not {'expected','expected_call','rubric','tags','family','task_id'} & set(payload)


def test_disabled_default_has_no_api_request(runtime):
    run=CandidateRun(runtime,candidate(runtime),'react').run()
    assert run['status']=='model_disabled' and run['actual_requests']==0 and run['model_calls']==0


def test_native_sdk_request_and_actual_usage_are_recorded(runtime):
    captured={}
    response=NS(model=runtime.settings.model,id='response-test',status='completed',output_text='',
        output=[NS(type='function_call',call_id='call-1',name='get_program',arguments='{"program_id":"rice-mcs-houston"}')],
        usage=NS(input_tokens=100,output_tokens=10,input_tokens_details=NS(cached_tokens=20),output_tokens_details=NS(reasoning_tokens=2)))
    def create(**kwargs):captured.update(kwargs);return response
    settings=replace(runtime.settings,enabled=True,api_key='private-test-key')
    provider=HomeworkProvider(settings,client=NS(responses=NS(create=create)))
    decision,usage=provider.invoke('react',{'question':'Read the program.'},[],12)
    assert decision.calls[0].name=='get_program' and usage['actual_request'] and usage['input_tokens']==100
    assert usage['cached_input_tokens']==20 and usage['estimated_cost_usd'] is not None
    assert captured['store'] is False and captured['parallel_tool_calls'] is False and captured['timeout']==12
    assert set(t['name'] for t in captured['tools'])=={'search_programs','get_program','get_evidence','check_program'}
    assert 'private-test-key' not in json.dumps(captured) and 'previous_response_id' not in captured


def test_failed_provider_usage_is_retained_without_secret_exception_text(runtime):
    from openai import APIConnectionError
    import httpx
    def fail(**kwargs):raise APIConnectionError(message='private-test-key',request=httpx.Request('POST','https://api.openai.com/v1/responses'))
    runtime.settings=replace(runtime.settings,enabled=True,api_key='private-test-key')
    provider=HomeworkProvider(runtime.settings,client=NS(responses=NS(create=fail)))
    run=CandidateRun(runtime,candidate(runtime),'react',provider=provider).run()
    assert run['status']=='connection_or_timeout' and run['actual_requests']==1
    assert run['usage_complete'] is False and run['estimated_cost_usd'] is None
    assert 'private-test-key' not in json.dumps(run)


def test_verified_planning_recommendation_still_passes_shared_validator(runtime):
    from gradmatch.ranking import RecommendationDraft
    c=candidate(runtime,'d07');c.setup_messages=[];c.question='Assess my current profile for MSAII.'
    rec=RecommendationDraft(program_id='cmu-msaii-pittsburgh',tier='Lottery',
        goal_feature_ids=['cmu-msaii-pittsburgh-industry'],tier_evidence_ids=['cmu-msaii-pittsburgh-2025-cohort'],
        comparison_dimensions=['selectivity'],lower_risk_rationale=None,
        limitations=['Cohort selectivity is a planning label, not personal admission odds.'])
    run=CandidateRun(runtime,c,'fixed',provider=Scripted(answer(recommendations=[rec]))).run()
    assert run['status']=='completed' and len(run['answer']['recommendations'])==1
    assert run['answer']['recommendations'][0]['tier']=='Lottery'


def test_search_is_exact_complete_and_responses_cannot_mutate_catalog(runtime):
    from gradmatch.homework.tools import SnapshotTools
    tools=SnapshotTools(runtime.programs,runtime.sources,date(2026,11,16))
    profile=candidate(runtime).profile
    rows=tools.dispatch('search_programs',dict(university=None,campus=None,discipline=None),profile)['programs']
    assert len(rows)==10 and [r['program_id'] for r in rows]==sorted(r['program_id'] for r in rows)
    assert tools.dispatch('search_programs',dict(university=None,campus='seattle',discipline=None),profile)['programs']==[]
    pid=rows[0]['program_id'];record=tools.dispatch('get_program',{'program_id':pid},profile)
    old=record['program']['program_name'];record['program']['program_name']='mutated'
    assert tools.dispatch('get_program',{'program_id':pid},profile)['program']['program_name']==old
