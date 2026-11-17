"""H4 schedules, recovery and arithmetic; fixtures never count as model benchmarks."""
from copy import deepcopy
import json
import os
from pathlib import Path
import socket
from uuid import uuid4
import pytest
from gradmatch.homework.dataset import candidate_input
from gradmatch.homework.engine import CandidateRun
from gradmatch.homework.experiment import (ExperimentStore,digest,execute,fingerprint,load_inputs,
    make_plan,schedule_for,write_new)
from gradmatch.homework.graders import grade
from gradmatch.homework.metrics import candidate_tokens,p95,summarize,write_reports
from gradmatch.homework.models import AnswerDraft,Decision,ToolCall
from gradmatch.storage import PROJECT_ROOT


@pytest.fixture
def bundle():
    return load_inputs(PROJECT_ROOT/'homework/dev_tasks.jsonl')


def store_for(tmp_path,bundle,ids=('d03',)):
    context,tasks,refs,split=bundle
    return ExperimentStore.create(tmp_path/'experiment',make_plan(context,tasks,split,
        task_ids=list(ids),execution_mode='offline_test_double'))


class OfflineProvider:
    is_live=False
    def invoke(self,purpose,payload,history,timeout):
        if purpose=='react' and not history:
            value=Decision(calls=[ToolCall('offline-call','get_program',json.dumps({'program_id':payload['declared_program_scope'][0]}))])
        else:
            value=Decision(answer=AnswerDraft(answer='The requested saved program record was retrieved.',
                citations=[],recommendations=[],needs_clarification=False))
        return value,{'actual_request':False,'status':'offline_test_double','input_tokens':None,
            'output_tokens':None,'cached_input_tokens':None,'estimated_cost_usd':None}


def factories():
    calls=[]
    def candidate(runtime,value,strategy):
        # The host passes only the H1 whitelist, never EvalTask or references.
        assert set(type(value).model_fields)=={'task_id','question','profile','setup_messages','program_ids','as_of_date'}
        calls.append((value.task_id,strategy))
        return CandidateRun(runtime,value,strategy,provider=OfflineProvider()).run()
    def grading(t,r,value,context):return grade(t,r,value,context)
    return candidate,grading,calls


def run_offline(store,bundle,**kwargs):
    context,tasks,refs,_=bundle
    return execute(store,context,tasks,refs,**kwargs)


def metric_payload(store,entry,*,passed=True,unknown_tokens=False,latency=None):
    fp=store.plan['fingerprint']
    usage={'actual_request':False,'input_tokens':None if unknown_tokens else 100,
        'output_tokens':20,'cached_input_tokens':80,'estimated_cost_usd':'0'}
    candidate={'task_id':entry['task_id'],'strategy':entry['strategy'],'trace_id':str(uuid4()),
        'execution_mode':'offline_test_double','status':'completed' if passed else 'time_limit',
        'model_calls':1,'tool_calls':1,'latency_ms':latency if latency is not None else entry['sequence']*1000,
        'usage':[usage],'configuration':{k:fp[k] for k in ['candidate_code_hash','catalog_data_hash','assessment_date','model']}}
    grading={'task_id':entry['task_id'],'candidate_trace_id':candidate['trace_id'],
        'candidate_record_sha256':digest(candidate),'grader_hash':fp['grader_hash'],
        'status':'passed' if passed else 'failed','passed':passed,
        'judge_record':{'latency_ms':100000,'usage':{'actual_request':False,'input_tokens':10,
            'output_tokens':1,'cached_input_tokens':0,'estimated_cost_usd':'0'}}}
    return candidate,grading


def save_pair(store,entry,candidate,grading):
    store.mark(entry,'candidate');store.save(entry,'candidate',candidate)
    store.mark(entry,'grade');store.save(entry,'grade',grading)


def synthetic_store(tmp_path,bundle,*,missing=None,unknown_tokens=False):
    store=store_for(tmp_path,bundle,('d01','d02'))
    with store.lock():
        for entry in store.plan['schedule']:
            if entry['run_id']==missing:continue
            passed=entry['task_id']=='d01' and (entry['strategy']=='fixed' or entry['repeat']!=2)
            candidate,grading=metric_payload(store,entry,passed=passed,unknown_tokens=unknown_tokens)
            save_pair(store,entry,candidate,grading)
    return store


