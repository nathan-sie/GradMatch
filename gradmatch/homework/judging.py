"""Separate, metered evaluator requests; never share candidate history or usage."""
import json
from time import monotonic
from uuid import uuid4
from openai import OpenAI, OpenAIError, AuthenticationError, RateLimitError, APITimeoutError, APIConnectionError
from pydantic import ValidationError
from gradmatch.config import estimate_cost
from gradmatch.homework.grade_models import SpanJudgeVerdict, span_verdict_schema
from gradmatch.homework.grading_prompt import JUDGE_INSTRUCTIONS
from gradmatch.homework.trace import Trace
from gradmatch.providers import _PAID_SLOTS


class JudgeFailure(RuntimeError):
    def __init__(self,code,record):
        super().__init__(code)
        self.code,self.record=code,record


class JudgeProvider:
    is_live=True

    def __init__(self,context,*,client=None):
        self.context,self.client=context,client

    def invoke(self,package):
        settings=self.context.runtime.settings
        trace=Trace()
        span=trace.start('judge_model','criterion_judge',inputs={'instructions':JUDGE_INSTRUCTIONS,'package':package},selected_by='evaluator')
        usage={'call_id':str(uuid4()),'purpose':'judge','provider':'openai','model':self.context.config['judge_model'],
            'input_tokens':None,'output_tokens':None,'cached_input_tokens':None,'reasoning_tokens':None,
            'estimated_cost_usd':None,'cost_status':'unknown','actual_request':False,'status':'error'}
        record={'judge_run_id':trace.trace_id,'grader_hash':self.context.grader_hash,'usage':usage,
            'latency_ms':None,'trace':None,'raw_output_text':None,'execution_mode':'live_judge'}
        failure=None
        acquired=False
        started=monotonic()
        try:
            if not settings.ready:raise JudgeFailure('judge_disabled',record)
            acquired=_PAID_SLOTS.acquire(timeout=1)
            if not acquired:raise JudgeFailure('judge_slots_busy',record)
            timeout=self.context.config['judge_timeout_seconds']
            client=self.client or OpenAI(api_key=settings.api_key,base_url='https://api.openai.com/v1',max_retries=0,timeout=timeout)
            usage['actual_request']=True
            response=client.responses.create(model=self.context.config['judge_model'],
                input=[{'role':'developer','content':JUDGE_INSTRUCTIONS},
                    {'role':'user','content':json.dumps(package,ensure_ascii=False)}],
                store=False,timeout=timeout,max_output_tokens=self.context.config['max_output_tokens'],
                text={'format':{'type':'json_schema','name':'SpanJudgeVerdict','strict':True,'schema':span_verdict_schema(package)}})
            usage.update(model=response.model,response_id=response.id)
            if response.usage is not None:
                u=response.usage
                usage.update(input_tokens=u.input_tokens,output_tokens=u.output_tokens,
                    cached_input_tokens=getattr(u.input_tokens_details,'cached_tokens',None),
                    reasoning_tokens=getattr(u.output_tokens_details,'reasoning_tokens',None))
                cost=estimate_cost(settings,response.model,u.input_tokens,u.output_tokens,usage['cached_input_tokens'])
                usage.update(estimated_cost_usd=str(cost) if cost is not None else None,
                    cost_status='estimated_from_published_prices' if cost is not None else 'unknown')
            record['raw_output_text']=response.output_text
            if response.status!='completed' or not response.output_text:raise JudgeFailure('judge_incomplete_response',record)
            verdict=SpanJudgeVerdict.model_validate_json(response.output_text)
            usage['status']='completed'
            trace.finish(span,outputs=verdict.model_dump(mode='json'))
        except JudgeFailure as error:
            failure=error.code
        except AuthenticationError:failure='judge_authentication_error'
        except RateLimitError:failure='judge_rate_limit'
        except (APITimeoutError,APIConnectionError):failure='judge_connection_or_timeout'
        except (OpenAIError,ValidationError,ValueError,TypeError):failure='judge_invalid_output'
        except Exception:failure='judge_internal_error'
        finally:
            if acquired:_PAID_SLOTS.release()
            if failure:trace.finish(span,error={'code':failure,'message':'Judge request failed; no retry was made.'})
            record['latency_ms']=round((monotonic()-started)*1000,3)
            span['usage']=usage
            record['trace']=trace.export()
        if failure:raise JudgeFailure(failure,record)
        return verdict,record
