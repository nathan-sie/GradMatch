"""Metered Responses API adapter with native functions and no automatic retries."""
import json
from uuid import uuid4
from openai import OpenAI, OpenAIError, AuthenticationError, RateLimitError, APITimeoutError, APIConnectionError
from pydantic import ValidationError
from gradmatch.config import estimate_cost
from gradmatch.homework.contracts import TOOL_ARGUMENTS, TOOL_DESCRIPTIONS
from gradmatch.homework.models import AnswerDraft, Decision, ToolCall
from gradmatch.homework import prompts
from gradmatch.providers import strict_schema, _PAID_SLOTS
from gradmatch.session import ProfilePatch


class ProviderFailure(RuntimeError):
    def __init__(self, code, usage):
        super().__init__(code)
        self.code, self.usage = code, usage


class HomeworkProvider:
    is_live = True

    def __init__(self, settings, *, client=None):
        self.settings, self.client = settings, client

    def invoke(self, purpose, payload, history, timeout):
        settings = self.settings
        usage = dict(call_id=str(uuid4()), provider='openai', model=settings.model,
            input_tokens=None, output_tokens=None, cached_input_tokens=None, reasoning_tokens=None,
            estimated_cost_usd=None, cost_status='unknown', actual_request=False, status='error')
        if not settings.ready:
            raise ProviderFailure('model_disabled', usage)
        if not _PAID_SLOTS.acquire(timeout=min(1, max(0, timeout))):
            raise ProviderFailure('model_slots_busy', usage)
        try:
            output_type = ProfilePatch if purpose == 'interpret' else AnswerDraft
            instructions = {'interpret':prompts.INTERPRET, 'react':prompts.REACT, 'fixed':prompts.FIXED}[purpose]
            inputs = [{'role':'developer', 'content':instructions},
                {'role':'user', 'content':json.dumps(payload, ensure_ascii=False)}, *history]
            kwargs = dict(model=settings.model, input=inputs, store=False, timeout=timeout,
                max_output_tokens=settings.limits['max_output_tokens'],
                text={'format':{'type':'json_schema','name':output_type.__name__,
                    'strict':True,'schema':strict_schema(output_type)}})
            if purpose == 'react':
                kwargs.update(tools=[{'type':'function','name':name,'description':TOOL_DESCRIPTIONS[name],
                    'parameters':strict_schema(model),'strict':True} for name, model in TOOL_ARGUMENTS.items()],
                    parallel_tool_calls=False, tool_choice='auto')
            client = self.client or OpenAI(api_key=settings.api_key, base_url='https://api.openai.com/v1',
                max_retries=0, timeout=timeout)
            usage['actual_request'] = True
            response = client.responses.create(**kwargs)
            usage.update(model=response.model, response_id=response.id)
            if response.usage is not None:
                u = response.usage
                usage.update(input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                    cached_input_tokens=getattr(u.input_tokens_details,'cached_tokens',None),
                    reasoning_tokens=getattr(u.output_tokens_details,'reasoning_tokens',None))
                cost = estimate_cost(settings, response.model, u.input_tokens, u.output_tokens, usage['cached_input_tokens'])
                usage.update(estimated_cost_usd=str(cost) if cost is not None else None,
                    cost_status='estimated_from_published_prices' if cost is not None else 'unknown')
            if response.status != 'completed':
                raise ProviderFailure('incomplete_response', usage)
            calls = [ToolCall(item.call_id, item.name, item.arguments) for item in response.output if item.type == 'function_call']
            if calls:
                if purpose != 'react' or len(calls) != 1 or response.output_text:
                    raise ProviderFailure('invalid_tool_response', usage)
                value = Decision(calls=calls)
            elif response.output_text:
                parsed = output_type.model_validate_json(response.output_text)
                value = parsed if purpose == 'interpret' else Decision(answer=parsed)
            else:
                raise ProviderFailure('empty_or_refused_response', usage)
            usage['status'] = 'completed'
            return value, usage
        except ProviderFailure:
            raise
        except AuthenticationError:
            raise ProviderFailure('authentication_error', usage) from None
        except RateLimitError:
            raise ProviderFailure('rate_limit', usage) from None
        except (APITimeoutError, APIConnectionError):
            raise ProviderFailure('connection_or_timeout', usage) from None
        except (OpenAIError, ValidationError, ValueError, TypeError):
            # SDK exception strings can include request data; never persist them.
            raise ProviderFailure('invalid_request_or_output', usage) from None
        finally:
            _PAID_SLOTS.release()
