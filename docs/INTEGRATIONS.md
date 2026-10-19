# Clients and optional hooks

## Python: direct or shared service

`DecisionEngine()` calls local Ollama directly. `DecisionClient()` talks to the
running Aiden HTTP service and shares its cache with other clients:

```python
from aiden_decisions import DecisionClient
client = DecisionClient("http://127.0.0.1:8841")
print(client.preflight("turn the living room TV on"))
```

The client timeout is at most five seconds. Set `AIDEN_DECISIONS_URL` to another
literal loopback HTTP URL when using a different port. Explicit constructor
arguments take precedence over that environment variable.

## Generic MCP

Install `.[mcp]`, keep `aiden-decisions serve` running separately and point a
stdio MCP client at the absolute installed `aiden-decisions-mcp` executable.
See `examples/mcp.json`; replace the executable path with your own installation.
No API key is needed. These tools return decisions only and are annotated
read-only. They cannot call device services or grant permissions.

## Codex

After the optional dependencies are installed:

```sh
codex mcp add aiden_decisions -- /absolute/path/to/.venv/bin/aiden-decisions-mcp
codex mcp list
```

The executable path must exist on the computer running Codex. The service still
needs to be running separately. Follow the host's normal enablement and trust
review. This repository does not change your client configuration automatically.

Source: [official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).

## Optional advisory hooks

The exported `aiden-decisions-hook` command accepts one bounded JSON event on
stdin and emits one JSON object. Supported events are `UserPromptSubmit` and
`PreToolUse`. `examples/hooks.json` is a template with an executable placeholder;
review and adapt it through the host's normal hooks interface.

Prompt hooks classify up to 4,000 UTF-8 bytes and skip prompts containing several
common credential markers. This is a best-effort filter, not comprehensive data
loss prevention. Tool checkpoints inspect the tool name only, not command
arguments or outputs. They exclude these decision tools to avoid recursion.
Failures emit empty context and preserve the original host behavior.

Hooks never approve, deny, rewrite or execute a tool call. They cannot see or
replace an assistant's hidden internal reasoning. Host event support and trust
activation determine coverage; merely installing this package does not make
hooks active.

Source: [official Codex hooks documentation](https://learn.chatgpt.com/docs/hooks).
