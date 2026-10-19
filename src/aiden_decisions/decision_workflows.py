"""Automatic bounded decision graphs, not a model's private chain of thought."""
from __future__ import annotations

import copy
from pathlib import Path
import re
import time

from .decisions import DecisionBackendError, DecisionInputError, HOME_QUESTIONS, encode, validate_request
from .decision_calibration import CalibrationRegistry

STAGE_ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,19}\Z')
NEXT = {'tv': 'verify_live_tv_then_existing_controller',
        'lights': 'verify_live_lights_then_existing_controller',
        'climate': 'verify_live_climate_then_existing_controller',
        'security': 'read_camera_events_or_live_state', 'coding': 'inspect_implement_and_test',
        'knowledge': 'answer_with_verified_sources_when_needed', 'other': 'ordinary_reasoning'}


def answer_value(answer):
    if answer['type'] == 'choice': return answer['choice']
    if answer['type'] == 'noul': return answer['noul']
    return answer['score']


def validate_graph(value):
    if not isinstance(value, dict) or set(value) != {'state', 'stages'} or len(encode(value)) > 65536:
        raise DecisionInputError('Workflow requires state and stages within 64 KiB')
    stages = value['stages']
    if not isinstance(stages, list) or not 1 <= len(stages) <= 12:
        raise DecisionInputError('Provide 1–12 ordered stages')
    seen = {}; total = 0
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) - {'id', 'after', 'when', 'questions', 'rule'}:
            raise DecisionInputError('Unsupported workflow stage fields')
        ident = stage.get('id')
        if not isinstance(ident, str) or not STAGE_ID.fullmatch(ident) or ident in seen:
            raise DecisionInputError('Stages need unique short identifiers')
        after = stage.get('after', [])
        if (not isinstance(after, list) or any(not isinstance(x, str) for x in after)
                or len(set(after)) != len(after) or any(x not in seen for x in after)):
            raise DecisionInputError('Dependencies must name earlier stages; cycles are not allowed')
        if ('questions' in stage) == ('rule' in stage):
            raise DecisionInputError('Stage needs questions or one bounded rule')
        def check(condition):
            if not isinstance(condition, dict) or set(condition) != {'stage', 'question', 'op', 'value'}:
                raise DecisionInputError('Invalid workflow condition')
            parent = condition['stage']; question = condition['question']
            if not isinstance(parent, str) or not isinstance(question, str) or parent not in after or question not in seen[parent]:
                raise DecisionInputError('Conditions must reference declared upstream answers')
            if condition['op'] not in {'eq', 'gte', 'lte'} or not isinstance(condition['value'], (str, int, float, bool)):
                raise DecisionInputError('Only eq/gte/lte scalar comparisons are allowed')
            if condition['op'] != 'eq' and (isinstance(condition['value'], bool) or not isinstance(condition['value'], (int, float))):
                raise DecisionInputError('Ordered comparisons require numbers')
        if 'when' in stage: check(stage['when'])
        if 'questions' in stage:
            validate_request({'state': value['state'], 'questions': stage['questions']})
            if any(len(name) > 40 for name in stage['questions']):
                raise DecisionInputError('Workflow question names must fit 40 characters')
            seen[ident] = set(stage['questions']); total += len(stage['questions'])
        else:
            rule = stage['rule']
            if not isinstance(rule, dict) or set(rule) != {'op', 'checks'} or rule['op'] not in {'all', 'any'}:
                raise DecisionInputError('Invalid bounded rule')
            if not isinstance(rule['checks'], list) or not 1 <= len(rule['checks']) <= 16:
                raise DecisionInputError('Rules require 1–16 checks')
            for condition in rule['checks']: check(condition)
            seen[ident] = {'result'}
    if total > 64: raise DecisionInputError('Workflow exceeds 64 model questions')
    return copy.deepcopy(value)


