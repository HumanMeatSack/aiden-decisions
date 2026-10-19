import unittest
from aiden_decisions.decision_hooks import handle


class Stub:
    def __init__(self):self.calls=[]
    def preflight(self,prompt):
        self.calls.append(prompt)
        return {'route':'tv','next_step':'verify_live_tv_then_existing_controller','needs_review':False,
                'calibration':{'status':'not_applicable_exact_parser'}}


class HookTests(unittest.TestCase):
    def test_prompt_receives_compact_advisory_context_only(self):
        client=Stub();r=handle({'hook_event_name':'UserPromptSubmit','prompt':'turn the living room TV on'},client)
        self.assertEqual(client.calls,['turn the living room TV on'])
        self.assertNotIn('permissionDecision',str(r))
        self.assertNotIn('updatedInput',str(r))
        self.assertLess(len(str(r)),600)

    def test_sensitive_and_large_prompts_skip_without_disclosure(self):
        client=Stub()
        for prompt in ['password=PRIVATE_FAKE','api_key: PRIVATE_FAKE','x'*4001]:
            self.assertEqual(handle({'hook_event_name':'UserPromptSubmit','prompt':prompt},client),{})
        self.assertEqual(client.calls,[])

    def test_tool_checkpoints_inspect_no_arguments_and_grant_no_permission(self):
        r=handle({'hook_event_name':'PreToolUse','tool_name':'Bash','tool_input':{'command':'PRIVATE_FAKE'}})
        self.assertNotIn('PRIVATE_FAKE',str(r));self.assertNotIn('permissionDecision',str(r))
        self.assertIn('additionalContext',r['hookSpecificOutput'])

    def test_helper_tools_are_excluded_to_avoid_recursion(self):
        self.assertEqual(handle({'hook_event_name':'PreToolUse','tool_name':'mcp__aiden_decisions__decision_preflight'}),{})

    def test_failures_remain_quiet_and_original_permissions_are_unchanged(self):
        class Failure:
            def preflight(self,prompt):raise RuntimeError('PRIVATE_FAKE')
        self.assertEqual(handle({'hook_event_name':'UserPromptSubmit','prompt':'synthetic'},Failure()),{})
        self.assertEqual(handle({'hook_event_name':'PermissionRequest'}),{})


if __name__=='__main__':unittest.main()
