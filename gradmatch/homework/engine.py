"""Isolated snapshot Agent and fixed RAG adapter; no evaluator imports or scores."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
import re
from time import monotonic
from gradmatch.homework.models import AnswerDraft, Decision, RunStop
from gradmatch.homework.provider import HomeworkProvider, ProviderFailure
from gradmatch.homework.tools import SnapshotTools
from gradmatch.homework.trace import Trace
from gradmatch.ranking import RankingDraft
from gradmatch.session import Session, ProfilePatch, quick_patch, apply_patch
from gradmatch.validation import validate_shortlist, citation


class CandidateRun:
    """New instance per task/repeat. Reusing a provider does not share task state."""
    def __init__(self, runtime, candidate, strategy, *, provider=None, clock=monotonic):
        if strategy not in {'fixed','react'}: raise ValueError('Unknown strategy.')
        if candidate.as_of_date != date.fromisoformat(runtime.manifest['assessment_date']):
            raise ValueError('Candidate date differs from the frozen assessment date.')
        self.runtime, self.candidate, self.strategy = runtime, candidate.model_copy(deep=True), strategy
        self.provider = provider or HomeworkProvider(runtime.settings)
        self.session = Session(profile=candidate.profile.model_copy(deep=True))
        self.tools = SnapshotTools(runtime.programs, runtime.sources, candidate.as_of_date)
        self.trace, self.clock = Trace(), clock
        self.limits = dict(runtime.manifest['candidate_limits'])
        self.model_calls = self.tool_calls = 0
        self.cache, self.repetitions, self.seen_sources, self.retrieved = {}, {}, set(), set()
        self.checked_versions, self.turns, self.usage = {}, [], []

    def remaining(self):
        remaining = self.limits['max_task_seconds'] - (self.clock() - self.started)
        if remaining <= 0: raise RunStop('time_limit','The task time limit was reached.')
        return remaining

    def model(self, purpose, payload, history, parent):
        remaining = self.remaining()
        if self.model_calls >= self.limits['max_model_calls_per_task']:
            raise RunStop('model_call_limit','The task model-call limit was reached.')
        if self.provider.is_live and not self.runtime.settings.ready:
            raise RunStop('model_disabled','Real model calls are disabled. Use --live-model after local configuration.')
        self.model_calls += 1
        span = self.trace.start('model', purpose, parent, {'payload':payload,'tool_history':history}, 'model')
        span['model'] = self.runtime.settings.model
        try:
            value, usage = self.provider.invoke(purpose, payload, history,
                min(self.limits['model_timeout_seconds'],remaining))
        except ProviderFailure as error:
            self.usage.append(error.usage)
            span['usage'] = error.usage
            self.trace.finish(span, error={'code':error.code,'message':'The model request failed; no automatic retry was made.'})
            raise RunStop(error.code,'The model request failed; no automatic retry was made.') from None
        self.usage.append(usage)
        span['usage'] = usage
        output = value.model_dump(mode='json') if isinstance(value,ProfilePatch) else {
            'calls':[c.as_input() for c in value.calls],
            'answer':value.answer.model_dump(mode='json') if value.answer else None}
        self.trace.finish(span, outputs=output)
        self.remaining()
        return value, span['span_id']

    def tool(self, name, arguments, parent, selected_by):
        self.remaining()
        if self.tool_calls >= self.limits['max_tool_calls_per_task']:
            raise RunStop('tool_call_limit','The task tool-call limit was reached.')
        self.tool_calls += 1
        span = self.trace.start('tool',name,parent,{'arguments':arguments,
            'profile_version':self.session.profile.profile_version},selected_by)
        key = json.dumps([name,arguments,self.session.profile.profile_version],sort_keys=True)
        self.repetitions[key] = self.repetitions.get(key,0) + 1
        if self.repetitions[key] > 2:
            self.trace.finish(span,error={'code':'repeated_action','message':'Third identical action stopped.'})
            raise RunStop('repeated_action','The same action was requested three times without a state change.')
        hit = key in self.cache
        observation = deepcopy(self.cache[key]) if hit else self.tools.dispatch(name,arguments,self.session.profile)
        self.cache[key] = deepcopy(observation)
        span['cache_hit'] = hit
        if observation['ok']:
            if name == 'get_program':self.retrieved.add(arguments['program_id'])
            if name == 'check_program':self.checked_versions[arguments['program_id']] = self.session.profile.profile_version
            for source in observation.get('sources',[]):self.seen_sources.add(source['source_id'])
            if 'source' in observation:self.seen_sources.add(observation['source']['source_id'])
        self.trace.finish(span,outputs=observation,error=observation.get('error'))
        self.remaining()
        return observation

    def prepare(self, message, parent):
        # Same explicit update gate for both strategies. Informational questions use the supplied profile.
        low = message.lower()
        budget_assertion = bool(re.search(r'\b(?:my|the) (?:total )?budget\s*(?:is|:)|^\s*(?:change|set|update)\b',low))
        excludes_living = bool(re.search(r'\b(?:exclud\w*|without) living',low))
        ambiguous_budget = 'budget' in low and budget_assertion and not excludes_living and ('living' in low or 'total budget' in low)
        if ambiguous_budget:
            return 'Please specify your full-program tuition budget in USD, excluding living costs.'
        patch = quick_patch(message)
        mutation = re.match(r'\s*(?:please\s+)?(?:change|set|update|replace|increase|decrease|lower|raise|switch)\b',low)
        if patch is None and not mutation:return None
        if patch is None:
            patch, _ = self.model('interpret',{'current_profile':self.session.profile.model_dump(mode='json'),
                'user_message':message,'allowed_program_ids':self.candidate.program_ids},[],parent)
        span = self.trace.start('profile','apply_explicit_patch',parent,patch.model_dump(mode='json'),'shared_interpreter')
        before = self.session.profile.model_dump(mode='json')
        try:
            if not patch.operations or patch.ambiguous_fields:raise ValueError('Ambiguous patch')
            changed = apply_patch(self.session,patch,message)
        except (ValueError,TypeError):
            self.trace.finish(span,error={'code':'patch_rejected','message':'No profile changes were applied.'})
            return 'Please state the exact profile field and value to change; other fields will stay unchanged.'
        if changed:
            self.cache.clear()
            self.checked_versions.clear()
        self.trace.finish(span,outputs={'changed_roots':changed,'before':before,
            'after':self.session.profile.model_dump(mode='json'),'checks_invalidated':bool(changed)})
        return None

    def payload(self, message):
        return {'question':message,'current_profile':self.session.profile.model_dump(mode='json'),
            'declared_program_scope':self.candidate.program_ids,'as_of_date':str(self.candidate.as_of_date),
            'data_mode':'snapshot','conversation':deepcopy(self.turns),
            'catalog_index':self.tools.catalog_index(),'tier_rubric':self.runtime.rubric,
            'remaining_limits':{'model_calls':self.limits['max_model_calls_per_task']-self.model_calls,
                'tool_calls':self.limits['max_tool_calls_per_task']-self.tool_calls}}

    def fixed_retrieval(self, message, parent):
        # Predetermined classic RAG: exact-filter search, lexical scope, records, deterministic checks, one answer.
        index, low = self.tools.catalog_index(), message.lower()
        filters = {key:None for key in ('university','campus','discipline')}
        for key in ('university','campus'):
            matches = {row[key] for row in index if row[key].lower() in low}
            if len(matches) == 1:filters[key] = matches.pop()
        if re.search(r'\bece\b',low):filters['discipline']='ECE'
        elif re.search(r'\bcs\b|computer science',low):filters['discipline']='CS'
        search = self.tool('search_programs',filters,parent,'fixed_pipeline')
        if self.candidate.program_ids:
            ids = sorted(set(self.candidate.program_ids))
        else:
            ids = [r['program_id'] for r in search.get('programs',[]) if r['program_id'] in low
                or r['program_name'].lower() in low or r['university'].lower() in low]
        observations = [{'name':'search_programs','arguments':filters,'observation':search}]
        for pid in ids:
            for name,args in [('get_program',{'program_id':pid}),
                    ('check_program',{'program_id':pid,'profile_version':self.session.profile.profile_version})]:
                observations.append({'name':name,'arguments':args,'observation':self.tool(name,args,parent,'fixed_pipeline')})
        return observations

    def validate(self, draft, parent):
        span = self.trace.start('validation','validate_answer',parent,draft.model_dump(mode='json'),'shared_validator')
        errors = []
        if len(set(draft.citations)) != len(draft.citations) or not set(draft.citations) <= self.seen_sources:
            errors.append('UNOBSERVED_OR_DUPLICATE_CITATION')
        known_urls = {str(self.tools.sources[s].url) for s in self.seen_sources}
        known_urls |= {str(self.tools.programs[p].official_url) for p in self.retrieved}
        if any(url.rstrip('.,;)') not in known_urls for url in re.findall(r'https?://[^\s<>\]\)]+',draft.answer)):
            errors.append('UNOBSERVED_URL')
        retrieved = [self.tools.programs[p] for p in sorted(self.retrieved)]
        base = validate_shortlist(None,self.session.profile,self.runtime.programs,retrieved,
            self.tools.sources,as_of=self.candidate.as_of_date)
        status = 'infeasible' if base['status']=='infeasible' else 'insufficient_evidence'
        if draft.recommendations:
            if any(self.checked_versions.get(r.program_id) != self.session.profile.profile_version for r in draft.recommendations):
                errors.append('RECOMMENDATION_WITHOUT_CURRENT_CHECK')
            rec_ids = {r.program_id for r in draft.recommendations}
            if self.candidate.program_ids and not rec_ids <= set(self.candidate.program_ids):errors.append('OUT_OF_SCOPE_RECOMMENDATION')
            if not any(p['program_id'] not in rec_ids for p in base['pending_verification']):status='completed'
        ranking = RankingDraft(profile_version=self.session.profile.profile_version,status=status,
            recommendations=draft.recommendations,pending_order=[],observations=[])
        result = validate_shortlist(ranking,self.session.profile,self.runtime.programs,retrieved,
            self.tools.sources,as_of=self.candidate.as_of_date)
        errors.extend(result['validation_errors'])
        # Every evidence item authorizing a recommendation must also have been observed.
        if any(c['source_id'] not in self.seen_sources for r in result['recommendations'] for c in r['citations']):
            errors.append('UNOBSERVED_RECOMMENDATION_EVIDENCE')
        self.trace.finish(span,outputs={'accepted':not errors,'errors':errors})
        if errors:raise RunStop('validation_failed','The draft failed source or recommendation validation; inspect the trace.')
        return {'answer':draft.answer,'citations':[citation(self.tools.sources[s]) for s in draft.citations],
            'recommendations':result['recommendations'],'needs_clarification':draft.needs_clarification}

    def run(self):
        self.started = self.clock()
        root = self.trace.start('task','candidate_task',inputs={'task_id':self.candidate.task_id,'strategy':self.strategy,
            'candidate_input':self.candidate.model_dump(mode='json')})
        status, error, answer, active = 'completed', None, None, None
        try:
            for ordinal,message in enumerate([*self.candidate.setup_messages,self.candidate.question],1):
                active = self.trace.start('turn',f'user_turn_{ordinal}',root['span_id'],{'message':message})
                clarification = self.prepare(message,active['span_id'])
                if clarification:
                    answer = {'answer':clarification,'citations':[],'recommendations':[],'needs_clarification':True}
                elif self.strategy == 'fixed':
                    observations = self.fixed_retrieval(message,active['span_id'])
                    decision, model_span = self.model('fixed',{**self.payload(message),'observations':observations},[],active['span_id'])
                    if decision.answer is None:raise RunStop('invalid_fixed_answer','Fixed baseline returned no answer.')
                    answer = self.validate(decision.answer,model_span)
                else:
                    history = []
                    while True:
                        decision, model_span = self.model('react',self.payload(message),history,active['span_id'])
                        if decision.answer is not None:
                            if decision.calls:raise RunStop('ambiguous_decision','A decision contains both tools and a final answer.')
                            answer = self.validate(decision.answer,model_span)
                            break
                        if len(decision.calls)!=1:raise RunStop('invalid_decision','Expected one observable tool action or a final answer.')
                        call = decision.calls[0]
                        try:arguments=json.loads(call.arguments)
                        except ValueError:arguments=None
                        observation = self.tool(call.name,arguments,model_span,'model')
                        history.extend([call.as_input(),{'type':'function_call_output','call_id':call.call_id,
                            'output':json.dumps(observation,ensure_ascii=False)}])
                self.turns.append({'user':message,'assistant':answer,'profile_version':self.session.profile.profile_version})
                self.trace.finish(active,outputs=answer)
                active = None
            self.remaining()
        except RunStop as stop:
            status, error, answer = stop.code, {'code':stop.code,'message':str(stop)}, None
            if active:self.trace.finish(active,error=error)
        except Exception:
            # Persist unexpected failures without serializing exception messages or credentials.
            status, error, answer = 'internal_error', {'code':'internal_error','message':'An internal execution error occurred; inspect the completed spans.'}, None
            for span in self.trace.spans:
                if span['status']=='running' and span is not root:self.trace.finish(span,error=error)
        self.trace.finish(root,outputs={'status':status,'answer':answer},error=error)
        known_costs = [Decimal(u['estimated_cost_usd']) for u in self.usage if u.get('estimated_cost_usd') is not None]
        return {'schema_version':'h2-v1','task_id':self.candidate.task_id,'strategy':self.strategy,
            'trace_id':self.trace.trace_id,'status':status,'error':error,'answer':answer,
            'profile_before':self.candidate.profile.model_dump(mode='json'),
            'profile_after':self.session.profile.model_dump(mode='json'),'conversation':self.turns,
            'execution_mode':'live_model' if self.provider.is_live else 'offline_test_double',
            'model_calls':self.model_calls,'tool_calls':self.tool_calls,
            'actual_requests':sum(u.get('actual_request',False) for u in self.usage),
            'latency_ms':root['duration_ms'],'usage':self.usage,
            'estimated_cost_usd':str(sum(known_costs)) if len(known_costs)==len(self.usage) and self.usage else None,
            'usage_complete':bool(self.usage) and all(u.get('input_tokens') is not None and u.get('output_tokens') is not None for u in self.usage),
            'configuration':{'assessment_date':self.runtime.manifest['assessment_date'],'model':self.runtime.settings.model,
                'catalog_data_hash':self.runtime.manifest['catalog_data_hash'],'candidate_code_hash':self.runtime.code_hash,
                'limits':self.limits},'trace':self.trace.export()}
