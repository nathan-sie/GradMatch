"""H6 submission inventory, byte integrity and selected formal-failure evidence."""
from collections import Counter
from datetime import date
import hashlib
import json
from pathlib import Path,PurePosixPath
import re
from gradmatch.config import load_settings
from gradmatch.homework.contracts import CandidateInput,TOOL_ARGUMENTS
from gradmatch.homework.dataset import EvalTask,Reference,read_jsonl
from gradmatch.homework.experiment import ExperimentStore
from gradmatch.homework.graders import digest
from gradmatch.homework.metrics import summarize
from gradmatch.storage import PROJECT_ROOT

RUN_ID='t26--react--r2'
PACKAGE_NAME='GradMatch_Eval_Homework'
PRIVATE_PARTS={'.git','.venv','.tools','work','runs','__pycache__','.pytest_cache'}
EXTENSIONS={'.py','.json','.jsonl','.md','.csv','.sql','.toml','.lock'}
FOLDERS=['gradmatch','scripts','tests','config','data/catalog','data/snapshots','docs/verification','homework']
ROOT_FILES=['app.py','pyproject.toml','uv.lock','.python-version','.gitignore','.gitattributes','.env.example',
    '.streamlit/config.toml','data/schema.sql','AGENTS.md','docs/HOMEWORK_EVAL_PLAN.md']
EXTERNAL_RECEIPTS={'docs/verification/h6/verification.json'}


def sha(payload):return hashlib.sha256(payload).hexdigest()


def safe_relative(name):
    path=PurePosixPath(name)
    if not name or not path.parts or name!=path.as_posix() or '\\' in name or path.is_absolute() or '..' in path.parts or ':' in name:
        raise ValueError('Unsafe archive path.')
    return path


def selected_failure(root=PROJECT_ROOT):
    store=ExperimentStore(root/'docs/verification/h5/formal')
    entry=next(e for e in store.plan['schedule'] if e['run_id']==RUN_ID)
    record=store.read_run(entry)
    task=next(t for t in read_jsonl(root/'homework/tasks.jsonl',EvalTask) if t.id=='t26')
    reference=next(r for r in read_jsonl(root/'homework/references.jsonl',Reference) if r.task_id=='t26')
    candidate,grading=record['candidate'],record['grade']
    tools=[s for s in candidate['trace']['spans'] if s['kind']=='tool']
    assert candidate['status']=='completed' and grading['status']=='failed' and grading['passed'] is False
    assert len(tools)==2 and all(s['outputs']['ok'] for s in tools)
    first={'name':tools[0]['name'],'arguments':tools[0]['inputs']['arguments']}
    expected=task.expected_call.model_dump(mode='json')
    second={'name':tools[1]['name'],'arguments':tools[1]['inputs']['arguments']}
    assert first=={'name':'get_program','arguments':{'program_id':'uci-mcs-irvine'}}
    assert expected==second=={'name':'check_program','arguments':{'program_id':'uci-mcs-irvine','profile_version':1}}
    assert [c['criterion_id'] for c in grading['code_checks'] if not c['passed']]==['first_tool_call']
    assert grading['judge_record'] is None
    model=next(s for s in candidate['trace']['spans'] if s['span_id']==tools[0]['parent_id'])
    assert model['kind']=='model' and model['outputs']['calls'][0]['name']=='get_program'
    assert any(s['kind']=='validation' and s['outputs']['accepted'] for s in candidate['trace']['spans'])
    english=next(c for c in tools[1]['outputs']['report']['checks'] if c['rule_id']=='english')
    assert english['status']=='fail' and candidate['profile_after']==candidate['profile_before']
    vector=next(v for v in summarize(store)['stability']['vectors'] if v['task_id']=='t26')['outcomes']
    assert vector==[True,False,True]
    return {'experiment_id':store.plan['experiment_id'],'plan_hash':store.plan['plan_hash'],
        'run_id':RUN_ID,'task_id':task.id,'task_type':task.type,'trace_id':candidate['trace_id'],
        'first_model_span_id':model['span_id'],'first_tool_span_id':tools[0]['span_id'],
        'second_tool_span_id':tools[1]['span_id'],'expected_first_call':expected,'actual_first_call':first,
        'later_call':second,'tool_failures':0,'first_tool_check':False,'final_answer_validated':True,
        'english_check':english,'repeat_vector':vector,'candidate_model_calls':candidate['model_calls'],
        'candidate_tool_calls':candidate['tool_calls'],'candidate_record_sha256':digest(candidate),
        'grade_record_sha256':digest(grading),'failure_class':'model_action_order',
        'fix_applied_to_frozen_experiment':False,
        'candidate_path':f'docs/verification/h5/formal/entries/{RUN_ID}/candidate.json',
        'grade_path':f'docs/verification/h5/formal/entries/{RUN_ID}/grade.json'}