def test_formal_schedule_exactly_200_unique_interleaved_runs(bundle):
    context,tasks,refs,split=load_inputs()
    plan=make_plan(context,tasks,split)
    assert len(plan['schedule'])==200 and len({e['run_id'] for e in plan['schedule']})==200
    assert sum(e['strategy']=='fixed' for e in plan['schedule'])==50
    assert sum(e['strategy']=='react' for e in plan['schedule'])==150
    assert plan['schedule'][:4]==schedule_for(['t01'])
    assert plan['schedule'][4]['strategy']=='react'
    with pytest.raises(ValueError):make_plan(context,tasks,split,task_ids=['t01'])
    with pytest.raises(ValueError):make_plan(context,tasks,split,execution_mode='offline_test_double')


def test_default_cli_is_a_real_no_cost_formal_plan(tmp_path,monkeypatch,capsys):
    import sys
    from scripts.homework.evaluate import main
    def deny(*args,**kwargs):raise AssertionError('Planning must not run a candidate or judge.')
    monkeypatch.setattr(CandidateRun,'run',deny)
    from gradmatch.homework.judging import JudgeProvider
    monkeypatch.setattr(JudgeProvider,'invoke',deny)
    directory=tmp_path/'dry-plan'
    monkeypatch.setattr(sys,'argv',['evaluate','--experiment-dir',str(directory)])
    assert main()==0
    report=json.loads(capsys.readouterr().out)
    assert report['scheduled_executions']==200 and report['baseline_executions']==50 and report['agent_executions']==150
    assert report['candidate_requests']==report['judge_requests']==0
    store=ExperimentStore(directory);summary=summarize(store)
    assert all(r['accuracy'] is None and r['avg_turns'] is None for r in summary['comparison'])
    assert summary['stability']['pass_at_3'] is None and not (directory/'entries').exists()


def test_actual_offline_agent_and_grader_integrate_and_resume_without_repeating(tmp_path,bundle):
    store=store_for(tmp_path,bundle);candidate,grading,calls=factories()
    run_offline(store,bundle,candidate_factory=candidate,grader_fn=grading,max_runs=2)
    first={p:p.read_bytes() for p in (store.path/'entries').glob('*/*.json')}
    assert len(calls)==2 and summarize(store)['stability']['pass_at_3'] is None
    records=run_offline(store,bundle,candidate_factory=candidate,grader_fn=grading)
    assert len(calls)==4 and all(p.read_bytes()==data for p,data in first.items())
    assert len({r['candidate']['trace_id'] for r in records})==4
    result=summarize(store)
    assert result['comparison'][0]['accuracy']==0 and result['comparison'][1]['accuracy']==1
    assert result['stability']['pass_at_3']==result['stability']['pass_all_3']==1
    assert result['candidate_usage']['known_actual_requests']==0
    assert result['comparison'][1]['avg_turns']==2 and result['comparison'][0]['avg_turns']==1
    assert result['comparison'][0]['avg_tokens'] is None
    run_offline(store,bundle,candidate_factory=candidate,grader_fn=grading)
    assert len(calls)==4


def test_observed_repeat_vectors_not_cube_and_failed_tail_not_dropped(tmp_path,bundle):
    store=synthetic_store(tmp_path,bundle)
    report=summarize(store);fixed,agent=report['comparison']
    assert fixed['accuracy']==agent['accuracy']==0.5
    assert fixed['scheduled']==agent['scheduled']==2
    assert fixed['avg_latency_ms']==4500 and fixed['p95_latency_ms']==8000
    assert agent['avg_latency_ms']==3500 and agent['p95_latency_ms']==5000
    assert fixed['avg_turns']==agent['avg_turns']==1 and fixed['avg_tokens']==120
    assert report['stability']['pass_at_3']==0.5 and report['stability']['pass_all_3']==0
    assert report['stability']['flip_tasks']==[{'task_id':'d01','outcomes':[True,False,True],'complete':True}]
    assert report['judge_usage']['judge_latency_ms_total']==800000
    assert fixed['avg_latency_ms']<report['judge_usage']['judge_latency_ms_total']


