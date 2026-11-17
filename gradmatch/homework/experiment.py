"""H4 frozen schedules and append-only execution records; never candidate answer inputs."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from importlib.metadata import version
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
from uuid import uuid4
from gradmatch.homework.dataset import EvalTask, Reference, candidate_input, read_jsonl
from gradmatch.homework.engine import CandidateRun
from gradmatch.homework.graders import digest, grade, load_grading_context
from gradmatch.homework.judging import JudgeProvider
from gradmatch.homework.trace import timestamp
from gradmatch.homework.validation import validate_bundle
from gradmatch.storage import PROJECT_ROOT


def file_hash(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def runner_hash():
    paths=['gradmatch/homework/experiment.py','gradmatch/homework/metrics.py',
        'scripts/homework/evaluate.py','scripts/homework/summarize.py']
    return hashlib.sha256(''.join(p+file_hash(PROJECT_ROOT/p) for p in paths).encode()).hexdigest()


def load_inputs(tasks_path=None,*,live_model=False):
    validate_bundle()  # Evaluator preflight also verifies locked task/reference bytes.
    context=load_grading_context(live_model=live_model)
    path=Path(tasks_path or PROJECT_ROOT/'homework/tasks.jsonl').resolve()
    allowed={ (PROJECT_ROOT/'homework/tasks.jsonl').resolve():'formal',
        (PROJECT_ROOT/'homework/dev_tasks.jsonl').resolve():'development'}
    if path not in allowed:raise ValueError('Use one of the two frozen task sets.')
    split=allowed[path]
    ref_path=path.with_name('references.jsonl' if split=='formal' else 'dev_references.jsonl')
    tasks=read_jsonl(path,EvalTask);refs={r.task_id:r for r in read_jsonl(ref_path,Reference)}
    if not (PROJECT_ROOT/'homework/grader_freeze.json').is_file():raise ValueError('H3 grader freeze is required.')
    return context,tasks,refs,split


def fingerprint(context):
    return {'candidate_code_hash':context.runtime.code_hash,'grader_hash':context.grader_hash,
        'runner_hash':runner_hash(),'h1_manifest_sha256':file_hash(PROJECT_ROOT/'homework/experiment.json'),
        'frozen_files':context.runtime.manifest['files'],
        'catalog_data_hash':context.runtime.manifest['catalog_data_hash'],
        'grading_freeze_sha256':file_hash(PROJECT_ROOT/'homework/grader_freeze.json'),
        'app_config_sha256':file_hash(PROJECT_ROOT/'config/app.json'),
        'dependency_lock_sha256':file_hash(PROJECT_ROOT/'uv.lock'),
        'assessment_date':context.runtime.manifest['assessment_date'],'model':context.runtime.settings.model,
        'candidate_limits':context.runtime.manifest['candidate_limits'],
        'environment':{'python':sys.version.split()[0],'openai':version('openai'),'pydantic':version('pydantic')}}


def schedule_for(task_ids):
    schedule=[]
    for ordinal,task_id in enumerate(task_ids):
        variants=[('fixed',1),('react',1),('react',2),('react',3)]
        offset=ordinal%4
        for strategy,repeat in variants[offset:]+variants[:offset]:
            schedule.append({'sequence':len(schedule)+1,'task_id':task_id,'strategy':strategy,'repeat':repeat,
                'run_id':f'{task_id}--{strategy}--r{repeat}'})
    return schedule


def make_plan(context,tasks,split,*,task_ids=None,execution_mode='live_model'):
    ids=[t.id for t in tasks]
    if task_ids is not None:
        if len(set(task_ids))!=len(task_ids) or not set(task_ids)<=set(ids):raise ValueError('Unknown/duplicate task IDs.')
        if split=='formal' and set(task_ids)!=set(ids):raise ValueError('Formal experiments schedule all 50 tasks.')
        ids=[id for id in ids if id in task_ids]
    if not ids:raise ValueError('A schedule needs at least one task.')
    if execution_mode not in {'live_model','offline_test_double'}:raise ValueError('Unknown execution mode.')
    if split=='formal' and execution_mode!='live_model':raise ValueError('Fixtures cannot be formal experiments.')
    plan={'schema_version':'h4-v1','experiment_id':str(uuid4()),'created_at':timestamp(),
        'split':split,'execution_mode':execution_mode,'fingerprint':fingerprint(context),
        'task_ids':ids,'agent_repeats':3,'baseline_repeats':1,'metrics_version':'h4-v1',
        'schedule':schedule_for(ids),'initial_state':'planned_only'}
    plan['plan_hash']=digest(plan)
    return plan


def validate_plan(plan):
    copy=deepcopy(plan);actual=copy.pop('plan_hash')
    if digest(copy)!=actual:raise ValueError('Experiment manifest changed.')
    if plan['schema_version']!='h4-v1' or plan['metrics_version']!='h4-v1':raise ValueError('Unsupported experiment schema.')
    if plan['split'] not in {'formal','development'} or plan['execution_mode'] not in {'live_model','offline_test_double'}:raise ValueError('Invalid experiment mode.')
    ids=plan['task_ids']
    prefix='t' if plan['split']=='formal' else 'd'
    if not ids or len(ids)!=len(set(ids)) or any(not re.fullmatch(prefix+r'\d{2}',x) for x in ids):raise ValueError('Invalid scheduled IDs.')
    if plan['split']=='formal' and (ids!=[f't{i:02d}' for i in range(1,51)] or plan['execution_mode']!='live_model'):
        raise ValueError('Formal schedule must contain the 50 frozen tasks and live candidates.')
    if plan['agent_repeats']!=3 or plan['baseline_repeats']!=1 or plan['schedule']!=schedule_for(ids):raise ValueError('Scheduled repetitions changed.')
    return plan


def write_new(path,value):
    """Durable temporary file plus same-directory rename; caller owns the exclusive store lock."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise FileExistsError('Existing experiment evidence is never overwritten.')
    temp=path.with_name('.'+path.name+'.'+str(uuid4())+'.tmp')
    with temp.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
    # os.rename never replaces an existing destination on this Windows host.
    # Store locking and the second existence check also protect single-writer operation.
    if path.exists():raise FileExistsError('Destination already exists; temporary evidence was retained.')
    os.rename(temp,path)