def regression_fixture(root=PROJECT_ROOT):
    task=next(t for t in read_jsonl(root/'homework/tasks.jsonl',EvalTask) if t.id=='t26')
    profile=task.profile.model_copy(deep=True);profile.profile_version=3
    value=CandidateInput(task_id='regression_direct_check_first_v3',
        question='Run the program checks for uci-mcs-irvine against my supplied current profile version 3. Inspect my declared IELTS module scores, without substituting the overall score.',
        profile=profile,program_ids=['uci-mcs-irvine'],setup_messages=[],as_of_date=date(2026,11,16))
    expected={'name':'check_program','arguments':{'program_id':'uci-mcs-irvine','profile_version':3}}
    TOOL_ARGUMENTS[expected['name']].model_validate(expected['arguments'])
    return value.model_dump(mode='json'),{'scope':'future_development_regression_only',
        'derived_from':RUN_ID,'expected_first_call':expected,'not_in_formal_task_set':True,
        'fix_status':'proposed, not implemented or model-tested in H6',
        'reason':'Honor an explicit direct-check request before discretionary program lookup; preserve declared module scores and current version.'}


def allowed_files(root):
    root=Path(root).resolve();found=set()
    for folder in FOLDERS:
        directory=root/folder
        if not directory.is_dir():raise ValueError('A required source/data directory is missing.')
        for path in directory.rglob('*'):
            if not path.is_file() or path.suffix not in EXTENSIONS:continue
            rel=path.relative_to(root)
            # The final archive receipt includes the archive hash and cannot include itself.
            if rel.as_posix() in EXTERNAL_RECEIPTS:continue
            if PRIVATE_PARTS & set(rel.parts):continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Source must be a regular file inside the package root.')
            if rel.name.startswith('.env') or rel.name in {'secrets.toml','gradmatch.db'}:continue
            found.add(rel.as_posix())
    for name in ROOT_FILES:
        path=root/name
        if not path.is_file() or path.is_symlink():raise ValueError('A required root file is missing.')
        found.add(name)
    return sorted(found)


def scan_payloads(payloads,*,known_key=b''):
    for name,payload in payloads.items():
        safe_relative(name)
        parts=PurePosixPath(name).parts
        if PRIVATE_PARTS & set(parts):raise ValueError('Runtime/private directory in submission.')
        if PurePosixPath(name).name in {'.env','secrets.toml','gradmatch.db'}:
            raise ValueError('Private configuration/database in submission.')
        if len(known_key)>=10 and known_key in payload:
            raise ValueError('Configured credential detected; no value was printed.')
        if re.search(rb'sk-(?:proj-)?[A-Za-z0-9_-]{32,}',payload):
            raise ValueError('Possible API credential detected; no value was printed.')


