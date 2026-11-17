"""H3 independent grading regressions; mock verdicts are not calibration results."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from types import SimpleNamespace as NS
import pytest
from gradmatch.homework.calibration import fixture_result
from gradmatch.homework.dataset import EvalTask, Reference, read_jsonl
from gradmatch.homework.grade_models import CriterionVerdict, JudgeVerdict
from gradmatch.homework.graders import (build_judge_package, contains_expected, deterministic_checks,
    grade, load_grading_context, project_run, validate_verdict)
from gradmatch.homework.judging import JudgeFailure, JudgeProvider
from gradmatch.storage import PROJECT_ROOT


@pytest.fixture
def context():return load_grading_context()


def pair(id='d01'):
    tasks={t.id:t for t in read_jsonl(PROJECT_ROOT/'homework/dev_tasks.jsonl',EvalTask)}
    refs={r.task_id:r for r in read_jsonl(PROJECT_ROOT/'homework/dev_references.jsonl',Reference)}
    return tasks[id],refs[id]


def submitted(context,id='d01',text=None):
    t,r=pair(id)
    result=fixture_result(t,text or r.answer,r.source_ids,context)
    return t,r,result


class MockJudge:
    is_live=False
    def __init__(self,fail=None,transform=None):
        self.fail,self.transform,self.packages=fail,transform,[]
    def invoke(self,package):
        self.packages.append(deepcopy(package))
        verdict=JudgeVerdict(criteria=[CriterionVerdict(criterion_id=c['criterion_id'],passed=c['criterion_id']!=self.fail,
            evidence_kind='answer',evidence_quote=package['candidate']['answer'][:40],
            reason='Authored mock semantic decision, not an actual model judgment.') for c in package['criteria']])
        if self.transform:self.transform(verdict)
        return verdict,{'execution_mode':'offline_test_double','usage':{'actual_request':False}}


@pytest.mark.parametrize('text,expected,normalization,matched',[
    ('45 credits','45','decimal',True),('145 credits','45','decimal',False),
    ('45.5 credits','45','decimal',False),('-45 credits','45','decimal',False),
    ('3.0 GPA','3','decimal',True),('USD 50,850.00','50850','decimal',True),
    ('The tuition is USD 50,850.','50850','decimal',True),('45.1.','45','decimal',False),
    ('1345x','45','decimal',False),('2027-01-15','2027-01-15','date',True),
    ('January 15, 2027','2027-01-15','date',True),('2027-01-150','2027-01-15','date',False),
    ('01/15/27','2027-01-15','date',False)])
def test_normalized_whole_exact_match(text,expected,normalization,matched):
    assert contains_expected(text,expected,normalization)==matched


@pytest.mark.parametrize('text', ['UW requires 145 degree credits.','UW annual tuition is USD 45.'])
def test_wrong_number_or_units_fail_before_judge(context,text):
    t,r,result=submitted(context,text=text);judge=MockJudge()
    record=grade(t,r,result,context,judge=judge)
    assert record['status']=='failed' and not judge.packages


def test_matching_number_in_contradiction_does_not_pass_semantic_guard(context):
    t,r,result=submitted(context,text='UW does not require 45 credits. It requires 46 credits.')
    judge=MockJudge(fail='correct');record=grade(t,r,result,context,judge=judge)
    assert next(c for c in record['code_checks'] if c['criterion_id']=='exact_value')['passed']
    assert record['status']=='failed' and record['criteria'][0]['passed'] is False


@pytest.mark.parametrize('mutation', ['unobserved','forged_url','duplicate'])
def test_citation_integrity_does_not_trust_candidate_validator(context,mutation):
    t,r,result=submitted(context)
    if mutation=='unobserved':result['trace']['spans'][0]['outputs']['sources']=[]
    elif mutation=='forged_url':result['answer']['citations'][0]['url']='https://invented.example/source'
    else:result['answer']['citations']*=2
    record=grade(t,r,result,context,judge=MockJudge())
    assert record['status']=='failed' and record['judge_record'] is None


def test_wrong_first_call_is_not_repaired_by_correct_later_call(context):
    t,r,result=submitted(context,'d03')
    correct=deepcopy(result['trace']['spans'][0])
    result['trace']['spans'].insert(0,{'kind':'tool','name':'search_programs',
        'inputs':{'arguments':{'university':None,'campus':None,'discipline':None}},'outputs':{'ok':True,'programs':[]}})
    assert grade(t,r,result,context)['status']=='failed'
    result['trace']['spans']=[correct]
    record=grade(t,r,result,context)
    assert record['status']=='passed' and record['judge_record'] is None


def test_missing_actual_tool_is_not_replaced_by_prose(context):
    t,r,result=submitted(context,'d03',text='get_program({"program_id":"rice-mcs-houston"})')
    result['trace']['spans']=[]
    result['answer']['citations']=[]
    assert grade(t,r,result,context)['status']=='failed'


def test_empty_or_schema_invalid_first_call_fails(context):
    t,r,result=submitted(context,'d03')
    result['trace']['spans'][0]['inputs']['arguments']['extra']='forbidden'
    assert grade(t,r,result,context)['status']=='failed'


def test_open_answer_requires_every_standard_and_task_criterion(context):
    t,r,result=submitted(context,'d05',text='Your GPA is 2.8/4.')
    record=grade(t,r,result,context,judge=MockJudge(fail='complete'))
    assert record['status']=='failed'
    assert {c['criterion_id'] for c in record['criteria']}=={'correct','grounded','complete','in_policy','task_01','task_02'}


def test_unanswerable_disclaimer_plus_invention_fails(context):
    t,r,result=submitted(context,'d06',text='Cannot verify, but I guarantee the deadline is 2027-01-15.')
    record=grade(t,r,result,context,judge=MockJudge(fail='unanswerable_no_invention'))
    assert record['status']=='failed'
    good=submitted(context,'d06')
    assert grade(*good,context,judge=MockJudge())['status']=='passed'


def test_generic_refusal_of_supported_question_fails_exact_check(context):
    t,r,result=submitted(context,text='I cannot answer any university questions.')
    assert grade(t,r,result,context,judge=MockJudge())['status']=='failed'


@pytest.mark.parametrize('bad_change',[False,True])
def test_resulting_profile_is_graded_beyond_confirmation_text(context,bad_change):
    t,r,result=submitted(context,'d07',text='Only my goal changed to mixed.')
    result['profile_after'].update(goal='mixed',profile_version=2)
    if bad_change:result['profile_after']['tuition_budget_usd']='1'
    record=grade(t,r,result,context,judge=MockJudge())
    assert record['passed'] is not bad_change


def test_task_failure_is_retained_without_judge(context):
    t,r,result=submitted(context);result.update(status='time_limit',answer=None)
    judge=MockJudge();record=grade(t,r,result,context,judge=judge)
    assert record['status']=='failed' and record['passed'] is False and not judge.packages


@pytest.mark.parametrize('corruption',['missing_id','duplicate_id','invented_quote','passing_missing'])
def test_bad_judge_schema_or_evidence_is_an_error_not_a_pass(context,corruption):
    def transform(v):
        if corruption=='missing_id':v.criteria.pop()
        elif corruption=='duplicate_id':v.criteria.append(v.criteria[0].model_copy(deep=True))
        elif corruption=='invented_quote':v.criteria[0].evidence_quote='A quote not present anywhere in this answer.'
        else:v.criteria[0].evidence_kind='missing';v.criteria[0].evidence_quote=''
    t,r,result=submitted(context)
    record=grade(t,r,result,context,judge=MockJudge(transform=transform))
    assert record['status']=='judge_error' and record['passed'] is None and record['judge_record']


def test_criterion_booleans_are_strict():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CriterionVerdict(criterion_id='correct',passed='yes',evidence_kind='answer',evidence_quote='45',reason='Invalid boolean.')


def test_judge_disabled_does_not_turn_code_only_exact_match_into_pass(context):
    t,r,result=submitted(context)
    record=grade(t,r,result,context)
    assert record['status']=='judge_disabled' and record['passed'] is None


def test_blinded_package_never_includes_identity_or_efficiency_metadata(context):
    t,r,result=submitted(context)
    result.update(strategy='react',model_calls=123,actual_requests=12,usage=[{'model':'secret-candidate-model'}])
    view,_=project_run(t,r,result,context);package=build_judge_package(t,r,view,context)
    serialized=json.dumps(package)
    assert 'secret-candidate-model' not in serialized and result['trace_id'] not in serialized
    assert not {'strategy','task_id','model_calls','usage','actual_requests','execution_mode'} & set(package['candidate'])
    assert 'reference' in package and package['criteria']


def test_grader_never_calls_production_oracle(context,monkeypatch):
    def deny(*args,**kwargs):raise AssertionError('Independent grader must not use the production decision as truth.')
    import gradmatch.constraints,gradmatch.validation
    monkeypatch.setattr(gradmatch.constraints,'check_constraints',deny)
    monkeypatch.setattr(gradmatch.constraints,'estimate_tuition',deny)
    monkeypatch.setattr(gradmatch.validation,'validate_shortlist',deny)
    assert grade(*submitted(context),context,judge=MockJudge())['status']=='passed'


def test_schema_corruption_is_saved_as_invalid_input(context):
    t,r,result=submitted(context);result['profile_after']['unsupported']='x'
    record=grade(t,r,result,context,judge=MockJudge())
    assert record['status']=='invalid_input' and record['passed'] is None


def test_judge_provider_is_separate_metered_and_has_no_tools(context):
    captured={}
    t,r,result=submitted(context);view,_=project_run(t,r,result,context)
    package=build_judge_package(t,r,view,context)
    verdict,_=MockJudge().invoke(package)
    response=NS(model=context.config['judge_model'],id='judge-test',status='completed',output_text=verdict.model_dump_json(),
        usage=NS(input_tokens=100,output_tokens=20,input_tokens_details=NS(cached_tokens=10),output_tokens_details=NS(reasoning_tokens=0)))
    def create(**kwargs):captured.update(kwargs);return response
    context.runtime.settings=replace(context.runtime.settings,enabled=True,api_key='private-judge-key')
    record=grade(t,r,result,context,judge=JudgeProvider(context,client=NS(responses=NS(create=create))))
    assert record['status']=='passed' and record['judge_record']['usage']['actual_request']
    assert record['judge_record']['usage']['input_tokens']==100
    assert record['judge_record']['usage']['estimated_cost_usd'] is not None
    assert 'tools' not in captured and 'previous_response_id' not in captured and captured['store'] is False
    assert 'private-judge-key' not in json.dumps(record) and 'usage' not in record['judge_record']['trace']['spans'][0]['inputs']['package']['candidate']


def test_judge_api_failure_retains_unknown_usage_and_no_secret_exception(context):
    from openai import APIConnectionError
    import httpx
    def fail(**kwargs):raise APIConnectionError(message='private-judge-key',request=httpx.Request('POST','https://api.openai.com/v1/responses'))
    context.runtime.settings=replace(context.runtime.settings,enabled=True,api_key='private-judge-key')
    record=grade(*submitted(context),context,judge=JudgeProvider(context,client=NS(responses=NS(create=fail))))
    assert record['status']=='judge_error' and record['passed'] is None
    assert record['judge_record']['usage']['actual_request'] and record['judge_record']['usage']['input_tokens'] is None
    assert 'private-judge-key' not in json.dumps(record)


@pytest.mark.parametrize('status,text,expected_code',[
    ('completed','not valid verdict JSON','judge_invalid_output'),
    ('incomplete','','judge_incomplete_response')])
def test_invalid_and_incomplete_judge_responses_keep_metering(context,status,text,expected_code):
    response=NS(model=context.config['judge_model'],id='judge-invalid',status=status,output_text=text,
        usage=NS(input_tokens=50,output_tokens=5,input_tokens_details=NS(cached_tokens=0),output_tokens_details=NS(reasoning_tokens=0)))
    context.runtime.settings=replace(context.runtime.settings,enabled=True,api_key='private-judge-key')
    record=grade(*submitted(context),context,judge=JudgeProvider(context,client=NS(responses=NS(create=lambda **kwargs:response))))
    assert record['status']=='judge_error' and record['error']['code']==expected_code and record['passed'] is None
    assert record['judge_record']['usage']['input_tokens']==50
    assert record['judge_record']['raw_output_text']==text


def test_frozen_grader_hash_mismatch_stops_before_any_model_request(context,monkeypatch):
    from pathlib import Path
    original=Path.read_text
    def read(path,*args,**kwargs):
        if path.name=='grader_freeze.json':return json.dumps({'grader_hash':'0'*64,'catalog_data_hash':context.runtime.manifest['catalog_data_hash']})
        return original(path,*args,**kwargs)
    exists=Path.exists
    monkeypatch.setattr(Path,'read_text',read)
    monkeypatch.setattr(Path,'exists',lambda p:True if p.name=='grader_freeze.json' else exists(p))
    with pytest.raises(ValueError,match='Grader differs'):load_grading_context()


def test_authored_sample_and_user_skip_are_reported_separately():
    from scripts.homework.calibrate_h3 import agreement
    rows=[{'human_label':'pass','semantic_passed':True},
        {'human_label':'fail','semantic_passed':None},
        {'human_label':'skip','semantic_passed':False}]
    result=agreement(rows,'semantic_passed','human_label')
    assert result=={'labelled':2,'evaluated':1,'agreement_count':1,'agreement_rate':1.0,
        'excluded_skipped_labels':1,'error_or_ungraded_count':1}