def test_missing_repeat_is_unresolved_not_a_smaller_denominator(tmp_path,bundle):
    store=synthetic_store(tmp_path,bundle,missing='d02--react--r3')
    report=summarize(store)
    assert report['pooled_agent']['scheduled']==6 and report['pooled_agent']['unresolved']==1
    assert report['pooled_agent']['accuracy'] is None
    assert report['pooled_agent']['pass_fraction_of_scheduled']==2/6
    assert report['stability']['pass_at_3'] is None and report['stability']['pass_all_3'] is None
    assert report['stability']['complete_vectors']==1
    assert report['stability']['vectors'][1]['outcomes']==[False,False,None]


def test_missing_usage_stays_unknown_while_accuracy_remains_known(tmp_path,bundle):
    report=summarize(synthetic_store(tmp_path,bundle,unknown_tokens=True))
    assert report['status']=='complete_with_measurement_gaps'
    assert report['comparison'][0]['accuracy']==0.5 and report['comparison'][0]['avg_tokens'] is None
    assert report['comparison'][0]['tokens_unknown_count']==2
    assert not report['candidate_usage']['usage_complete']


@pytest.mark.parametrize('n,expected',[(1,1),(20,19),(21,20)])
def test_nearest_rank_p95(n,expected):assert p95(list(range(1,n+1)))==expected


def test_zero_calls_are_known_zero_tokens_and_cache_is_not_added_twice():
    assert candidate_tokens({'model_calls':0,'usage':[]})==0
    assert candidate_tokens({'model_calls':1,'usage':[{'input_tokens':100,'output_tokens':30,'cached_input_tokens':80}]})==130
    assert candidate_tokens({'model_calls':1,'usage':[]}) is None
    with pytest.raises(ValueError):
        candidate_tokens({'model_calls':1,'usage':[{'input_tokens':10,'output_tokens':1,'cached_input_tokens':11}]})


@pytest.mark.parametrize('stage',['candidate_started','candidate_saved','grade_started'])
def test_crash_recovery_never_reissues_an_attempted_stage(tmp_path,bundle,stage):
    store=store_for(tmp_path,bundle);candidate,grading,calls=factories();grades=[]
    def counted_grade(*args):grades.append(True);return grading(*args)
    def crash(observed,entry):
        if observed==stage:raise KeyboardInterrupt('Simulated process interruption, not a model error.')
    with pytest.raises(KeyboardInterrupt):
        run_offline(store,bundle,candidate_factory=candidate,grader_fn=counted_grade,on_event=crash)
    assert not (store.path/'.writer.lock').exists()
    first=store.plan['schedule'][0]
    records=run_offline(store,bundle,candidate_factory=candidate,grader_fn=counted_grade)
    if stage=='candidate_saved':
        assert len(calls)==len(grades)==4 and records[0]['state']=='terminal'
    else:
        assert records[0]['state']=='interrupted_unknown'
        assert len(calls)==(3 if stage=='candidate_started' else 4) and len(grades)==3
        report=summarize(store)
        assert report['comparison'][0]['accuracy'] is None
        actor='candidate_usage' if stage=='candidate_started' else 'judge_usage'
        assert report[actor]['unknown_attempts']==1 and report[actor]['estimated_cost_usd'] is None
    before=len(calls)
    run_offline(store,bundle,candidate_factory=candidate,grader_fn=counted_grade)
    assert len(calls)==before


def test_unexpected_wrapper_failure_retains_safe_interruption(tmp_path,bundle):
    store=store_for(tmp_path,bundle);_,grading,calls=factories()
    def broken(*args):raise RuntimeError('private-key-must-not-be-logged')
    run_offline(store,bundle,candidate_factory=broken,grader_fn=grading,max_runs=1)
    record=store.records()[0]
    assert record['state']=='interrupted_unknown' and record['candidate'] is None
    assert 'private-key' not in json.dumps(record)


