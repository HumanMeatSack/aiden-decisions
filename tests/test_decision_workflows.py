import copy
import unittest
from unittest.mock import patch

from aiden_decisions.decision_workflows import WorkflowEngine, validate_graph
from aiden_decisions.decisions import DecisionBackendError, DecisionInputError


Q = {'type': 'choice', 'instructions': 'Choose category', 'criteria': {'yes': 'Fits', 'no': 'Does not fit'}}


def graph():
    return {'state': 'synthetic', 'stages': [
        {'id': 'first', 'questions': {'category': Q}},
        {'id': 'independent', 'questions': {'category': Q}},
        {'id': 'policy', 'after': ['first'], 'rule': {'op': 'all', 'checks': [
            {'stage': 'first', 'question': 'category', 'op': 'eq', 'value': 'yes'}]}},
        {'id': 'followup', 'after': ['policy'], 'when': {'stage': 'policy', 'question': 'result', 'op': 'gte', 'value': .5},
         'questions': {'category': Q}},
    ]}


class Stub:
    model = 'stub'; model_digest = 'stub-digest'
    def __init__(self): self.calls=[]; self.fail=False; self.choose='yes'
    def decide(self, value, **kwargs):
        self.calls.append(value)
        if self.fail: raise DecisionBackendError('no backend')
        return {'answers': {n: {'type':'choice','choice':self.choose,
                'probabilities':{'yes':.9 if self.choose=='yes' else .1,'no':.1 if self.choose=='yes' else .9}, 'confidence':.5}
                for n in value['questions']}, 'usage': {'input_tokens':10,'output_tokens':len(value['questions'])},
                'aiden': {'needs_review':False}}
    def home_route(self, text, **kwargs):
        return {'route':'tv','source':'deterministic_parser','needs_review':False,
                'draft_intent':{'target':'living_room_tv','action':'power','value':True},
                'usage':{'input_tokens':0,'output_tokens':0}}


class WorkflowTests(unittest.TestCase):
    def test_every_defined_stage_and_independent_batch(self):
        stub=Stub(); result=WorkflowEngine(stub).run(graph())
        self.assertEqual(result['model_calls'],2)
        self.assertEqual(len(stub.calls[0]['questions']),2)
        self.assertEqual([s['status'] for s in result['stages']],['completed']*4)
        self.assertEqual(stub.calls[1]['state']['upstream_answers']['policy']['result']['noul'],1.)
        self.assertEqual(result['device_action_authority'],'none')
        self.assertFalse(result['internal_model_reasoning_intercepted'])

    def test_conditional_branch_skips_without_inference(self):
        stub=Stub();stub.choose='no';result=WorkflowEngine(stub).run(graph())
        self.assertEqual(result['model_calls'],1)
        self.assertEqual(result['stages'][-1]['status'],'skipped_condition')

    def test_error_blocks_dependencies_and_falls_back(self):
        stub=Stub();stub.fail=True;result=WorkflowEngine(stub).run(graph())
        self.assertFalse(result['complete']);self.assertEqual(result['fallback'],'ordinary_reasoning')
        self.assertEqual(result['stages'][-1]['status'],'skipped_dependency')

    def test_deadline_prevents_additional_stages(self):
        stub=Stub(); ticks=iter([0.,10.,10.,10.])
        result=WorkflowEngine(stub,clock=lambda:next(ticks),budget_seconds=1).run(graph())
        self.assertEqual(stub.calls,[]);self.assertFalse(result['complete'])

    def test_invalid_graph_is_rejected_before_any_model_call(self):
        variants=[]
        v=graph();v['stages'][0]['after']=['followup'];variants.append(v)
        v=graph();v['stages'][1]['id']='first';variants.append(v)
        v=graph();v['stages'][0]['execute']='shell';variants.append(v)
        v=graph();v['stages'][2]['rule']['checks'][0]['question']='missing';variants.append(v)
        v=graph();v['stages'][2]['rule']['op']='eval';variants.append(v)
        v=graph();v['stages'][1]['after']=[{}];variants.append(v)
        for value in variants:
            stub=Stub()
            with self.subTest(value=value), self.assertRaises(DecisionInputError): WorkflowEngine(stub).run(value)
            self.assertEqual(stub.calls,[])

    def test_preflight_uses_zero_token_parser_then_code_policy(self):
        stub=Stub();result=WorkflowEngine(stub).preflight('turn the living room TV on')
        self.assertEqual(stub.calls,[])
        self.assertEqual(result['next_step'],'verify_live_tv_then_existing_controller')
        self.assertEqual(len(result['steps']),4)

    def test_weak_raw_clarification_cannot_force_an_unnecessary_question(self):
        stub=Stub()
        stub.home_route=lambda *args,**kwargs:{'route':'coding','source':'local_decision_model',
            'needs_review':True,'answers':{'clarify':{'type':'noul','noul':.99}}}
        flow=WorkflowEngine(stub)
        with patch.object(flow.registry,'apply',return_value={'status':'task_scoped','answers':{
            'clarify':{'status':'candidate_rejected'}},'suggestion_gate':{'threshold':None}}):
            result=flow.preflight('Implement a JSON validator')
        self.assertEqual(result['next_step'],'ordinary_reasoning_with_route_suggestion')
        self.assertTrue(result['needs_review'])

    def test_validated_route_gate_selects_only_a_handler_not_arguments(self):
        stub=Stub()
        stub.home_route=lambda *args,**kwargs:{'route':'coding','source':'local_decision_model','needs_review':True,'answers':{}}
        flow=WorkflowEngine(stub)
        evidence={'status':'task_scoped','answers':{'route':{'status':'synthetic_prediction_confidence_supported',
            'estimated_prediction_correctness':.95}},'suggestion_gate':{'threshold':None,'routing_only':{'threshold':.9}}}
        with patch.object(flow.registry,'apply',return_value=evidence):
            result=flow.preflight('Implement a JSON validator')
        self.assertEqual(result['next_step'],'inspect_implement_and_test')
        self.assertEqual(result['device_action_authority'],'none')
        self.assertIsNone(result['draft_intent'])

    def test_default_parser_target_still_requires_resolution(self):
        stub=Stub(); original=stub.home_route
        def ambiguous(*args,**kwargs):
            r=original(*args,**kwargs);r['needs_review']=True;return r
        stub.home_route=ambiguous
        result=WorkflowEngine(stub).preflight('turn the TV on')
        self.assertEqual(result['next_step'],'resolve_ambiguous_target_or_request')


if __name__=='__main__':unittest.main()
