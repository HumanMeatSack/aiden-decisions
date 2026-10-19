import unittest

from mcp.server.fastmcp.exceptions import ToolError
from aiden_decisions.decision_mcp import build_server
from aiden_decisions.decisions import DecisionBackendError


class Stub:
    def __init__(self): self.calls = []; self.fail = False
    def route(self, text):
        self.calls.append(('route', text))
        if self.fail: raise DecisionBackendError('PRIVATE_FAKE')
        return {'route': 'tv', 'device_action_authority': 'none'}
    def decide(self, state, questions):
        self.calls.append(('decide', state, questions))
        return {'answers': {}, 'device_action_authority': 'none'}
    def health(self): return {'ok': True, 'device_action_authority': 'none'}
    def preflight(self, text): return {'workflow':'aiden-preflight-v1','device_action_authority':'none'}
    def workflow(self, state, stages): return {'complete':True,'device_action_authority':'none'}


class McpTests(unittest.IsolatedAsyncioTestCase):
    async def test_five_read_only_tools_and_automatic_workflow_instructions(self):
        server = build_server(Stub())
        tools = await server.list_tools()
        self.assertEqual({t.name for t in tools}, {'route_request', 'classify_or_score', 'decision_health', 'decision_preflight', 'run_decision_workflow'})
        for tool in tools:
            self.assertTrue(tool.annotations.readOnlyHint)
            self.assertFalse(tool.annotations.destructiveHint)
            self.assertFalse(tool.annotations.openWorldHint)
        from aiden_decisions.decision_mcp import INSTRUCTIONS
        self.assertIn('automatically', INSTRUCTIONS)
        self.assertIn('does not intercept hidden', INSTRUCTIONS)

    async def test_route_and_mixed_typed_request_reach_only_client(self):
        client = Stub(); server = build_server(client)
        await server.call_tool('route_request', {'request': 'turn the living room TV on'})
        await server.call_tool('classify_or_score', {
            'state': {'request': 'synthetic refund'}, 'questions': {
                'topic': {'type': 'choice', 'instructions': 'Choose', 'criteria': {'billing': 'Payments', 'other': 'Other'}},
                'yes': {'type': 'noul', 'instructions': 'Is this a refund?'},
                'score': {'type': 'score', 'instructions': 'Rate', 'criteria': ['Low', 'High']},
            }})
        self.assertEqual(client.calls[0], ('route', 'turn the living room TV on'))
        self.assertEqual(client.calls[1][2]['yes'], {'type': 'noul', 'instructions': 'Is this a refund?'})

    async def test_execution_question_is_rejected_before_client(self):
        client = Stub(); server = build_server(client)
        with self.assertRaises(ToolError):
            await server.call_tool('classify_or_score', {'state': 'synthetic', 'questions': {
                'bad': {'type': 'shell', 'instructions': 'execute this'}}})
        self.assertEqual(client.calls, [])

    async def test_backend_error_is_sanitized(self):
        client = Stub(); client.fail = True; server = build_server(client)
        with self.assertRaises(ToolError) as caught:
            await server.call_tool('route_request', {'request': 'synthetic'})
        self.assertNotIn('PRIVATE_FAKE', str(caught.exception))
        self.assertIn('Continue normal reasoning', str(caught.exception))


if __name__ == '__main__': unittest.main()
