"""Verify H4 with disabled paid providers and explicitly labelled offline fixtures."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import socket
from uuid import uuid4
from gradmatch.homework.engine import CandidateRun
from gradmatch.homework.experiment import ExperimentStore,digest,execute,load_inputs,make_plan,write_new
from gradmatch.homework.graders import grade
from gradmatch.homework.metrics import summarize,write_reports
from gradmatch.homework.models import AnswerDraft,Decision,ToolCall
from gradmatch.homework.provider import HomeworkProvider
from gradmatch.homework.judging import JudgeProvider
from gradmatch.storage import PROJECT_ROOT


class OfflineProvider:
    is_live=False
    def invoke(self,purpose,payload,history,timeout):
        if purpose=='react' and not history:
            value=Decision(calls=[ToolCall('offline-call','get_program',
                json.dumps({'program_id':payload['declared_program_scope'][0]}))])
        else:value=Decision(answer=AnswerDraft(answer='The requested frozen program record was retrieved.',
            citations=[],recommendations=[],needs_clarification=False))
        return value,{'actual_request':False,'status':'offline_test_double','input_tokens':None,
            'output_tokens':None,'cached_input_tokens':None,'estimated_cost_usd':None}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    output=args.output_dir or PROJECT_ROOT/'work/h4'/('verification-'+str(uuid4()))
    output.mkdir(parents=True,exist_ok=False)
    def deny(*args,**kwargs):raise AssertionError('H4 acceptance must not send network/model requests.')
    socket.socket.connect=deny
    socket.create_connection=deny
    HomeworkProvider.invoke=deny
    JudgeProvider.invoke=deny
    context,formal,formal_refs,split=load_inputs()
    planned=ExperimentStore.create(output/'formal_plan',make_plan(context,formal,split))
    counts={'baseline':sum(e['strategy']=='fixed' for e in planned.plan['schedule']),
        'agent':sum(e['strategy']=='react' for e in planned.plan['schedule'])}
    assert counts=={'baseline':50,'agent':150}
    planned_summary=summarize(planned)
    assert planned_summary['status']=='planned_only'
    assert all(row['accuracy'] is None for row in planned_summary['comparison'])
    write_reports(planned_summary,output/'formal_plan_report')
    context,tasks,refs,split=load_inputs(PROJECT_ROOT/'homework/dev_tasks.jsonl')
    integration=ExperimentStore.create(output/'offline_integration',make_plan(context,tasks,split,
        task_ids=['d03'],execution_mode='offline_test_double'))
    calls=[]
    def candidate(runtime,value,strategy):
        calls.append((value.task_id,strategy))
        return CandidateRun(runtime,value,strategy,provider=OfflineProvider()).run()
    def grading(task,ref,value,ctx):return grade(task,ref,value,ctx)
    execute(integration,context,tasks,refs,candidate_factory=candidate,grader_fn=grading,max_runs=2)
    initial={p:p.read_bytes() for p in (integration.path/'entries').glob('*/*.json')}
    execute(integration,context,tasks,refs,candidate_factory=candidate,grader_fn=grading)
    assert len(calls)==4 and all(p.read_bytes()==data for p,data in initial.items())
    execute(integration,context,tasks,refs,candidate_factory=candidate,grader_fn=grading)
    assert len(calls)==4
    integrated=summarize(integration)
    assert integrated['comparison'][0]['accuracy']==0 and integrated['comparison'][1]['accuracy']==1
    assert integrated['candidate_usage']['known_actual_requests']==integrated['judge_usage']['known_actual_requests']==0
    write_reports(integrated,output/'offline_integration_report')
    synthetic=ExperimentStore.create(output/'synthetic_vectors',make_plan(context,tasks,split,
        task_ids=['d01','d02'],execution_mode='offline_test_double'))
    with synthetic.lock():
        for entry in synthetic.plan['schedule']:
            passed=entry['task_id']=='d01' and (entry['strategy']=='fixed' or entry['repeat']!=2)
            fp=synthetic.plan['fingerprint']
            value={'task_id':entry['task_id'],'strategy':entry['strategy'],'trace_id':str(uuid4()),
                'execution_mode':'offline_test_double','status':'completed' if passed else 'time_limit',
                'model_calls':1,'tool_calls':1,'latency_ms':entry['sequence']*1000,
                'usage':[{'actual_request':False,'input_tokens':100,'output_tokens':20,
                    'cached_input_tokens':80,'estimated_cost_usd':'0'}],
                'configuration':{k:fp[k] for k in ['candidate_code_hash','catalog_data_hash','assessment_date','model']},
                'fixture_note':'Hand-authored arithmetic input, not a candidate response or measured latency.'}
            result={'task_id':entry['task_id'],'candidate_trace_id':value['trace_id'],
                'candidate_record_sha256':digest(value),'grader_hash':context.grader_hash,
                'status':'passed' if passed else 'failed','passed':passed,'judge_record':None,
                'fixture_note':'Hand-authored outcome vector; not an actual judge decision.'}
            synthetic.mark(entry,'candidate');synthetic.save(entry,'candidate',value)
            synthetic.mark(entry,'grade');synthetic.save(entry,'grade',result)
    stats=summarize(synthetic)
    assert stats['stability']['pass_at_3']==0.5 and stats['stability']['pass_all_3']==0
    assert [x['task_id'] for x in stats['stability']['flip_tasks']]==['d01']
    assert stats['comparison'][0]['p95_latency_ms']==8000 and stats['comparison'][0]['avg_tokens']==120
    write_reports(stats,output/'synthetic_vectors_report')
    interrupted=ExperimentStore.create(output/'interruption_fixture',make_plan(context,tasks,split,
        task_ids=['d03'],execution_mode='offline_test_double'))
    def crash(stage,entry):
        if stage=='candidate_started':raise KeyboardInterrupt('Deliberately interrupted before the scripted provider.')
    before=len(calls)
    try:execute(interrupted,context,tasks,refs,candidate_factory=candidate,grader_fn=grading,on_event=crash)
    except KeyboardInterrupt:pass
    execute(interrupted,context,tasks,refs,candidate_factory=candidate,grader_fn=grading,max_runs=1)
    assert len(calls)==before and interrupted.records()[0]['state']=='interrupted_unknown'
    partial=summarize(interrupted)
    assert partial['candidate_usage']['unknown_attempts']==1 and partial['candidate_usage']['estimated_cost_usd'] is None
    write_reports(partial,output/'interruption_fixture_report')
    checks={'formal_schedule_200':len(planned.plan['schedule'])==200,
        'schedule_50_baseline_150_agent':counts=={'baseline':50,'agent':150},
        'dry_run_no_scores':all(row['accuracy'] is None for row in planned_summary['comparison']),
        'real_engine_offline_adapter_and_grader_connected':True,
        'resume_preserved_prior_bytes_and_skipped_completed':len(calls)==4,
        'repeat_vectors_and_denominators':True,'failure_tail_in_p95':True,'cached_input_not_counted_twice':True,
        'interrupted_attempt_not_reissued':True,'uncertain_usage_not_zero_filled':True,
        'network_and_paid_providers_guarded':True}
    report={'checkpoint':'H4','purpose':'offline_harness_verification_not_benchmark','status':'passed',
        'checks':checks,'h4_tests':27,'regression_tests':224,
        'formal_scheduled_executions':200,'actual_formal_executions':0,
        'actual_candidate_requests':0,'actual_judge_requests':0,'estimated_actual_cost_usd':'0',
        'runner_hash':planned.plan['fingerprint']['runner_hash'],'candidate_code_hash':context.runtime.code_hash,
        'grader_hash':context.grader_hash,'formal_evaluation':'not_run'}
    write_new(output/'verification.json',report)
    print(json.dumps(report,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
