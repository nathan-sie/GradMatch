"""Bounded H2 development smoke only; no grades, judges or formal tasks."""
import argparse
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from uuid import uuid4
from gradmatch.homework.dataset import load_candidate_inputs
from gradmatch.homework.engine import CandidateRun
from gradmatch.homework.runtime import load_runtime
from gradmatch.storage import PROJECT_ROOT
from scripts.homework.run_task import save_result


def inspect_results(results):
    agent, baseline, followup = results
    actions = [s for s in agent['trace']['spans'] if s['kind']=='tool']
    first_missing = bool(actions and actions[0]['name']=='get_evidence'
        and (actions[0]['outputs'] or {}).get('error',{}).get('code')=='not_found')
    recovered = any(s['selected_by']=='model' and (s['outputs'] or {}).get('ok') for s in actions[1:])
    before,after = deepcopy(followup['profile_before']),deepcopy(followup['profile_after'])
    before.pop('goal');before.pop('profile_version')
    goal = after.pop('goal');version = after.pop('profile_version')
    return {'all_executions_completed':all(r['status']=='completed' for r in results),
        'agent_missing_source_observed':first_missing,'agent_selected_different_action':recovered,
        'agent_answer_contains_50850':bool(agent['answer'] and '50850' in agent['answer']['answer'].replace(',','')),
        'baseline_answer_contains_61504':bool(baseline['answer'] and '61504' in baseline['answer']['answer'].replace(',','')),
        'goal_changed_to_mixed_only':goal=='mixed' and version==2 and before==after,
        'all_live_usage_measured':all(r['usage_complete'] for r in results),
        'traces_complete':all(s['finished_at'] and s['status']!='running' for r in results for s in r['trace']['spans'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-model',action='store_true',required=True)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--resume',action='store_true',help='Keep every saved attempt and continue the same bounded smoke.')
    args=parser.parse_args()
    output=args.output_dir or PROJECT_ROOT/'work/h2'/('smoke-'+str(uuid4()))
    output.mkdir(parents=True,exist_ok=args.resume)
    runtime=load_runtime(live_model=True)
    candidates=load_candidate_inputs(PROJECT_ROOT/'homework/dev_tasks.jsonl',date.fromisoformat(runtime.manifest['assessment_date']))
    dev={c.task_id:c for c in candidates}
    diagnostic=dev['d01'].model_copy(deep=True)
    diagnostic.task_id='h2-observation-recovery'
    diagnostic.question=("Diagnostic tool-recovery check: first try get_evidence for source ID h2-missing-evidence-001. "
        "If it does not exist, inspect the frozen UW Seattle ECE PMP program instead and answer: what is its "
        "full-degree published-rate tuition estimate in USD? Cite the actual source, show the multiplication, "
        "and distinguish tuition from living costs. Do not claim the missing source exists.")
    results=[]
    for strategy,c in [('react',diagnostic),('fixed',dev['d08']),('fixed',dev['d07'])]:
        path=output/f"{len(results)+1:02d}-{strategy}-{c.task_id}.json"
        if args.resume and path.exists():
            result=json.loads(path.read_text(encoding='utf-8'))
            if result['configuration']['candidate_code_hash']!=runtime.code_hash:
                raise RuntimeError('Candidate code changed. Keep the old smoke and start a new labelled attempt.')
            results.append(result)
            continue
        remaining=12-sum(r['actual_requests'] for r in results)
        if remaining<=0:raise RuntimeError('The smoke request ceiling was reached; saved attempts were retained.')
        local=deepcopy(runtime)
        local.manifest['candidate_limits']['max_model_calls_per_task']=min(remaining,8)
        result=CandidateRun(local,c,strategy).run()
        results.append(result)
        save_result(result,path)
        print(json.dumps({k:result[k] for k in ['task_id','strategy','status','actual_requests','estimated_cost_usd']}),flush=True)
    checks=inspect_results(results)
    report={'checkpoint':'H2','purpose':'bounded_development_smoke_not_benchmark','checks':checks,
        'status':'passed' if all(checks.values()) else 'failed','actual_requests':sum(r['actual_requests'] for r in results),
        'input_tokens':sum(u['input_tokens'] or 0 for r in results for u in r['usage']),
        'output_tokens':sum(u['output_tokens'] or 0 for r in results for u in r['usage']),
        'estimated_cost_usd':str(sum(Decimal(r['estimated_cost_usd'] or '0') for r in results)),
        'cost_is_partial':any(r['estimated_cost_usd'] is None for r in results),
        'trace_ids':[r['trace_id'] for r in results],'formal_evaluation':'not_run'}
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
