"""H5 pilot regressions for exact evidence after presentation-only normalization."""
import pytest
from gradmatch.homework.grade_models import CriterionVerdict,JudgeVerdict
from gradmatch.homework.graders import validate_verdict


def verdict(quote,kind='answer'):
    return JudgeVerdict(criteria=[CriterionVerdict(criterion_id='complete',passed=True,
        evidence_kind=kind,evidence_quote=quote,reason='Diagnostic quote validation, not a model score.')])


@pytest.mark.parametrize('answer,quote,mode',[
    ('Recorded **45 degree credits** are required.','45 degree credits are required.','rendered_markdown'),
    ('The price is **USD 1,130 per credit**.','The price is USD 1,130 per credit.','rendered_markdown'),
    ('Use '+chr(96)+'uw_ece_id'+chr(96)+' for the program.','Use uw_ece_id for the program.','rendered_markdown'),
    ('There are 45\\n  degree credits.','There are 45 degree credits.','rendered_markdown'),
    ('There are 45 credits.','45 credits','verbatim'),
])
def test_presentation_only_quotes_validate_without_paraphrase(answer,quote,mode):
    answer=answer.replace('\\n','\n')
    package={'criteria':[{'criterion_id':'complete'}],'candidate':{'answer':answer,'profile_after_text':'{}'}}
    assert validate_verdict(verdict(quote),package)[0]['quote_match']==mode


@pytest.mark.parametrize('answer,quote',[
    ('There are **45** credits.','There are 46 credits.'),
    ('There are **45.5** credits.','There are 455 credits.'),
    ('Program uw__ece__id is recorded.','Program uweceid is recorded.'),
    ('There are **45** credits.','** **'),
    ('There are **45** credits.','***'),
    ('There are **45** credits.','A paraphrased answer about forty-five.'),
])
def test_normalization_never_accepts_changed_facts_identifiers_or_empty_markup(answer,quote):
    package={'criteria':[{'criterion_id':'complete'}],'candidate':{'answer':answer,'profile_after_text':'{}'}}
    with pytest.raises(ValueError):validate_verdict(verdict(quote),package)


def test_profile_evidence_remains_literal():
    package={'criteria':[{'criterion_id':'complete'}],
        'candidate':{'answer':'Only the goal changed.','profile_after_text':'{"goal":"mixed"}'}}
    with pytest.raises(ValueError):validate_verdict(verdict('"goal": "mixed"','profile_after'),package)
    assert validate_verdict(verdict('"goal":"mixed"','profile_after'),package)[0]['quote_match']=='verbatim'


def test_formal_cost_forecast_weights_task_type_and_strategy():
    from scripts.homework.audit_h5 import forecast
    rows=[]
    for strategy in ['fixed','react']:
        for task_id in ['d01','d03']:
            rows.append({'task_id':task_id,'strategy':strategy,'state':'terminal','interruption':None,
                'candidate':{'model_calls':1,'usage':[{'actual_request':False,'input_tokens':10,'output_tokens':1,'estimated_cost_usd':'1'}]},
                'grade':{'judge_record':{'latency_ms':1,'usage':{'actual_request':False,'input_tokens':10,'output_tokens':1,'estimated_cost_usd':'0.5'}}}})
    result=forecast(rows,{'d01':'exact','d03':'tool'},{'t01':'exact','t02':'exact','t03':'tool'})
    assert result['complete'] and float(result['estimated_formal_usd'])==18
    assert result['two_times_planning_allowance_usd']=='36.00'


def test_formal_cost_forecast_does_not_guess_missing_pilot_cells():
    from scripts.homework.audit_h5 import forecast
    result=forecast([],{'d01':'exact'},{'t01':'exact','t02':'tool'})
    assert result['complete'] is False and result['estimated_formal_usd'] is None


