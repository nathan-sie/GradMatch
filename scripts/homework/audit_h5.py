"""Audit actual H5 execution records and estimate formal cost from a separate pilot."""
import argparse
from collections import Counter
from decimal import Decimal,ROUND_UP
from pathlib import Path
from gradmatch.homework.experiment import ExperimentStore,load_inputs,write_new
from gradmatch.homework.metrics import actor_usage,summarize


def audit(store):
    records=store.records()
    trace_errors=[];limit_errors=[];model_errors=[]
    candidate_status=Counter();grade_status=Counter();code_failures=Counter()
    for record in records:
        candidate,grading=record['candidate'],record['grade']
        if candidate is None:continue
        candidate_status[candidate['status']]+=1
        limits=store.plan['fingerprint']['candidate_limits']
        if candidate['model_calls']>limits['max_model_calls_per_task'] or candidate['tool_calls']>limits['max_tool_calls_per_task']:
            limit_errors.append(record['run_id'])
        spans=candidate['trace']['spans']
        ids=[s['span_id'] for s in spans]
        if candidate['trace']['trace_id']!=candidate['trace_id'] or len(ids)!=len(set(ids)) or any(
                not s.get('finished_at') or s['status']=='running' or
                (s['parent_id'] is not None and s['parent_id'] not in ids) for s in spans):
            trace_errors.append(record['run_id'])
        if len(candidate['usage'])!=candidate['model_calls']:
            trace_errors.append(record['run_id'])
        if any(u.get('model')!=store.plan['fingerprint']['model'] for u in candidate['usage']):
            model_errors.append(record['run_id'])
        if grading:
            grade_status[grading['status']]+=1
            code_failures.update(c['criterion_id'] for c in grading['code_checks'] if not c['passed'])
    summary=summarize(store)
    return {'experiment_id':store.plan['experiment_id'],'plan_hash':store.plan['plan_hash'],
        'split':store.plan['split'],'execution_mode':store.plan['execution_mode'],
        'scheduled':len(records),'candidate_records':sum(r['candidate'] is not None for r in records),
        'grading_records':sum(r['grade'] is not None for r in records),
        'all_scheduled_outcomes_known':all(r['grade'] and type(r['grade']['passed']) is bool for r in records),
        'trace_errors':sorted(set(trace_errors)),'limit_errors':limit_errors,'model_version_errors':model_errors,
        'candidate_statuses':dict(candidate_status),'grading_statuses':dict(grade_status),
        'failed_code_checks':dict(code_failures),'summary':summary}


def forecast(records,pilot_types,formal_types):
    cells=[]
    for strategy,repeats in [('fixed',1),('react',3)]:
        for task_type,count in sorted(Counter(formal_types.values()).items()):
            selected=[r for r in records if r['strategy']==strategy and pilot_types[r['task_id']]==task_type and r['candidate'] is not None and r['grade'] is not None]
            candidate_costs=[actor_usage([r],'candidate')['estimated_cost_usd'] for r in selected]
            judge_costs=[actor_usage([r],'judge')['estimated_cost_usd'] for r in selected]
            complete=bool(selected) and all(v is not None for v in candidate_costs+judge_costs)
            mean_candidate=sum(Decimal(v) for v in candidate_costs)/len(selected) if complete else None
            mean_judge=sum(Decimal(v) for v in judge_costs)/len(selected) if complete else None
            projected=(mean_candidate+mean_judge)*count*repeats if complete else None
            cells.append({'strategy':strategy,'task_type':task_type,'pilot_executions':len(selected),
                'formal_executions':count*repeats,
                'candidate_mean_usd':str(mean_candidate) if mean_candidate is not None else None,
                'judge_mean_usd':str(mean_judge) if mean_judge is not None else None,
                'projected_usd':str(projected) if projected is not None else None})
    complete=all(c['projected_usd'] is not None for c in cells)
    total=sum(Decimal(c['projected_usd']) for c in cells) if complete else None
    return {'method':'Per-strategy/per-task-type pilot means, weighted by the 50-task formal distribution and 1+3 repeats.',
        'cells':cells,'estimated_formal_usd':str(total) if total is not None else None,
        'two_times_planning_allowance_usd':str((total*2).quantize(Decimal('0.01'),rounding=ROUND_UP)) if total is not None else None,
        'complete':complete,'limitation':'Eight selected development questions may underrepresent multi-program and long follow-up tasks. The allowance is a planning estimate, not a price guarantee or API spending limit.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot-dir',type=Path,required=True)
    parser.add_argument('--formal-dir',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    _,dev,_,_=load_inputs(Path(__file__).resolve().parents[2]/'homework/dev_tasks.jsonl')
    _,formal,_,_=load_inputs()
    pilot=ExperimentStore(args.pilot_dir)
    if pilot.plan['split']!='development':raise ValueError('Pilot must use the separate development split.')
    result={'checkpoint':'H5','purpose':'actual_execution_audit_not_submission_failure_analysis',
        'pilot':audit(pilot),'formal_cost_forecast':forecast(pilot.records(),{t.id:t.type for t in dev},{t.id:t.type for t in formal})}
    if args.formal_dir:
        store=ExperimentStore(args.formal_dir)
        if store.plan['split']!='formal':raise ValueError('Expected a formal experiment.')
        result['formal']=audit(store)
    write_new(args.output,result)
    print('Saved H5 audit:',args.output)
    return 0


if __name__=='__main__':raise SystemExit(main())