def package_payloads(root=PROJECT_ROOT):
    root=Path(root)
    payloads={name:(root/name).read_bytes() for name in allowed_files(root)}
    mapping={'tasks.jsonl':'homework/tasks.jsonl','report.pdf':'output/pdf/GradMatch_Eval_Report.pdf',
        'results.csv':'docs/verification/h5/results/results.csv','results.json':'docs/verification/h5/results/summary.json',
        'results.md':'docs/verification/h5/results/results.md','flip_tasks.json':'docs/verification/h5/results/flip_tasks.json',
        'repeat_vectors.json':'docs/verification/h5/results/repeat_vectors.json'}
    for name,source in mapping.items():
        path=root/source
        if name=='report.pdf' and not path.exists():path=root/'report.pdf'
        payloads[name]=path.read_bytes()
    for name,source in [('report.md','homework/FINAL_REPORT.md'),('failure_analysis.md','homework/FAILURE_ANALYSIS.md')]:
        # Root copies have the same prose, with repository-relative links adjusted one level.
        payloads[name]=(root/source).read_text(encoding='utf-8').replace('](../','](').encode()
    payloads['README.md']=(root/'homework/SUBMISSION_README.md').read_bytes()
    payloads['eval.py']=b'"""Run the frozen candidate/baseline evaluation CLI; defaults to no-cost planning."""\nfrom scripts.homework.evaluate import main\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
    scan_payloads(payloads,known_key=load_settings(root).api_key.encode())
    required={'tasks.jsonl','eval.py','report.pdf','report.md','failure_analysis.md','results.csv','flip_tasks.json',
        'homework/references.jsonl','homework/formal_freeze.json','docs/verification/h6/failure_case.json'}
    if not required<=set(payloads):raise ValueError('Submission checklist is incomplete.')
    manifest={'schema_version':'h6-submission-v1','package':PACKAGE_NAME,'manifest_scope':'Every member except this manifest itself.',
        'files':[{'path':name,'sha256':sha(data),'bytes':len(data)} for name,data in sorted(payloads.items())]}
    payloads['submission_manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    return payloads


def verify_payloads(payloads):
    manifest=json.loads(payloads['submission_manifest.json'])
    entries=manifest['files']
    names=[e['path'] for e in entries]
    if len(names)!=len(set(names)) or set(names)!=(set(payloads)-{'submission_manifest.json'}):
        raise ValueError('Archive manifest members differ.')
    for entry in entries:
        safe_relative(entry['path']);raw=payloads[entry['path']]
        if sha(raw)!=entry['sha256'] or len(raw)!=entry['bytes']:raise ValueError('Submission member integrity failure.')
    scan_payloads(payloads)
    if payloads['tasks.jsonl']!=payloads['homework/tasks.jsonl']:raise ValueError('Root task copy differs from frozen tasks.')
    tasks=[json.loads(line) for line in payloads['tasks.jsonl'].decode('utf-8').splitlines()]
    counts=Counter(t['type'] for t in tasks)
    if len(tasks)!=50 or len({t['id'] for t in tasks})!=50 or counts!=dict(exact=18,tool=8,rubric=20,unanswerable=4):
        raise ValueError('Task coverage changed.')
    summary=json.loads(payloads['results.json'])
    if summary['terminal_records']!=200 or summary['status']!='complete':raise ValueError('Expected the complete actual comparison.')
    if [row['passed'] for row in summary['comparison']]!=[39,47]:raise ValueError('Results no longer match the frozen run.')
    if summary['stability']['pass_at_3']!=0.98 or summary['stability']['pass_all_3']!=0.76:raise ValueError('Stability results changed.')
    raw_count=sum(name.startswith('docs/verification/h5/formal/entries/') and name.endswith('/candidate.json') for name in payloads)
    if raw_count!=200:raise ValueError('The complete actual candidate evidence is required.')
    return {'status':'passed','members':len(payloads),'formal_tasks':50,'formal_executions':200,
        'raw_candidate_records':raw_count,
        'secrets':'no credentials or runtime database','results':'frozen values verified'}
