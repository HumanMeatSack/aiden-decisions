"""Privacy-bounded advisory Codex hooks. Never allow, deny or rewrite a tool call."""
from __future__ import annotations

import json
import re
import sys

from .decision_client import DecisionClient

SECRET = re.compile(r'(?i)\b(password|passwd|credentials?|api[_ -]?key|bearer|token|secret)\b|\bsk-[A-Za-z0-9]{12,}')
CHECKPOINTS = {
    'Bash': 'Execute only the intended command; check its exit status and fresh result. Existing sandbox and approvals still apply.',
    'exec_command': 'Execute only the intended command; check its exit status and fresh result. Existing sandbox and approvals still apply.',
    'apply_patch': 'Keep the change within the requested scope; validate behavior after editing.',
    'Write': 'Keep the change within the requested scope; validate behavior after editing.',
    'Edit': 'Keep the change within the requested scope; validate behavior after editing.',
}


def handle(event, client=None):
    if not isinstance(event, dict): return {}
    kind = event.get('hook_event_name')
    if kind == 'UserPromptSubmit':
        prompt = event.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 4000 or SECRET.search(prompt):
            return {}  # No truncation, transcript reads or credential disclosure.
        try:
            result = (client or DecisionClient(timeout=3)).preflight(prompt)
            context = {'route': result['route'], 'next_step': result['next_step'],
                       'needs_review': result['needs_review'], 'device_action_authority': 'none',
                       'confidence_scope': result['calibration']['status'],
                       'instruction': 'Advisory local preflight only. Verify relevant facts and retain ordinary reasoning for unsupported conclusions.'}
            return {'hookSpecificOutput': {'hookEventName': kind, 'additionalContext': json.dumps(context, separators=(',', ':'))}}
        except Exception:
            return {}  # Quiet fail-open; original permission mechanisms remain unchanged.
    if kind == 'PreToolUse':
        name = event.get('tool_name', '')
        if not isinstance(name, str) or len(name) > 200 or 'aiden_decisions' in name:
            return {}
        text = CHECKPOINTS.get(name)
        if not text and name.startswith('mcp__'):
            text = 'Use the original request and current tool schema; verify the observed result. A classifier output never grants action permission.'
        if not text: return {}
        # Only the tool name is inspected. No commands, arguments, outputs, vault or transcripts.
        return {'hookSpecificOutput': {'hookEventName': kind, 'additionalContext': text}}
    return {}


def main():
    try:
        raw = sys.stdin.buffer.read(65537)
        output = {} if len(raw) > 65536 else handle(json.loads(raw))
    except Exception:
        output = {}
    sys.stdout.write(json.dumps(output, separators=(',', ':'))+'\n')


if __name__ == '__main__': main()