def test_corrupt_candidate_is_not_overwritten_or_retried(tmp_path,bundle):
    store=store_for(tmp_path,bundle);candidate,grading,calls=factories()
    run_offline(store,bundle,candidate_factory=candidate,grader_fn=grading,max_runs=1)
    path=store.run_path(store.plan['schedule'][0])/'candidate.json'
    data=json.loads(path.read_text(encoding='utf-8'));data['payload']['model_calls']=999
    path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='content changed'):
        run_offline(store,bundle,candidate_factory=candidate,grader_fn=grading)
    assert len(calls)==1


def test_foreign_grade_pairing_and_unscheduled_directory_are_rejected(tmp_path,bundle):
    store=synthetic_store(tmp_path,bundle);entry=store.plan['schedule'][0]
    path=store.run_path(entry)/'grade.json';data=json.loads(path.read_text(encoding='utf-8'))
    data['payload']['candidate_trace_id']='different-trace';data['payload_sha256']=digest(data['payload'])
    path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='Grade does not refer'):store.records()


def test_unknown_run_directory_rejected(tmp_path,bundle):
    store=store_for(tmp_path,bundle);(store.path/'entries'/'foreign-run').mkdir(parents=True)
    with pytest.raises(ValueError,match='Unscheduled'):store.records()


def test_immutable_manifest_and_output_are_not_replaced(tmp_path,bundle):
    store=store_for(tmp_path,bundle)
    with pytest.raises(FileExistsError):ExperimentStore.create(store.path,store.plan)
    p=tmp_path/'record.json';write_new(p,{'value':1})
    with pytest.raises(FileExistsError):write_new(p,{'value':2})
    assert json.loads(p.read_text())=={'value':1}
    altered=deepcopy(store.plan);altered['schedule'][0]['repeat']=2
    from gradmatch.homework.experiment import validate_plan
    with pytest.raises(ValueError,match='manifest changed'):validate_plan(altered)


def test_configuration_change_refuses_resume_before_calls(tmp_path,bundle):
    store=store_for(tmp_path,bundle);candidate,grading,calls=factories()
    context,tasks,refs,split=bundle
    changed=deepcopy(context);changed.runtime.code_hash='0'*64
    with pytest.raises(ValueError,match='changed'):
        execute(store,changed,tasks,refs,candidate_factory=candidate,grader_fn=grading)
    assert not calls


def test_writer_lock_and_verified_stale_recovery(tmp_path,bundle,monkeypatch):
    store=store_for(tmp_path,bundle)
    with store.lock():
        with pytest.raises(ValueError,match='writer'):
            with store.lock():pass
        with pytest.raises(ValueError,match='owner'):
            with store.lock(recover=True):pass
    path=store.path/'.writer.lock'
    path.write_text(json.dumps({'owner_id':'old','pid':99999999,'host':socket.gethostname()}),encoding='utf-8')
    import gradmatch.homework.experiment as module
    monkeypatch.setattr(module,'process_alive',lambda pid:False)
    with store.lock(recover=True):assert path.exists()
    assert not path.exists()
    path.write_text(json.dumps({'owner_id':'foreign','pid':99999999,'host':'different-host'}),encoding='utf-8')
    with pytest.raises(ValueError,match='owner'):
        with store.lock(recover=True):pass
    assert path.exists()


def test_real_experiments_refuse_test_double_injection(tmp_path,bundle):
    context,tasks,refs,split=bundle
    store=ExperimentStore.create(tmp_path/'real-plan',make_plan(context,tasks,split,task_ids=['d03']))
    candidate,grading,_=factories()
    with pytest.raises(ValueError,match='cannot use injected'):
        execute(store,context,tasks,refs,candidate_factory=candidate,grader_fn=grading)


