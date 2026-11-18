"""Verify ZIP bytes and optionally run isolated offline checks on a fresh extraction."""
import argparse
import json
import os
from pathlib import Path,PurePosixPath
import subprocess
import sys
from uuid import uuid4
import zipfile
from gradmatch.homework.submission import PACKAGE_NAME,safe_relative,sha,verify_payloads


PROBE = r'''
import contextlib,io,json,socket,sys
from pathlib import Path
def deny(*args,**kwargs):raise AssertionError('Submission checks must not make network/model requests.')
socket.socket.connect=deny
socket.create_connection=deny
from gradmatch.storage import PROJECT_ROOT
assert PROJECT_ROOT==Path.cwd()
from gradmatch.config import load_settings
assert not load_settings().ready and not (PROJECT_ROOT/'.env').exists()
assert not (PROJECT_ROOT/'data/gradmatch.db').exists()
from gradmatch.homework.provider import HomeworkProvider
from gradmatch.homework.judging import JudgeProvider
HomeworkProvider.invoke=deny
JudgeProvider.invoke=deny
from gradmatch.homework.validation import validate_bundle
assert validate_bundle()['formal']['tasks']==50
from gradmatch.homework.experiment import ExperimentStore
from gradmatch.homework.experiment import fingerprint,load_inputs
from gradmatch.homework.metrics import summarize
original=json.loads((PROJECT_ROOT/'results.json').read_text(encoding='utf-8'))
context,_,_,_=load_inputs()
assert fingerprint(context)==original['fingerprint']
recomputed=summarize(ExperimentStore(PROJECT_ROOT/'docs/verification/h5/formal'))
for key in ['comparison','pooled_agent','stability','candidate_usage','judge_usage','fingerprint']:
    assert recomputed[key]==original[key],key
from scripts.homework.evaluate import main
capture=io.StringIO()
sys.argv=['eval.py','--dry-run','--experiment-dir','work/unpacked-check-plan']
with contextlib.redirect_stdout(capture):assert main()==0
plan=json.loads(capture.getvalue())
assert plan['scheduled_executions']==200 and plan['baseline_executions']==50 and plan['agent_executions']==150
assert plan['candidate_requests']==plan['judge_requests']==0
assert not (PROJECT_ROOT/'work/unpacked-check-plan/entries').exists()
from scripts.homework.summarize import main as summary_main
capture=io.StringIO()
sys.argv=['summarize','--experiment-dir','docs/verification/h5/formal','--output-dir','work/unpacked-recomputed']
with contextlib.redirect_stdout(capture):assert summary_main()==0
assert json.loads(capture.getvalue())['model_requests_made_by_summary']==0
print(json.dumps({'status':'passed','fresh_root':True,'key_ready':False,'sqlite_absent':True,'source_fingerprint_match':True,
    'frozen_tasks':50,'formal_records':200,'metrics_match':True,'dry_schedule':200,
    'candidate_requests':0,'judge_requests':0,'network_guarded':True}))
'''


def read_archive(archive):
    payloads={}
    with zipfile.ZipFile(archive) as stream:
        if stream.testzip() is not None:raise ValueError('ZIP CRC check failed.')
        seen=set()
        for item in stream.infolist():
            safe_relative(item.filename)
            path=PurePosixPath(item.filename)
            if path.parts[0]!=PACKAGE_NAME or len(path.parts)<2 or item.is_dir():
                raise ValueError('Unexpected archive member layout.')
            if (item.external_attr>>16)&0o170000==0o120000:raise ValueError('Symbolic links are not supported.')
            name=PurePosixPath(*path.parts[1:]).as_posix()
            if name in seen:raise ValueError('Duplicate ZIP member.')
            seen.add(name);payloads[name]=stream.read(item)
    return payloads


def verify(archive,*,extract_dir=None):
    archive=Path(archive)
    payloads=read_archive(archive)
    report=verify_payloads(payloads)
    report.update(archive_sha256=sha(archive.read_bytes()),archive_bytes=archive.stat().st_size)
    if extract_dir is not None:
        destination=Path(extract_dir).resolve()
        destination.mkdir(parents=True,exist_ok=False)
        with zipfile.ZipFile(archive) as stream:
            for item in stream.infolist():
                target=(destination/item.filename).resolve()
                if not target.is_relative_to(destination):raise ValueError('Extraction escaped the destination.')
            stream.extractall(destination)
        root=destination/PACKAGE_NAME
        env=dict(os.environ)
        for key in ['OPENAI_API_KEY','MODEL_API_KEY','MODEL_ENABLED','MODEL_NAME','MODEL_PROVIDER','PYTHONPATH']:
            env.pop(key,None)
        checked=subprocess.run([sys.executable,'-c',PROBE],cwd=root,env=env,
            capture_output=True,text=True,encoding='utf-8',timeout=180)
        if checked.returncode!=0:
            raise ValueError('Fresh offline source/metrics/CLI verification failed; no live calls were enabled.')
        report['offline_extraction']=json.loads(checked.stdout.strip().splitlines()[-1])
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--extract-check',type=Path)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    report=verify(args.archive,extract_dir=args.extract_check)
    if args.report:
        with args.report.open('x',encoding='utf-8',newline='\n') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