def process_alive(pid):
    if type(pid) is not int or pid<=0:return None
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False if ctypes.get_last_error()==87 else None
        try:
            code=wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)):return None
            return code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True  # Signal 0 is read-only on POSIX only.
    except ProcessLookupError:return False
    except PermissionError:return None


class ExperimentStore:
    def __init__(self,path):
        self.path=Path(path).resolve()
        self.plan=validate_plan(json.loads((self.path/'experiment.json').read_text(encoding='utf-8')))

    @classmethod
    def create(cls,path,plan):
        path=Path(path)
        path.mkdir(parents=True,exist_ok=False)
        write_new(path/'experiment.json',validate_plan(plan))
        return cls(path)

    @contextmanager
    def lock(self,*,recover=False):
        path=self.path/'.writer.lock'
        if recover and path.exists():
            old=json.loads(path.read_text(encoding='utf-8'))
            if old.get('host')!=socket.gethostname() or process_alive(old.get('pid')) is not False:
                raise ValueError('Lock owner is alive or cannot be verified as a dead local process.')
            path.unlink()  # Only the checked, dead local writer lock; never a result.
        owner={'owner_id':str(uuid4()),'pid':os.getpid(),'host':socket.gethostname(),'created_at':timestamp()}
        try:
            with path.open('x',encoding='utf-8') as stream:
                json.dump(owner,stream);stream.flush();os.fsync(stream.fileno())
        except FileExistsError:raise ValueError('Another writer or stale lock exists. Verify ownership before recovery.') from None
        try:yield
        finally:
            if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('owner_id')==owner['owner_id']:
                path.unlink()

    def run_path(self,entry):
        if entry not in self.plan['schedule']:raise ValueError('Run is not part of the immutable schedule.')
        return self.path/'entries'/entry['run_id']

    def mark(self,entry,stage):
        write_new(self.run_path(entry)/(stage+'.started.json'),
            {'experiment_id':self.plan['experiment_id'],'run_id':entry['run_id'],'plan_hash':self.plan['plan_hash'],
                'stage':stage,'started_at':timestamp()})

    def save(self,entry,kind,payload):
        write_new(self.run_path(entry)/(kind+'.json'),{'schema_version':'h4-record-v1',
            'experiment_id':self.plan['experiment_id'],'run_id':entry['run_id'],'plan_hash':self.plan['plan_hash'],
            'kind':kind,'saved_at':timestamp(),'payload_sha256':digest(payload),'payload':payload})

    def interruption(self,entry,stage,code):
        write_new(self.run_path(entry)/'interruption.json',{'experiment_id':self.plan['experiment_id'],
            'run_id':entry['run_id'],'plan_hash':self.plan['plan_hash'],'stage':stage,'code':code,
            'recorded_at':timestamp(),'message':'An attempted stage has no committed result. Do not retry it automatically; request outcome and usage may be unknown.'})

    def read_payload(self,entry,kind):
        path=self.run_path(entry)/(kind+'.json')
        if not path.exists():return None
        record=json.loads(path.read_text(encoding='utf-8'))
        if record['experiment_id']!=self.plan['experiment_id'] or record['run_id']!=entry['run_id'] or record['kind']!=kind or record['plan_hash']!=self.plan['plan_hash']:
            raise ValueError('Result belongs to a different experiment, run or stage.')
        if record['payload_sha256']!=digest(record['payload']):raise ValueError('Saved result content changed.')
        if not (path.parent/(kind+'.started.json')).is_file():raise ValueError('Result has no prior attempt marker.')
        return record['payload']

    def read_run(self,entry):
        directory=self.run_path(entry)
        for stage in ['candidate','grade']:
            marker=directory/(stage+'.started.json')
            if marker.exists():
                value=json.loads(marker.read_text(encoding='utf-8'))
                if any(value.get(k)!=v for k,v in [('experiment_id',self.plan['experiment_id']),('run_id',entry['run_id']),('plan_hash',self.plan['plan_hash']),('stage',stage)]):
                    raise ValueError('Attempt marker belongs to a different run or stage.')
        candidate=self.read_payload(entry,'candidate');grading=self.read_payload(entry,'grade')
        interrupted=directory/'interruption.json'
        interruption=json.loads(interrupted.read_text(encoding='utf-8')) if interrupted.exists() else None
        if interruption and any(interruption[k]!=v for k,v in [('experiment_id',self.plan['experiment_id']),('run_id',entry['run_id']),('plan_hash',self.plan['plan_hash'])]):
            raise ValueError('Interruption belongs to another run.')
        if interruption and (interruption['stage'] not in {'candidate','grade'} or
                (interruption['stage']=='candidate' and candidate is not None) or
                (interruption['stage']=='grade' and grading is not None)):
            raise ValueError('An interrupted stage cannot also have a committed result.')
        if grading is not None and candidate is None:raise ValueError('Grading has no candidate record.')
        if candidate is not None:
            if candidate.get('task_id')!=entry['task_id'] or candidate.get('strategy')!=entry['strategy'] or candidate.get('execution_mode')!=self.plan['execution_mode']:
                raise ValueError('Candidate identity/mode differs from the schedule.')
            config=candidate.get('configuration',{})
            fp=self.plan['fingerprint']
            if any(config.get(k)!=fp[k] for k in ['candidate_code_hash','catalog_data_hash','assessment_date','model']):
                raise ValueError('Candidate configuration differs from the experiment.')
        if grading is not None:
            if grading.get('task_id')!=entry['task_id'] or grading.get('candidate_trace_id')!=candidate.get('trace_id') or grading.get('candidate_record_sha256')!=digest(candidate) or grading.get('grader_hash')!=self.plan['fingerprint']['grader_hash']:
                raise ValueError('Grade does not refer to this candidate and frozen grader.')
            status,value=grading.get('status'),grading.get('passed')
            if not ((status=='passed' and value is True) or (status=='failed' and value is False) or
                    (status in {'judge_error','judge_disabled','invalid_input'} and value is None)):
                raise ValueError('Grading status and pass value disagree.')
        if interruption:state='interrupted_unknown'
        elif grading is not None:state='terminal'
        elif candidate is not None:state='grading_in_flight' if (directory/'grade.started.json').exists() else 'awaiting_grade'
        elif (directory/'candidate.started.json').exists():state='candidate_in_flight'
        else:state='pending'
        return {**entry,'state':state,'candidate':candidate,'grade':grading,'interruption':interruption}

    def records(self):
        allowed={entry['run_id'] for entry in self.plan['schedule']}
        folder=self.path/'entries'
        if folder.exists() and any(p.name not in allowed for p in folder.iterdir()):raise ValueError('Unscheduled result directory.')
        records=[self.read_run(entry) for entry in self.plan['schedule']]
        trace_ids=[r['candidate']['trace_id'] for r in records if r['candidate'] is not None]
        if len(trace_ids)!=len(set(trace_ids)):raise ValueError('Candidate task/repeat traces are not isolated.')
        return records


