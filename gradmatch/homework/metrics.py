"""Offline recomputation of frozen H4 denominators, efficiency and repeat stability."""
import csv
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
from uuid import uuid4
from gradmatch.homework.experiment import write_new
from gradmatch.homework.trace import timestamp


def number(value,*,integer=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:return None
    if integer and not isinstance(value,int):return None
    return value


def candidate_tokens(candidate):
    if candidate is None:return None
    calls=number(candidate.get('model_calls'),integer=True)
    usage=candidate.get('usage')
    if calls is None or not isinstance(usage,list) or len(usage)!=calls:return None
    total=0
    for item in usage:
        values=[number(item.get(key),integer=True) for key in ['input_tokens','output_tokens']]
        if any(v is None for v in values):return None
        cached=item.get('cached_input_tokens')
        if cached is not None and (number(cached,integer=True) is None or cached>values[0]):
            raise ValueError('Invalid cached-input subset.')
        total+=sum(values)  # Cached tokens are already included in input.
    return total


def observed_mean(values):
    return sum(values)/len(values) if values else None


def p95(values):
    return sorted(values)[math.ceil(0.95*len(values))-1] if values else None


def known_pass(record):
    grading=record.get('grade')
    return grading['passed'] if grading and grading['status'] in {'passed','failed'} else None


def group(records,label):
    n=len(records)
    outcomes=[known_pass(r) for r in records]
    candidates=[r['candidate'] for r in records]
    turns=[number(c.get('model_calls'),integer=True) if c else None for c in candidates]
    latency=[number(c.get('latency_ms')) if c else None for c in candidates]
    tokens=[candidate_tokens(c) for c in candidates]
    complete=all(v is not None for v in outcomes)
    present=[r for r in records if r['state']!='pending']
    passed=sum(v is True for v in outcomes)
    counts={'scheduled':n,'candidate_records':sum(c is not None for c in candidates),
        'passed':passed,'failed':sum(v is False for v in outcomes),
        'grading_errors':sum(r['grade'] is not None and r['grade']['status'] not in {'passed','failed'} for r in records),
        'interrupted_unknown':sum(r['state']=='interrupted_unknown' for r in records),
        'unresolved':sum(v is None for v in outcomes)}
    result={'label':label,**counts,'accuracy':passed/n if complete and n else None,
        'accuracy_final':complete and bool(n),'pass_fraction_of_scheduled':passed/n if present and n else None,
        'provisional_fraction':bool(present) and not complete}
    for name,values in [('turns',turns),('latency_ms',latency),('tokens',tokens)]:
        known=[v for v in values if v is not None]
        result['avg_'+name]=observed_mean(known) if len(known)==n and n else None
        result[name+'_known_count']=len(known)
        result[name+'_unknown_count']=n-len(known)
        result[name+'_observed_mean']=observed_mean(known)
    result['p95_latency_ms']=p95(latency) if all(v is not None for v in latency) and n else None
    return result


def actor_usage(records,actor):
    requests=0;unknown_attempts=0;known_cost=Decimal(0);unknown_cost_calls=0
    known_input=known_output=0;unknown_token_calls=0;known_latency=[];unknown_latency=0
    for r in records:
        if actor=='candidate':
            obj=r['candidate']
            usage=obj.get('usage',[]) if obj else []
            attempted=bool(obj) or r['state']=='candidate_in_flight' or bool(r['interruption'] and r['interruption']['stage']=='candidate')
            if obj is None and attempted:unknown_attempts+=1
            if obj is not None and number(obj.get('model_calls'),integer=True)!=len(usage):unknown_attempts+=1
        else:
            obj=(r['grade'] or {}).get('judge_record')
            usage=[obj['usage']] if obj else []
            if r['state']=='grading_in_flight' or (r['interruption'] and r['interruption']['stage']=='grade'):
                unknown_attempts+=1
            elif (r['grade'] or {}).get('status')=='judge_error' and obj is None:
                unknown_attempts+=1
            if obj:
                if number(obj.get('latency_ms')) is not None:known_latency.append(obj['latency_ms'])
                else:unknown_latency+=1
        for item in usage:
            actual=item.get('actual_request')
            if type(actual) is not bool:raise ValueError('Request metering must be a strict boolean.')
            requests+=actual
            iv,ov=number(item.get('input_tokens'),integer=True),number(item.get('output_tokens'),integer=True)
            if iv is None or ov is None:unknown_token_calls+=1
            else:known_input+=iv;known_output+=ov
            raw=item.get('estimated_cost_usd')
            if raw is None:
                if actual:unknown_cost_calls+=1
            else:
                try:cost=Decimal(raw)
                except (InvalidOperation,TypeError):raise ValueError('Invalid saved cost estimate.') from None
                if not cost.is_finite() or cost<0:raise ValueError('Invalid saved cost estimate.')
                known_cost+=cost
    return {'known_actual_requests':requests,'unknown_attempts':unknown_attempts,
        'known_input_tokens':known_input,'known_output_tokens':known_output,'unknown_usage_calls':unknown_token_calls,
        'known_estimated_cost_usd':str(known_cost),
        'estimated_cost_usd':str(known_cost) if unknown_cost_calls==0 and unknown_attempts==0 else None,
        'unknown_cost_calls':unknown_cost_calls,'cost_complete':unknown_cost_calls==0 and unknown_attempts==0,
        'usage_complete':unknown_token_calls==0 and unknown_attempts==0,
        'judge_latency_ms_known_sum':sum(known_latency) if actor=='judge' else None,
        'judge_latency_unknown_records':unknown_latency+unknown_attempts if actor=='judge' else None,
        'judge_latency_ms_total':sum(known_latency) if actor=='judge' and not unknown_latency and not unknown_attempts else None}


def summarize(store):
    records=store.records();plan=store.plan
    baseline=[r for r in records if r['strategy']=='fixed']
    first=[r for r in records if r['strategy']=='react' and r['repeat']==1]
    agent=[r for r in records if r['strategy']=='react']
    by_key={(r['task_id'],r['strategy'],r['repeat']):r for r in records}
    vectors=[];flips=[]
    for task in plan['task_ids']:
        values=[known_pass(by_key[(task,'react',i)]) for i in (1,2,3)]
        item={'task_id':task,'outcomes':values,'complete':all(v is not None for v in values)}
        vectors.append(item)
        if item['complete'] and any(values) and not all(values):flips.append(item)
    total=len(vectors);complete_vectors=sum(v['complete'] for v in vectors)
    all_known=complete_vectors==total and total>0
    pass_any=sum(any(v is True for v in row['outcomes']) for row in vectors)
    pass_all=sum(row['complete'] and all(row['outcomes']) for row in vectors)
    groups=[group(baseline,'Fixed baseline'),group(first,'Agent repeat 1')]
    candidates=actor_usage(records,'candidate');judges=actor_usage(records,'judge')
    all_grades=all(known_pass(r) is not None for r in records)
    nothing=all(r['state']=='pending' for r in records)
    status='planned_only' if nothing else 'complete' if all_grades else 'incomplete'
    if all_grades and (not candidates['usage_complete'] or not judges['usage_complete'] or not candidates['cost_complete'] or not judges['cost_complete']):
        status='complete_with_measurement_gaps'
    return {'schema_version':'h4-summary-v1','generated_at':timestamp(),'experiment_id':plan['experiment_id'],
        'plan_hash':plan['plan_hash'],'split':plan['split'],'execution_mode':plan['execution_mode'],
        'result_kind':'offline_fixture_not_benchmark' if plan['execution_mode']!='live_model' else 'candidate_evaluation',
        'status':status,'scheduled_executions':len(records),'terminal_records':sum(r['state']=='terminal' for r in records),
        'fingerprint':plan['fingerprint'],'comparison':groups,'pooled_agent':group(agent,'Agent all three repeats (pooled)'),
        'stability':{'scheduled_tasks':total,'complete_vectors':complete_vectors,
            'pass_at_3':pass_any/total if all_known else None,'pass_all_3':pass_all/total if all_known else None,
            'observed_pass_at_3_lower_bound':pass_any/total if complete_vectors or pass_any else None,
            'flip_tasks':flips,'vectors':vectors,'final':all_known},
        'candidate_usage':candidates,'judge_usage':judges,
        'unresolved_runs':[{'run_id':r['run_id'],'state':r['state'],'grade_status':(r['grade'] or {}).get('status')} for r in records if known_pass(r) is None],
        'metric_notes':{'accuracy':'Final only after all scheduled outcomes in the row are known; provisional passed/scheduled is separately labelled.',
            'turns':'All candidate model calls, including setup and profile interpretation.',
            'p95':'Nearest-rank over all scheduled candidate latencies, including failed/timed-out tasks; null if any missing.',
            'tokens':'Input plus output; cached input is a subset, not added twice; unknown is never zero-filled.',
            'stability':'Exactly three predesignated repeats; mixed complete vectors form the flip list.'}}


def format_value(value):
    if value is None:return 'N/A'
    if isinstance(value,float):return f'{value:.6g}'
    return str(value)


def markdown(summary):
    rows=['# Evaluation results','',
        '**OFFLINE FIXTURE — NOT A MODEL BENCHMARK.**' if summary['execution_mode']!='live_model' else 'Saved candidate evaluation; review completeness before submission.',
        '',f"Status: {summary['status']}. Experiment: {summary['experiment_id']}.",
        '','| Strategy | Scheduled | Pass / fail / unresolved | Accuracy | Avg turns | Avg latency (ms) | p95 latency (ms) | Avg tokens |',
        '| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for row in summary['comparison']:
        values=[row['label'],row['scheduled'],f"{row['passed']} / {row['failed']} / {row['unresolved']}",
            row['accuracy'],row['avg_turns'],row['avg_latency_ms'],row['p95_latency_ms'],row['avg_tokens']]
        rows.append('| '+' | '.join(format_value(v) for v in values)+' |')
    s=summary['stability']
    rows.extend(['',f"pass@3: {format_value(s['pass_at_3'])}; pass^3: {format_value(s['pass_all_3'])}. Complete vectors: {s['complete_vectors']}/{s['scheduled_tasks']}.",
        f"Flip task IDs: {', '.join(v['task_id'] for v in s['flip_tasks']) or 'None among complete vectors'}.",
        '',f"Candidate known requests: {summary['candidate_usage']['known_actual_requests']}; judge known requests: {summary['judge_usage']['known_actual_requests']}.",
        '', 'Unknown metrics are N/A. Candidate and judge costs/usage are separate in summary.json. Incomplete reports are not final benchmark scores.'])
    return '\n'.join(rows)+'\n'


def write_reports(summary,path):
    path=Path(path);path.mkdir(parents=True,exist_ok=False)
    write_new(path/'summary.json',summary)
    write_new(path/'flip_tasks.json',summary['stability']['flip_tasks'])
    write_new(path/'repeat_vectors.json',summary['stability']['vectors'])
    with (path/'results.md').open('x',encoding='utf-8',newline='\n') as stream:stream.write(markdown(summary))
    fields=['label','scheduled','passed','failed','unresolved','grading_errors','interrupted_unknown',
        'accuracy','accuracy_final','pass_fraction_of_scheduled','provisional_fraction',
        'avg_turns','avg_latency_ms','p95_latency_ms','avg_tokens','tokens_known_count','tokens_unknown_count']
    with (path/'results.csv').open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
        writer.writeheader();writer.writerows(summary['comparison'])
    return path
