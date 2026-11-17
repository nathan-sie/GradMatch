"""Grade one saved candidate record; no candidate execution or formal scheduling."""
import argparse
import json
from pathlib import Path
from gradmatch.config import ConfigurationError
from gradmatch.homework.dataset import EvalTask, Reference, read_jsonl
from gradmatch.homework.graders import grade, load_grading_context
from gradmatch.homework.judging import JudgeProvider
from gradmatch.storage import PROJECT_ROOT


def save_grade(record,path=None):
    path=path or PROJECT_ROOT/'work/h3'/f"grade-{record['grade_id']}.json"
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:stream.write(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--split',choices=['development','formal'],default='development')
    parser.add_argument('--live-judge',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.output and args.output.exists():parser.error('Choose a new output file; existing grading records are preserved.')
    try:
        context=load_grading_context(live_model=args.live_judge)
        result=json.loads(args.run.read_text(encoding='utf-8'))
        prefix='dev_' if args.split=='development' else ''
        tasks={t.id:t for t in read_jsonl(PROJECT_ROOT/f'homework/{prefix}tasks.jsonl',EvalTask)}
        refs={r.task_id:r for r in read_jsonl(PROJECT_ROOT/f'homework/{prefix}references.jsonl',Reference)}
        task_id=result['task_id']
        record=grade(tasks[task_id],refs[task_id],result,context,
            judge=JudgeProvider(context) if args.live_judge else None)
        path=save_grade(record,args.output)
    except (ConfigurationError,ValueError,KeyError,OSError):
        print('Could not validate the grading configuration, input or output path.')
        return 2
    print(json.dumps({'task_id':task_id,'grade_id':record['grade_id'],'status':record['status'],
        'passed':record['passed'],'saved_to':str(path)},indent=2))
    return 0 if record['status']=='passed' else 1 if record['status']=='failed' else 3


if __name__=='__main__':raise SystemExit(main())