def test_span_grader_copies_candidate_only_evidence_and_strict_schema_keys():
    from gradmatch.homework.grade_models import SpanJudgeVerdict,SpanVerdict,span_verdict_schema
    from gradmatch.homework.graders import evidence_spans
    view={'answer':'Programming is **required**. Your declared programming course is missing.',
        'profile_after':{'goal':'mixed'},'profile_after_text':'{"goal":"mixed"}'}
    spans=evidence_spans(view)
    package={'criteria':[{'criterion_id':'correct'}],'candidate':view,'evidence_spans':spans}
    judged=SpanJudgeVerdict(criteria={'correct':SpanVerdict(passed=True,evidence_id=spans[0]['evidence_id'],reason='Use candidate evidence.')})
    result=validate_verdict(judged,package)[0]
    assert result['evidence_quote']=='Programming is **required**.' and result['quote_match']=='selected_span'
    schema=span_verdict_schema(package)
    assert schema['properties']['criteria']['required']==['correct']
    enum=schema['$defs']['EvidenceAssessment']['properties']['evidence_id']['anyOf'][0]['enum']
    assert enum==[s['evidence_id'] for s in spans] and 'reference' not in enum
    for span in spans:
        original=view['answer'] if span['kind']=='answer' else view['profile_after_text']
        assert original[span['start']:span['end']]==span['text']


@pytest.mark.parametrize('id,passed',[('invented_span',True),(None,True)])
def test_span_grader_rejects_invented_or_missing_passing_evidence(id,passed):
    from gradmatch.homework.grade_models import SpanJudgeVerdict,SpanVerdict
    package={'criteria':[{'criterion_id':'correct'}],'candidate':{'answer':'45 credits.'},'evidence_spans':[]}
    judged=SpanJudgeVerdict(criteria={'correct':SpanVerdict(passed=passed,evidence_id=id,reason='Invalid evidence option.')})
    with pytest.raises(ValueError):validate_verdict(judged,package)


def test_span_missing_requirement_can_fail_without_a_fabricated_quote():
    from gradmatch.homework.grade_models import SpanJudgeVerdict,SpanVerdict
    package={'criteria':[{'criterion_id':'complete'}],'candidate':{'answer':'2.8 GPA.'},'evidence_spans':[]}
    judged=SpanJudgeVerdict(criteria={'complete':SpanVerdict(passed=False,evidence_id=None,reason='No minimum comparison was supplied.')})
    result=validate_verdict(judged,package)[0]
    assert not result['passed'] and result['evidence_quote']=='' and result['evidence_kind']=='missing'


@pytest.mark.parametrize('supported',[True,False])
def test_profile_quote_wrappers_only_normalize_a_real_user_substring(supported):
    from datetime import date
    from gradmatch.homework.dataset import load_candidate_inputs
    from gradmatch.homework.runtime import load_runtime
    from gradmatch.homework.engine import CandidateRun
    from gradmatch.homework.models import AnswerDraft,Decision
    from gradmatch.session import ProfilePatch,PatchOperation
    from gradmatch.storage import PROJECT_ROOT
    runtime=load_runtime()
    value=next(c for c in load_candidate_inputs(PROJECT_ROOT/'homework/dev_tasks.jsonl',date(2026,11,16)) if c.task_id=='d07')
    value.setup_messages=[]
    text='Change only my goal to mixed' if supported else 'Change only my goal to research'
    class Provider:
        is_live=False
        def invoke(self,purpose,payload,history,timeout):
            if purpose=='interpret':
                result=ProfilePatch(intent='update_profile',operations=[PatchOperation(field='goal',value_json='"mixed"',explicit_span='"'+text+'"')],
                    referenced_program_ids=[],ambiguous_fields=[])
            else:result=Decision(answer=AnswerDraft(answer='Profile update confirmed.',citations=[],recommendations=[],needs_clarification=False))
            return result,{'actual_request':False,'input_tokens':None,'output_tokens':None,'estimated_cost_usd':None}
    result=CandidateRun(runtime,value,'react',provider=Provider()).run()
    assert result['profile_after']['goal']==('mixed' if supported else 'employment')
    if supported:
        event=next(s for s in result['trace']['spans'] if s['kind']=='profile')
        assert event['outputs']['presentation_normalizations'][0]['literal_substring']==text
