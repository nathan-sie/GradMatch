"""Prepare the frozen schedule, or explicitly execute/resume candidate and judge stages."""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from gradmatch.config import ConfigurationError
from gradmatch.homework.experiment import ExperimentStore,execute,load_inputs,make_plan
from gradmatch.homework.metrics import summarize,write_reports
from gradmatch.storage import PROJECT_ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks',type=Path)
    parser.add_argument('--task-ids',nargs='+',help='Development subset only; formal experiments use all 50.')
    parser.add_argument('--agent-repeats',type=int,choices=[3],default=3)
    parser.add_argument('--experiment-dir',type=Path)
    parser.add_argument('--dry-run',action='store_true',help='Default: save schedule only; zero model/judge requests.')
    parser.add_argument('--live-model',action='store_true',help='Explicitly execute BOTH candidate and required judge calls.')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--max-runs',type=int,help='Stop between scheduled runs, retaining the complete original schedule.')
    parser.add_argument('--recover-lock',action='store_true',help='Recover only a verified dead local writer lock.')
    args=parser.parse_args()
    if args.dry_run and args.live_model:parser.error('Choose dry-run or live execution.')
    if (args.resume or args.recover_lock) and not args.experiment_dir:parser.error('Resume/recovery requires the original experiment directory.')
    if args.recover_lock and not (args.resume and args.live_model):parser.error('Lock recovery requires explicit live resume.')
    if args.max_runs is not None and (not args.live_model or args.max_runs<1):parser.error('A positive max-runs requires live execution.')
    try:
        if args.resume:
            store=ExperimentStore(args.experiment_dir)
            tasks_path=args.tasks or PROJECT_ROOT/('homework/tasks.jsonl' if store.plan['split']=='formal' else 'homework/dev_tasks.jsonl')
            context,tasks,refs,split=load_inputs(tasks_path,live_model=args.live_model)
            if split!=store.plan['split'] or (args.task_ids is not None and set(args.task_ids)!=set(store.plan['task_ids'])):
                raise ValueError('Resume must keep the same task selection.')
        else:
            context,tasks,refs,split=load_inputs(args.tasks,live_model=args.live_model)
            plan=make_plan(context,tasks,split,task_ids=args.task_ids)
            directory=args.experiment_dir or PROJECT_ROOT/'work/evaluations'/plan['experiment_id']
            store=ExperimentStore.create(directory,plan)
        if not args.live_model:
            print(json.dumps({'status':'planned_only','experiment_id':store.plan['experiment_id'],
                'experiment_dir':str(store.path),'split':store.plan['split'],
                'scheduled_executions':len(store.plan['schedule']),
                'baseline_executions':sum(e['strategy']=='fixed' for e in store.plan['schedule']),
                'agent_executions':sum(e['strategy']=='react' for e in store.plan['schedule']),
                'candidate_requests':0,'judge_requests':0,'benchmark_scores':'not_computed'},indent=2))
            return 0
        def progress(stage,entry):
            if stage=='grade_saved':print(json.dumps({'run_id':entry['run_id'],'stage':stage}),flush=True)
        execute(store,context,tasks,refs,max_runs=args.max_runs,recover_lock=args.recover_lock,on_event=progress)
        result=summarize(store)
        output=write_reports(result,store.path/'reports'/str(uuid4()))
        print(json.dumps({'status':result['status'],'report_dir':str(output),
            'terminal_records':result['terminal_records'],'scheduled_executions':result['scheduled_executions'],
            'candidate_usage':result['candidate_usage'],'judge_usage':result['judge_usage']},indent=2))
        return 0 if result['status'].startswith('complete') else 1
    except (ConfigurationError,ValueError,KeyError,TypeError,OSError):
        print('Experiment validation failed. Existing evidence was preserved; check the frozen revision, paths and writer ownership.')
        return 2


if __name__=='__main__':raise SystemExit(main())