def execute(store,context,tasks,refs,*,candidate_factory=None,grader_fn=None,max_runs=None,recover_lock=False,on_event=None):
    if fingerprint(context)!=store.plan['fingerprint']:raise ValueError('Code, data, configuration or dependencies changed; use a new labelled experiment.')
    if max_runs is not None and (type(max_runs) is not int or max_runs<1):raise ValueError('max_runs must be positive.')
    real=store.plan['execution_mode']=='live_model'
    if real and (candidate_factory is not None or grader_fn is not None):
        raise ValueError('Real experiments cannot use injected candidate/grader test doubles.')
    if real and not context.runtime.settings.ready:raise ValueError('Live execution requires explicitly enabled model configuration.')
    if not real and (candidate_factory is None or grader_fn is None):raise ValueError('Offline tests require explicit candidate and grader doubles.')
    task_map={t.id:t for t in tasks}
    if not set(store.plan['task_ids'])<=set(task_map) or not set(store.plan['task_ids'])<=set(refs):raise ValueError('Missing tasks/references.')
    candidate_factory=candidate_factory or (lambda runtime,value,strategy:CandidateRun(runtime,value,strategy).run())
    judge=JudgeProvider(context) if real else None
    grader_fn=grader_fn or (lambda t,r,value,ctx:grade(t,r,value,ctx,judge=judge))
    count=0
    event=on_event or (lambda stage,entry:None)
    with store.lock(recover=recover_lock):
        store.records()  # Validate all prior committed records before further requests.
        for entry in store.plan['schedule']:
            saved=store.read_run(entry)
            if saved['state'] in {'terminal','interrupted_unknown'}:continue
            if max_runs is not None and count>=max_runs:break
            count+=1
            if saved['state'] in {'candidate_in_flight','grading_in_flight'}:
                store.interruption(entry,'candidate' if saved['candidate'] is None else 'grade','interrupted_before_commit')
                continue
            if saved['candidate'] is None:
                store.mark(entry,'candidate');event('candidate_started',entry)
                try:
                    value=candidate_factory(context.runtime,candidate_input(task_map[entry['task_id']],
                        date.fromisoformat(context.runtime.manifest['assessment_date'])),entry['strategy'])
                except Exception:
                    store.interruption(entry,'candidate','candidate_wrapper_error');continue
                store.save(entry,'candidate',value);event('candidate_saved',entry)
                saved=store.read_run(entry)
            store.mark(entry,'grade');event('grade_started',entry)
            try:grading=grader_fn(task_map[entry['task_id']],refs[entry['task_id']],deepcopy(saved['candidate']),context)
            except Exception:
                store.interruption(entry,'grade','grader_wrapper_error');continue
            store.save(entry,'grade',grading);event('grade_saved',entry)
            store.read_run(entry)
        return store.records()
