"""Bounded H3 judge calibration and grading of two saved H2 development runs."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal
import json
from pathlib import Path
from uuid import uuid4
from gradmatch.homework.calibration import calibration_sources,fixture_result,load_cases
from gradmatch.homework.dataset import EvalTask,Reference,read_jsonl
from gradmatch.homework.graders import (build_judge_package,deterministic_checks,grade,
    load_grading_context,validate_verdict)
from gradmatch.homework.judging import JudgeFailure,JudgeProvider
from gradmatch.storage import PROJECT_ROOT


def save(path,record):
    with path.open('x',encoding='utf-8',newline='\n') as stream:stream.write(json.dumps(record,indent=2,ensure_ascii=False)+'\n')


def agreement(rows,prediction,label):
    eligible=[r for r in rows if r[label] in ('pass','fail')]
    evaluated=[r for r in eligible if r[prediction] is not None]
    matched=sum(r[prediction]==(r[label]=='pass') for r in evaluated)
    return {'labelled':len(eligible),'evaluated':len(evaluated),'agreement_count':matched,
        'agreement_rate':matched/len(evaluated) if evaluated else None,
        'excluded_skipped_labels':sum(r[label]=='skip' for r in rows),
        'error_or_ungraded_count':len(eligible)-len(evaluated)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live-judge',action='store_true',required=True)
    parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    context=load_grading_context(live_model=True)
    output=args.output_dir or PROJECT_ROOT/'work/h3'/('calibration-'+str(uuid4()))
    output.mkdir(parents=True,exist_ok=args.resume)
    tasks={t.id:t for t in read_jsonl(PROJECT_ROOT/'homework/dev_tasks.jsonl',EvalTask)}
    refs={r.task_id:r for r in read_jsonl(PROJECT_ROOT/'homework/dev_references.jsonl',Reference)}
    cases=load_cases(PROJECT_ROOT/'homework/calibration_cases.jsonl')
    judge=JudgeProvider(context)
    records=[]
    for case in cases:
        path=output/f"case-{case['case_id']}.json"
        if args.resume and path.exists():
            record=json.loads(path.read_text(encoding='utf-8'))
            if record['grader_hash']!=context.grader_hash:raise ValueError('Changed grader: preserve old records and label a new attempt.')
        else:
            task,ref=tasks[case['task_id']],refs[case['task_id']]
            result=fixture_result(task,case['answer'],calibration_sources(task,ref,context),context)
            view,checks=deterministic_checks(task,ref,result,context)
            package=build_judge_package(task,ref,view,context)
            record={'purpose':'authored_calibration_semantic_probe_not_candidate_benchmark',
                'case_id':case['case_id'],'grader_hash':context.grader_hash,
                'human_label':case['human_label'],'author_expected_pass':case['author_expected_pass'],
                'candidate_fixture':result,'code_checks':checks,'criteria':[],
                'semantic_passed':None,'combined_passed':None,'judge_record':None,'error':None}
            try:
                verdict,request=judge.invoke(package)
                record['judge_record']=request
                record['criteria']=validate_verdict(verdict,package)
                record['semantic_passed']=all(c['passed'] for c in record['criteria'])
                record['combined_passed']=all(c['passed'] for c in checks) and record['semantic_passed']
            except JudgeFailure as error:
                record.update(judge_record=error.record,error={'code':error.code})
            except ValueError:
                record['error']={'code':'invalid_judge_evidence'}
            save(path,record)
        records.append(record)
        print(json.dumps({'case_id':record['case_id'],'human_label':record['human_label'],
            'semantic_passed':record['semantic_passed'],'combined_passed':record['combined_passed'],'error':record['error']}),flush=True)
    for filename in ['02-fixed-d08.json','03-fixed-d07.json']:
        path=output/f"grade-{filename}"
        if args.resume and path.exists():
            record=json.loads(path.read_text(encoding='utf-8'))
            if record['grader_hash']!=context.grader_hash:raise ValueError('Changed grader revision.')
        else:
            result=json.loads((PROJECT_ROOT/'docs/verification/h2'/filename).read_text(encoding='utf-8'))
            record=grade(tasks[result['task_id']],refs[result['task_id']],result,context,judge=judge)
            save(path,record)
        records.append(record)
        print(json.dumps({'task_id':record['task_id'],'status':record['status'],'passed':record['passed']}),flush=True)
    usages=[r['judge_record']['usage'] for r in records if r.get('judge_record')]
    actual=sum(u['actual_request'] for u in usages)
    assert actual<=8,'H3 acceptance has at most eight requests and no automatic retries.'
    calibration=records[:6]
    summary={'checkpoint':'H3','verified_at':datetime.now(timezone.utc).isoformat(),
        'grader_hash':context.grader_hash,'calibration_cases':6,
        'human_review':'Five binary user labels, one user-skipped incomplete answer; presented in Chinese with the same facts and meaning as the English fixtures.',
        'semantic_judge_vs_human':agreement(calibration,'semantic_passed','human_label'),
        'combined_pipeline_vs_human':agreement(calibration,'combined_passed','human_label'),
        'authored_fixture_agreement':{'matched':sum(r['combined_passed']==r['author_expected_pass'] for r in calibration),
            'total':len(calibration),'not_human_agreement':True},
        'actual_judge_requests':actual,'new_candidate_requests':0,
        'judge_model':context.config['judge_model'],'same_model_family_limitation':context.config['model_family_limitation'],
        'judge_input_tokens':sum(u['input_tokens'] or 0 for u in usages),
        'judge_output_tokens':sum(u['output_tokens'] or 0 for u in usages),
        'usage_complete':all(u['input_tokens'] is not None and u['output_tokens'] is not None for u in usages),
        'estimated_judge_cost_usd':str(sum(Decimal(u['estimated_cost_usd'] or '0') for u in usages)),
        'cost_is_partial':any(u['estimated_cost_usd'] is None for u in usages),
        'existing_development_grades':[{'task_id':r['task_id'],'status':r['status'],'passed':r['passed']} for r in records[6:]],
        'formal_evaluation':'not_run'}
    # Preserve a prior summary on resume rather than overwrite it.
    summary_path=output/'summary.json'
    if not summary_path.exists():save(summary_path,summary)
    print(json.dumps(summary,indent=2),flush=True)
    return 0 if all(r.get('error') is None for r in records) and all(r['combined_passed']==r['author_expected_pass'] for r in calibration) else 1


if __name__=='__main__':raise SystemExit(main())
