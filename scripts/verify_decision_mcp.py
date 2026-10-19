"""Exercise the real stdio helper with synthetic inputs only; no device commands."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(__file__).resolve().parents[1]
    server = StdioServerParameters(
        command=sys.executable,
        args=['-m', 'aiden_decisions.decision_mcp'],
        env={**os.environ, 'PYTHONUNBUFFERED': '1'},
        cwd=str(root),
    )
    body = {'state': {'request': 'My card was charged twice. Please refund one charge.'},
            'questions': {
                'topic': {'type': 'choice', 'instructions': 'Which topic fits this request?',
                          'criteria': {'billing': 'Payments or refunds', 'technical': 'Software faults', 'other': 'None of those'}},
                'refund': {'type': 'noul', 'instructions': 'Is a refund explicitly requested?'},
                'severity': {'type': 'score', 'instructions': 'How urgent is this request?',
                             'criteria': ['Routine', 'Inconvenienced customer', 'Critical outage']},
            }}
    calls = []
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == {'route_request', 'classify_or_score', 'decision_health', 'decision_preflight', 'run_decision_workflow'}
            assert all(t.annotations.readOnlyHint for t in tools.tools)
            for name, args in [('decision_health', {}),
                               ('route_request', {'request': 'turn the living room TV on'}),
                               ('classify_or_score', body), ('classify_or_score', body),
                               ('decision_preflight', {'request': 'turn the living room TV on'}),
                               ('run_decision_workflow', {'state': 'A customer explicitly asks for a refund after being charged twice.', 'stages': [
                                   {'id':'intent','questions':{'refund':{'type':'noul','instructions':'Is a refund explicitly requested?'}}},
                                   {'id':'policy','after':['intent'],'rule':{'op':'all','checks':[
                                       {'stage':'intent','question':'refund','op':'gte','value':.5}]}}
                               ]})]:
                started = time.monotonic()
                result = await session.call_tool(name, args)
                assert not result.isError, 'MCP tool failed'
                value = result.structuredContent
                assert value['device_action_authority'] == 'none'
                calls.append({'tool': name, 'roundtrip_ms': round((time.monotonic()-started)*1000, 3), 'result': value})
            bad = await session.call_tool('classify_or_score', {'state': 'synthetic', 'questions': {'bad': {'type': 'shell', 'instructions': 'execute'}}})
            assert bad.isError
    assert calls[0]['result']['ok']
    assert calls[1]['result']['route'] == 'tv' and calls[1]['result']['usage']['input_tokens'] == 0
    assert calls[2]['result']['answers']['topic']['choice'] == 'billing'
    assert calls[2]['result']['answers']['refund']['noul'] > .5
    assert calls[3]['result']['cache_hit'] and calls[3]['result']['usage'] == {'input_tokens': 0, 'output_tokens': 0}
    assert calls[4]['result']['next_step'] == 'verify_live_tv_then_existing_controller'
    assert calls[5]['result']['complete'] and calls[5]['result']['model_calls'] == 1
    report = {'time_utc': datetime.now(timezone.utc).isoformat(), 'protocol': init.protocolVersion,
              'server': init.serverInfo.model_dump(), 'tool_names': [t.name for t in tools.tools],
              'synthetic_calls': calls, 'invalid_execution_type_rejected': True,
              'device_actions': 0, 'paid_api_calls': 0}
    target = root / 'output/aiden-decisions/workflow-mcp-verification.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'verified': True, 'protocol': init.protocolVersion,
                      'tool_names': report['tool_names'], 'roundtrip_ms': [c['roundtrip_ms'] for c in calls],
                      'cached_repeat': calls[3]['result']['cache_hit'], 'receipt': str(target)}))


if __name__ == '__main__': asyncio.run(main())