class WorkflowEngine:
    def __init__(self, engine, *, calibration_path=None, clock=time.monotonic, budget_seconds=5):
        self.engine, self.clock, self.budget = engine, clock, budget_seconds
        self.registry = CalibrationRegistry(calibration_path or Path.home()/'.config/aiden-decisions/calibration.json')

    def preflight(self, request):
        """Automatic classify → scoped confidence → policy → verification plan."""
        started = self.clock(); routed = self.engine.home_route(request, deadline=started+self.budget)
        raw = routed.get('answers', {}); exact = routed['source'] == 'deterministic_parser'
        calibration = {'status': 'not_applicable_exact_parser', 'globally_calibrated': False}
        if not exact:
            calibration = self.registry.apply(routed, HOME_QUESTIONS, self.engine.model, self.engine.model_digest)
        supported = calibration.get('answers', {})
        clarify_evidence = supported.get('clarify', {})
        clarify = (clarify_evidence.get('probabilities', {}).get('true', 0)
                   if clarify_evidence.get('status') == 'synthetic_holdout_supported' else 0)
        threshold = calibration.get('suggestion_gate', {}).get('threshold')
        supported_gate = (threshold is not None and set(supported) == set(HOME_QUESTIONS)
                          and all(a.get('status') == 'synthetic_holdout_supported' for a in supported.values()))
        clears_gate = supported_gate and min(a['top_probability'] for a in supported.values()) >= threshold
        route_evidence = supported.get('route', {})
        routing_threshold = calibration.get('suggestion_gate', {}).get('routing_only', {}).get('threshold')
        routing_supported = (route_evidence.get('status') == 'synthetic_prediction_confidence_supported'
                             and routing_threshold is not None
                             and route_evidence['estimated_prediction_correctness'] >= routing_threshold)
        needs_review = routed['needs_review'] if exact else not clears_gate
        if clarify >= .85 or exact and routed['needs_review']:
            next_step = 'resolve_ambiguous_target_or_request'; needs_review = True
        elif not exact and routing_supported:
            next_step = NEXT[routed['route']]
            # Selecting a handler is automatic; model-inferred command arguments are still absent.
            needs_review = routed['route'] in {'tv','lights','climate','other'}
        elif needs_review:
            next_step = 'ordinary_reasoning_with_route_suggestion'
        else:
            next_step = NEXT[routed['route']]
        return {'workflow': 'aiden-preflight-v1', 'route': routed['route'],
                'draft_intent': routed.get('draft_intent'), 'needs_review': needs_review,
                'next_step': next_step, 'device_action_authority': 'none',
                'confidence_calibrated': False, 'calibration': calibration,
                'steps': [{'id': 'classify', 'status': 'completed', 'source': routed['source'], 'answers': raw},
                          {'id': 'confidence', 'status': 'completed', 'scope': calibration['status']},
                          {'id': 'policy', 'status': 'completed', 'next_step': next_step},
                          {'id': 'verify', 'status': 'required_before_any_effect',
                           'checks': ['original_user_instruction', 'fresh_relevant_facts', 'existing_control_permissions', 'observed_result']}],
                'cache_hit': routed.get('aiden', {}).get('cache_hit', False),
                'usage': routed.get('usage', {}), 'latency_ms': round((self.clock()-started)*1000, 3),
                'internal_model_reasoning_intercepted': False}

    def run(self, value):
        graph = validate_graph(value); started = self.clock(); done = {}; trace = []
        pending = list(graph['stages']); calls = 0; tokens = {'input_tokens': 0, 'output_tokens': 0}
        def condition(spec):
            answer = done[spec['stage']]['answers'][spec['question']]
            actual = answer_value(answer); expected = spec['value']; op = spec['op']
            if op == 'eq': return actual == expected
            if isinstance(actual, bool) or not isinstance(actual, (int, float)): return False
            return actual >= expected if op == 'gte' else actual <= expected
        def finish(stage, status, **fields):
            record = {'id': stage['id'], 'status': status, **fields}
            done[stage['id']] = record; trace.append(record); pending.remove(stage)
        while pending:
            ready = [s for s in pending if all(parent in done for parent in s.get('after', []))]
            if not ready: raise DecisionInputError('Workflow dependency resolution failed')
            groups = {}
            for stage in ready:
                after = stage.get('after', [])
                if any(done[p]['status'] != 'completed' for p in after):
                    finish(stage, 'skipped_dependency'); continue
                if 'when' in stage and not condition(stage['when']):
                    finish(stage, 'skipped_condition'); continue
                if 'rule' in stage:
                    values = [condition(c) for c in stage['rule']['checks']]
                    value = all(values) if stage['rule']['op'] == 'all' else any(values)
                    finish(stage, 'completed', source='deterministic_rule',
                           answers={'result': {'type': 'noul', 'noul': float(value)}}); continue
                groups.setdefault(tuple(sorted(after)), []).append(stage)
            for after, stages in groups.items():
                if self.clock()-started >= self.budget:
                    for stage in stages: finish(stage, 'budget_exhausted')
                    continue
                questions = {}; mapping = {}
                for stage in stages:
                    for name, question in stage['questions'].items():
                        key = stage['id']+'.'+name
                        questions[key] = question; mapping[key] = (stage['id'], name)
                state = graph['state'] if not after else {
                    'input': graph['state'], 'upstream_answers': {p: done[p]['answers'] for p in after}}
                try:
                    result = self.engine.decide({'state': state, 'questions': questions}, deadline=started+self.budget); calls += 1
                    for token in tokens: tokens[token] += result.get('usage', {}).get(token, 0)
                    for stage in stages:
                        answers = {name: result['answers'][stage['id']+'.'+name] for name in stage['questions']}
                        finish(stage, 'completed', source='local_decision_model', answers=answers,
                               cache_hit=result.get('aiden', {}).get('cache_hit', False),
                               confidence_calibrated=False, needs_review=result.get('aiden', {}).get('needs_review', True))
                except DecisionBackendError:
                    for stage in stages: finish(stage, 'backend_unavailable')
        return {'workflow': 'typed-graph-v1', 'stages': trace, 'model_calls': calls, 'usage': tokens,
                'complete': all(s['status'] in {'completed', 'skipped_condition', 'skipped_dependency'} for s in trace),
                'fallback': 'ordinary_reasoning' if any(s['status'] in {'backend_unavailable', 'budget_exhausted'} for s in trace) else None,
                'latency_ms': round((self.clock()-started)*1000, 3), 'device_action_authority': 'none',
                'internal_model_reasoning_intercepted': False}