def test_grading_errors_are_unresolved_and_no_auto_regrading(tmp_path,bundle):
    store=store_for(tmp_path,bundle);candidate,_,calls=factories();grades=[]
    def error_grade(t,r,value,context):
        grades.append(True)
        return {'task_id':t.id,'candidate_trace_id':value['trace_id'],'candidate_record_sha256':digest(value),
            'grader_hash':context.grader_hash,'status':'judge_error','passed':None,'judge_record':None}
    run_offline(store,bundle,candidate_factory=candidate,grader_fn=error_grade)
    report=summarize(store)
    assert report['comparison'][0]['grading_errors']==1 and report['comparison'][0]['scheduled']==1
    assert report['comparison'][0]['accuracy'] is None and report['comparison'][0]['pass_fraction_of_scheduled']==0
    run_offline(store,bundle,candidate_factory=candidate,grader_fn=error_grade)
    assert len(grades)==len(calls)==4


def test_reports_recompute_offline_without_reading_key_or_rewriting_raw_data(tmp_path,bundle,monkeypatch):
    store=synthetic_store(tmp_path,bundle)
    before={p:p.read_bytes() for p in store.path.rglob('*.json')}
    import gradmatch.config
    monkeypatch.setattr(gradmatch.config,'load_settings',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No credentials needed.')))
    report=summarize(ExperimentStore(store.path));target=tmp_path/'reports'
    write_reports(report,target)
    assert all(p.read_bytes()==value for p,value in before.items())
    assert 'OFFLINE FIXTURE' in (target/'results.md').read_text(encoding='utf-8')
    assert json.loads((target/'flip_tasks.json').read_text())[0]['outcomes']==[True,False,True]
    assert (target/'results.csv').read_text().count('\n')==3
    with pytest.raises(FileExistsError):write_reports(report,target)


def test_attempt_markers_are_bound_to_their_run(tmp_path,bundle):
    store=store_for(tmp_path,bundle);entry=store.plan['schedule'][0]
    with store.lock():store.mark(entry,'candidate')
    path=store.run_path(entry)/'candidate.started.json'
    obj=json.loads(path.read_text());obj['run_id']='foreign'
    path.write_text(json.dumps(obj),encoding='utf-8')
    with pytest.raises(ValueError,match='Attempt marker'):store.records()


def test_no_judge_record_on_judge_error_is_unknown_not_zero_usage(tmp_path,bundle):
    from gradmatch.homework.metrics import actor_usage
    record={'candidate':None,'grade':{'status':'judge_error','judge_record':None},
        'state':'terminal','interruption':None}
    usage=actor_usage([record],'judge')
    assert usage['unknown_attempts']==1 and usage['estimated_cost_usd'] is None
    assert usage['judge_latency_ms_total'] is None


def test_known_tokens_with_unknown_actual_request_cost_are_flagged(tmp_path,bundle):
    store=store_for(tmp_path,bundle);entry=store.plan['schedule'][0]
    candidate,grading=metric_payload(store,entry)
    candidate['usage'][0].update(actual_request=True,estimated_cost_usd=None)
    grading['candidate_record_sha256']=digest(candidate)
    with store.lock():save_pair(store,entry,candidate,grading)
    report=summarize(store)
    assert report['candidate_usage']['usage_complete']
    assert not report['candidate_usage']['cost_complete']
    assert report['candidate_usage']['estimated_cost_usd'] is None


def test_reused_trace_ids_across_repeats_are_rejected(tmp_path,bundle):
    store=synthetic_store(tmp_path,bundle)
    entries=store.plan['schedule'][:2]
    first=store.read_payload(entries[0],'candidate')
    path=store.run_path(entries[1])/'candidate.json'
    record=json.loads(path.read_text());record['payload']['trace_id']=first['trace_id']
    record['payload_sha256']=digest(record['payload']);path.write_text(json.dumps(record),encoding='utf-8')
    grade_path=path.with_name('grade.json');grading=json.loads(grade_path.read_text())
    grading['payload']['candidate_trace_id']=first['trace_id']
    grading['payload']['candidate_record_sha256']=digest(record['payload'])
    grading['payload_sha256']=digest(grading['payload']);grade_path.write_text(json.dumps(grading),encoding='utf-8')
    with pytest.raises(ValueError,match='not isolated'):store.records()
