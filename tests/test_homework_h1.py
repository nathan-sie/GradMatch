"""H1 data integrity, independent arithmetic and evaluator/candidate isolation."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import socket
import pytest
from pydantic import ValidationError
from gradmatch.catalog import load_seed
from gradmatch.homework.dataset import EvalTask, ExpectedCall, Reference, candidate_input, load_candidate_inputs, read_jsonl
from gradmatch.homework.validation import validate_bundle, validate_records
from gradmatch.storage import PROJECT_ROOT

FOLDER=PROJECT_ROOT/'homework'


def records():
    return read_jsonl(FOLDER/'tasks.jsonl',EvalTask),read_jsonl(FOLDER/'references.jsonl',Reference)


def validate(tasks,refs):
    programs,sources=load_seed()
    return validate_records(tasks,refs,programs,sources)


def test_complete_bundle_is_offline_and_has_required_coverage(monkeypatch):
    def deny(*args,**kwargs):raise AssertionError('H1 must not make network/model requests')
    monkeypatch.setattr(socket.socket,'connect',deny)
    monkeypatch.setattr(socket,'create_connection',deny)
    from gradmatch.providers import OpenAIProvider
    monkeypatch.setattr(OpenAIProvider,'generate',deny)
    report=validate_bundle()
    assert report['status']=='passed' and report['model_api_calls']==0
    assert report['formal']['types']=={'exact':18,'rubric':20,'tool':8,'unanswerable':4}
    assert report['formal']['tasks']==50 and report['formal']['edge_cases']==11
    assert len(report['formal']['programs_covered'])==10 and report['development']['tasks']==8


def test_expected_arithmetic_does_not_reuse_the_production_oracle(monkeypatch):
    import gradmatch.constraints
    def deny(*args,**kwargs):raise AssertionError('References must not be copied from production checker')
    monkeypatch.setattr(gradmatch.constraints,'estimate_tuition',deny)
    monkeypatch.setattr(gradmatch.constraints,'check_constraints',deny)
    assert validate_bundle()['status']=='passed'


@pytest.mark.parametrize('mutation',['count','duplicate_id','duplicate_question','missing_edges','wrong_exact','invalid_exact_number','wrong_fact','wrong_source','unsupported_text','stale_tool_version','outside_tool_scope','unsupported_update'])
def test_invalid_references_or_dataset_structure_are_rejected(mutation):
    tasks,refs=records()
    if mutation=='count':tasks.pop()
    if mutation=='duplicate_id':tasks[1].id=tasks[0].id
    if mutation=='duplicate_question':tasks[1].question=tasks[0].question.upper()
    if mutation=='missing_edges':
        for t in tasks:t.tags=[x for x in t.tags if x!='edge_case'] or ['normal']
    if mutation=='wrong_exact':tasks[0].expected='50849'
    if mutation=='invalid_exact_number':tasks[0].expected='USD fifty thousand'
    if mutation=='wrong_fact':refs[0].claims[0].value='1'
    if mutation=='wrong_source':
        refs[0].claims[0].source_ids=['cmu-msaii-pittsburgh-msaii_fees-m35']
        refs[0].source_ids.append('cmu-msaii-pittsburgh-msaii_fees-m35')
    if mutation=='unsupported_text':
        r=next(r for r in refs if r.source_assertions);r.source_assertions[0].contains='An invented official fact.'
    if mutation=='stale_tool_version':
        t=next(t for t in tasks if t.expected_call and t.expected_call.name=='check_program');t.expected_call.arguments['profile_version']=2
    if mutation=='outside_tool_scope':
        t=next(t for t in tasks if t.expected_call and t.expected_call.name=='get_program');t.program_ids=[]
    if mutation=='unsupported_update':
        r=next(r for r in refs if r.expected_profile_changes);r.expected_profile_changes['profile_version']=99
    with pytest.raises(ValueError):validate(tasks,refs)


@pytest.mark.parametrize('bad_call',[
    {'name':'browse_web','arguments':{'url':'https://example.com'}},
    {'name':'check_program','arguments':{'program_id':'cmu-msaii-pittsburgh','profile_version':'1'}},
    {'name':'get_program','arguments':{'program_id':'cmu-msaii-pittsburgh','hidden_answer':'Lottery'}},
])
def test_tool_contract_rejects_unknown_tools_argument_types_and_extra_fields(bad_call):
    with pytest.raises(ValidationError):ExpectedCall.model_validate(bad_call)


def test_candidate_projection_hides_answers_rubrics_tags_families_and_is_a_deep_copy(monkeypatch):
    tasks,refs=records(); marker='EVALUATOR_ONLY_SENTINEL_8942'
    exact=next(t for t in tasks if t.type=='exact');exact.expected=marker
    rubric=next(t for t in tasks if t.type=='rubric');rubric.rubric=[marker]
    for task in [exact,rubric]:
        visible=candidate_input(task,date(2026,11,16))
        assert marker not in visible.model_dump_json()
        assert set(visible.model_dump())=={'task_id','question','profile','setup_messages','program_ids','as_of_date'}
        visible.profile.gpa.value=Decimal('1')
        assert task.profile.gpa.value!=1
    original=Path.read_text
    def no_references(path,*args,**kwargs):
        if 'reference' in path.name:raise AssertionError('Candidate loader must not read evaluator reference files')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',no_references)
    assert len(load_candidate_inputs(FOLDER/'tasks.jsonl',date(2026,11,16)))==50


@pytest.mark.parametrize('line',['{}\n\n','{"id":"t01","id":"t02"}\n','{"value":NaN}\n'])
def test_jsonl_rejects_blank_duplicate_key_and_nonfinite_records(tmp_path,line):
    path=tmp_path/'bad.jsonl';path.write_text(line,encoding='utf-8')
    with pytest.raises(ValueError):read_jsonl(path,EvalTask)


def test_hypothetical_deadline_and_non_us_degree_inputs_are_unambiguous():
    tasks,_=records()
    non_us=next(t for t in tasks if t.family=='english_intake_validity' and t.profile.degree.country=='CN')
    assert non_us.profile.institution_country=='CN'
    day=next(t for t in tasks if t.family=='deadline_clock_ambiguity')
    assert 'Suppose' in day.question and '2026-12-09' in day.question
    assert not day.setup_messages
