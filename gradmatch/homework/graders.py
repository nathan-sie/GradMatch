"""Independent evaluator-side checks and blinded reference packages; no production oracle."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from uuid import uuid4
from gradmatch.homework.contracts import TOOL_ARGUMENTS
from gradmatch.homework.grade_models import CodeCheck, criteria_for
from gradmatch.homework.runtime import load_runtime
from gradmatch.schemas import ApplicantProfile
from gradmatch.storage import PROJECT_ROOT


def stable_json(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def digest(value):return hashlib.sha256(stable_json(value).encode()).hexdigest()


@dataclass
class GradingContext:
    runtime: object
    config: dict
    grader_hash: str


def load_grading_context(*,live_model=False):
    runtime=load_runtime(live_model=live_model)
    config=json.loads((PROJECT_ROOT/'homework/grading.json').read_text(encoding='utf-8'))
    if config['judge_model']!=runtime.settings.model or config['automatic_retries']!=0 or config['max_judge_calls_per_grade']!=1:
        raise ValueError('Unsupported judge configuration.')
    paths=['homework/grading.json',*[f'gradmatch/homework/{n}.py' for n in
        ['grade_models','grading_prompt','graders','judging','dataset','validation']],'gradmatch/schemas.py']
    hashed=''.join(name+hashlib.sha256((PROJECT_ROOT/name).read_bytes()).hexdigest() for name in paths)
    grader_hash=hashlib.sha256(hashed.encode()).hexdigest()
    freeze_path=PROJECT_ROOT/'homework/grader_freeze.json'
    if freeze_path.exists():
        freeze=json.loads(freeze_path.read_text(encoding='utf-8'))
        if freeze['grader_hash']!=grader_hash or freeze['catalog_data_hash']!=runtime.manifest['catalog_data_hash']:
            raise ValueError('Grader differs from the H3 checkpoint freeze; create an explicit new revision.')
    return GradingContext(runtime,config,grader_hash)


def check(key,passed,reason):
    return CodeCheck(criterion_id=key,passed=bool(passed),reason=reason).model_dump(mode='json')


def contains_expected(text,expected,normalization):
    text=unicodedata.normalize('NFKC',text)
    if normalization=='decimal':
        try:target=Decimal(expected)
        except InvalidOperation:return False
        numbers=re.findall(r'(?<![\w.\-])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w|\.\d)',text)
        return any(Decimal(n.replace(',',''))==target for n in numbers)
    if normalization=='date':
        dates=re.findall(r'(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)',text)
        for match in re.findall(r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b',text,re.I):
            for fmt in ('%B %d %Y','%b %d %Y'):
                try:dates.append(datetime.strptime(match.replace(',',''),fmt).date().isoformat());break
                except ValueError:pass
        return expected in dates
    return bool(re.search(r'(?<!\w)'+re.escape(expected.casefold())+r'(?!\w)',text.casefold()))


def unit_guard(text,basis):
    if basis.normalization=='date':return bool(re.search(r'\b20\d\d\b',text))
    if basis.normalization!='decimal':return True
    path=basis.path or ''
    if basis.kind.startswith('tuition'):pattern=r'\b(?:USD|US dollars?|dollars?)\b|\$'
    elif path=='required_credits':pattern=r'\bcredits?\b|\bsemester hours?\b'
    elif path.startswith('gpa.'):pattern=r'\bGPA\b'
    elif path.endswith('.offers'):pattern=r'\boffers?\b'
    elif path.endswith('.applications'):pattern=r'\bapplications?\b'
    elif path.startswith('english.'):pattern=r'\b(?:TOEFL|IELTS|score|points?)\b'
    else:return True
    # Semantic linkage and contradictions are independently judged, beyond this presence guard.
    return bool(re.search(pattern,text,re.I))


def project_run(task,reference,result,context):
    """Whitelist candidate output/state only; never expose strategy or performance to the judge."""
    if result.get('task_id')!=task.id:raise ValueError('Candidate task ID mismatch.')
    if result.get('status')!='completed':return None,[check('execution_completed',False,'Candidate execution did not complete.')]
    if not isinstance(result.get('answer'),dict):raise ValueError('Missing structured candidate answer.')
    answer=result['answer']
    if set(answer)!={'answer','citations','recommendations','needs_clarification'} or not isinstance(answer['answer'],str) or not answer['answer'].strip():
        raise ValueError('Invalid candidate answer schema.')
    if type(answer['needs_clarification']) is not bool or not isinstance(answer['citations'],list) or not isinstance(answer['recommendations'],list):
        raise ValueError('Invalid candidate answer values.')
    before=ApplicantProfile.model_validate(result['profile_before']).model_dump(mode='json')
    after=ApplicantProfile.model_validate(result['profile_after']).model_dump(mode='json')
    checks=[check('execution_completed',True,'Candidate execution completed.'),
        check('initial_profile',before==task.profile.model_dump(mode='json'),'Initial profile must equal the declared task profile.')]
    spans=result['trace']['spans']
    if not isinstance(spans,list):raise ValueError('Invalid trace span list.')
    tool_spans=[s for s in spans if s.get('kind')=='tool']
    observed_ids=set()
    observed_programs=set()
    reported_checks=[]
    for span in tool_spans:
        observation=span.get('outputs') or {}
        if observation.get('ok') is not True:continue
        if isinstance(observation.get('program'),dict):
            observed_programs.add(observation['program']['program_id'])
        for source in observation.get('sources',[]):observed_ids.add(source['source_id'])
        if isinstance(observation.get('source'),dict):observed_ids.add(observation['source']['source_id'])
        if isinstance(observation.get('report'),dict):
            report=observation['report']
            reported_checks.append({'program_id':report.get('program_id'),'profile_version':report.get('profile_version'),
                'checks':deepcopy(report.get('checks',[]))})
    citations=answer['citations']
    cited=[]
    metadata_valid=True
    for item in citations:
        if not isinstance(item,dict) or not isinstance(item.get('source_id'),str):raise ValueError('Invalid citation record.')
        sid=item['source_id'];cited.append(sid)
        source=context.runtime.sources.get(sid)
        if source is None:metadata_valid=False;continue
        canonical={'url':str(source.url),'retrieved_at':source.retrieved_at.isoformat(),
            'applicable_intake':source.applicable_intake,'quote':source.source_excerpt,'locator':source.locator}
        metadata_valid &= all(item.get(key)==value for key,value in canonical.items())
    checks.append(check('citation_integrity',metadata_valid and len(set(cited))==len(cited)
        and set(cited)<=observed_ids,'Citation IDs and metadata must be real, unique and actually observed.'))
    allowed_urls={str(context.runtime.sources[sid].url) for sid in cited if sid in context.runtime.sources}
    allowed_urls |= {str(p.official_url) for p in context.runtime.programs if p.program_id in observed_programs}
    urls=re.findall(r'https?://[^\s<>\]\)]+',answer['answer'])
    checks.append(check('answer_urls',all(u.rstrip('.,;') in allowed_urls for u in urls),'Answer URLs must name observed program/source URLs.'))
    requested=reference.expected_profile_changes
    desired=deepcopy(before)
    desired.update(deepcopy(requested))
    desired=ApplicantProfile.model_validate(desired).model_dump(mode='json')
    changes_ok=all(after[key]==desired[key] for key in requested)
    other_keys=set(before)-set(requested)-{'profile_version'}
    preserve_ok=all(before[key]==after[key] for key in other_keys)
    real_change=any(before[key]!=desired[key] for key in requested)
    version_ok=after['profile_version']==before['profile_version']+(1 if real_change else 0)
    checks.append(check('profile_state',changes_ok and preserve_ok and version_ok,
        'Apply only expected explicit root-field changes, preserve other fields and advance the version only for an actual change.'))
    recommendation_ids=[]
    recommendation_source_ids=[]
    for item in answer['recommendations']:
        if not isinstance(item,dict) or not isinstance(item.get('program_id'),str):raise ValueError('Invalid recommendation.')
        recommendation_ids.append(item['program_id'])
        recommendation_source_ids.extend(c.get('source_id') for c in item.get('citations',[]))
    checks.append(check('formal_recommendation_scope',not (set(recommendation_ids)&set(reference.forbidden_formal_program_ids))
        and set(recommendation_ids)<=observed_programs and set(recommendation_source_ids)<=observed_ids,
        'Formal recommendations must be observed and not expressly forbidden by the task reference.'))
    view={'answer':answer['answer'],'cited_source_ids':cited,'recommendations':deepcopy(answer['recommendations']),
        'needs_clarification':answer['needs_clarification'],'profile_before':before,'profile_after':after,
        'profile_after_text':stable_json(after),'observed_source_ids':sorted(observed_ids),
        'observed_program_ids':sorted(observed_programs),'reported_checks':reported_checks}
    return view,checks


def deterministic_checks(task,reference,result,context):
    view,checks=project_run(task,reference,result,context)
    if view is None:return view,checks
    if task.type=='tool':
        spans=[s for s in result['trace']['spans'] if s.get('kind')=='tool']
        actual=None
        if spans:
            span=spans[0]
            name=span.get('name');arguments=(span.get('inputs') or {}).get('arguments')
            try:
                if name not in TOOL_ARGUMENTS:raise ValueError('Unknown tool')
                TOOL_ARGUMENTS[name].model_validate(arguments)
                actual={'name':name,'arguments':arguments}
            except (ValueError,TypeError):pass
        checks.append(check('first_tool_call',actual==task.expected_call.model_dump(mode='json'),
            'Compare the first actual tool span, never a later call or tool name mentioned in answer prose.'))
    elif task.type=='exact':
        basis=reference.exact_basis
        if basis is None:raise ValueError('Exact task has no independent answer basis.')
        checks.extend([
            check('exact_value',contains_expected(view['answer'],task.expected,basis.normalization),'Expected whole quantity/date/text must occur in the answer.'),
            check('exact_unit',unit_guard(view['answer'],basis),'The quantity must have the requested type of unit.'),
            check('exact_cited_basis',bool(set(view['cited_source_ids'])&set(reference.source_ids)),
                'An exact factual answer needs an observed citation to its reference basis; semantic judging checks actual support.')])
    return view,checks


def build_judge_package(task,reference,view,context):
    program_ids=set(task.program_ids)|set(reference.required_program_ids)|{c.program_id for c in reference.claims}
    program_ids |= set(view['observed_program_ids'])
    source_ids=set(reference.source_ids)|set(view['cited_source_ids'])|set(view['observed_source_ids'])
    sources=[]
    for sid in sorted(source_ids):
        if sid not in context.runtime.sources:continue
        source=context.runtime.sources[sid].model_dump(mode='json')
        sources.append({key:source[key] for key in ['source_id','program_id','url','title','applicable_intake',
            'verification_status','effective_period','retrieved_at','locator','source_excerpt','fact_summary','field_groups','verified_values']})
    return {'task':{'type':task.type,'question':task.question,'setup_messages':task.setup_messages,
            'as_of_date':context.runtime.manifest['assessment_date'],'declared_program_scope':task.program_ids},
        'reference':{'answer':reference.answer,'claims':[c.model_dump(mode='json') for c in reference.claims],
            'expected_checks':[c.model_dump(mode='json') for c in reference.expected_checks],
            'expected_profile_changes':reference.expected_profile_changes,
            'required_program_ids':reference.required_program_ids,'forbidden_formal_program_ids':reference.forbidden_formal_program_ids,
            'source_assertions':[c.model_dump(mode='json') for c in reference.source_assertions]},
        'criteria':criteria_for(task),'candidate':deepcopy(view),
        'frozen_programs':[p.model_dump(mode='json') for p in context.runtime.programs if p.program_id in program_ids],
        'frozen_sources':sources,'conservative_tier_rubric':context.runtime.rubric}


def validate_verdict(verdict,package):
    expected=[c['criterion_id'] for c in package['criteria']]
    ids=[c.criterion_id for c in verdict.criteria]
    if len(ids)!=len(set(ids)) or set(ids)!=set(expected):raise ValueError('Judge criterion IDs do not match.')
    for c in verdict.criteria:
        quote=c.evidence_quote
        if c.evidence_kind=='missing':
            if c.passed or quote:raise ValueError('A missing item cannot pass or contain a fabricated quote.')
        else:
            haystack=package['candidate']['answer'] if c.evidence_kind=='answer' else package['candidate']['profile_after_text']
            if not quote or quote not in haystack:raise ValueError('Judge evidence is not a verbatim candidate quote.')
    by_id={c.criterion_id:c for c in verdict.criteria}
    return [by_id[key].model_dump(mode='json') for key in expected]


def grade(task,reference,result,context,*,judge=None):
    from gradmatch.homework.judging import JudgeFailure
    if task.id!=reference.task_id:raise ValueError('Task/reference mismatch.')
    record={'schema_version':'h3-v1','grade_id':str(uuid4()),'task_id':task.id,
        'candidate_trace_id':result.get('trace_id'),'candidate_record_sha256':digest(result),
        'grader_hash':context.grader_hash,'status':'invalid_input','passed':None,
        'code_checks':[],'criteria':[],'judge_record':None,'error':None}
    try:
        view,checks=deterministic_checks(task,reference,result,context)
        record['code_checks']=checks
        if not all(c['passed'] for c in checks):
            record.update(status='failed',passed=False)
        elif task.type=='tool':
            record.update(status='passed',passed=True)
        elif judge is None:
            record.update(status='judge_disabled',error={'code':'judge_disabled','message':'Open-answer semantic grading requires an explicit judge.'})
        else:
            package=build_judge_package(task,reference,view,context)
            try:
                verdict,judge_record=judge.invoke(package)
                record['judge_record']=judge_record
                record['criteria']=validate_verdict(verdict,package)
            except JudgeFailure as error:
                record.update(status='judge_error',judge_record=error.record,error={'code':error.code,'message':'Judge failed; no automatic retry or pass was assigned.'})
                return record
            except ValueError:
                record.update(status='judge_error',error={'code':'invalid_judge_evidence','message':'Criterion IDs or quoted evidence failed validation.'})
                return record
            passed=all(c['passed'] for c in record['criteria'])
            record.update(status='passed' if passed else 'failed',passed=passed)
    except (ValueError,TypeError,KeyError,AttributeError):
        record.update(status='invalid_input',passed=None,error={'code':'invalid_grading_input','message':'Task, candidate output or trace did not satisfy the grading input contract.'})
    return record
