"""Authored calibration fixtures, explicitly distinct from actual candidate executions."""
from copy import deepcopy
import json
from uuid import uuid4


def fixture_result(task,answer,source_ids,context):
    sources=context.runtime.sources
    citations=[{'source_id':sid,'url':str(sources[sid].url),'retrieved_at':sources[sid].retrieved_at.isoformat(),
        'applicable_intake':sources[sid].applicable_intake,'quote':sources[sid].source_excerpt,'locator':sources[sid].locator}
        for sid in source_ids]
    profile=task.profile.model_dump(mode='json')
    pid=task.program_ids[0] if task.program_ids else None
    span={'span_id':str(uuid4()),'kind':'tool','name':'get_program','selected_by':'authored_fixture',
        'inputs':{'arguments':{'program_id':pid}},'outputs':{'ok':True,
            'program':{'program_id':pid},'sources':[{'source_id':sid} for sid in source_ids]}}
    return {'schema_version':'h2-v1','task_id':task.id,'trace_id':str(uuid4()),'status':'completed',
        'answer':{'answer':answer,'citations':citations,'recommendations':[],'needs_clarification':False},
        'profile_before':deepcopy(profile),'profile_after':deepcopy(profile),'trace':{'spans':[span]},
        'execution_mode':'authored_calibration_fixture','strategy':'deliberately_not_sent_to_judge'}


def load_cases(path):
    cases=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    if [c['case_id'] for c in cases]!=list('ABCDEF'):raise ValueError('Calibration case IDs must be A-F.')
    return cases


def calibration_sources(task,reference,context):
    # The credit examples also mention the per-credit price, so cite its separate bound source.
    ids=set(reference.source_ids)
    if task.id=='d01':
        ids.update(s.source_id for s in context.runtime.sources.values()
            if s.program_id in task.program_ids and 'tuition' in s.field_groups)
    return sorted(ids)
