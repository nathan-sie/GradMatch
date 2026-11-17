"""Run one ungraded H2 candidate, saving actual actions and failures as JSON."""
import argparse
from datetime import date
import json
from pathlib import Path
from gradmatch.config import ConfigurationError
from gradmatch.homework.contracts import CandidateInput
from gradmatch.homework.dataset import load_candidate_inputs
from gradmatch.homework.engine import CandidateRun
from gradmatch.homework.runtime import load_runtime
from gradmatch.storage import PROJECT_ROOT


def save_result(result, path=None):
    path = path or PROJECT_ROOT/'work/h2'/f"{result['strategy']}-{result['task_id']}-{result['trace_id']}.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--strategy',required=True,choices=['fixed','react'])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--task-id',choices=[f'd{i:02d}' for i in range(1,9)])
    source.add_argument('--input',type=Path,help='CandidateInput JSON containing user fields only.')
    parser.add_argument('--live-model',action='store_true',help='Explicitly enable metered real-model calls.')
    parser.add_argument('--output',type=Path,help='New JSON file; existing results are never overwritten.')
    args = parser.parse_args()
    if args.output and args.output.exists():parser.error('The output file already exists. Choose a new path.')
    try:
        runtime = load_runtime(live_model=args.live_model)
        if args.input:candidate = CandidateInput.model_validate_json(args.input.read_text(encoding='utf-8'))
        else:
            candidates = load_candidate_inputs(PROJECT_ROOT/'homework/dev_tasks.jsonl',
                date.fromisoformat(runtime.manifest['assessment_date']))
            candidate = next(c for c in candidates if c.task_id==args.task_id)
        result = CandidateRun(runtime,candidate,args.strategy).run()
        path = save_result(result,args.output)
    except (ConfigurationError,ValueError,OSError):
        print('Configuration/input/output validation failed. Check the frozen files and use a new output path.')
        return 2
    print(json.dumps({k:result[k] for k in ['task_id','strategy','trace_id','status','model_calls',
        'tool_calls','actual_requests','latency_ms','estimated_cost_usd']} | {'saved_to':str(path)},indent=2))
    if result['answer']:print(result['answer']['answer'])
    return 0 if result['status']=='completed' else 1


if __name__=='__main__':raise SystemExit(main())
