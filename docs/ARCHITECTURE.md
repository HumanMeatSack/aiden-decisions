# Architecture and API

## Layers

- `decisions.py`: strict JSON/question/answer validation, local Ollama adapter,
  model capability/digest checks, bounded cache, CLI and routing.
- `home_controls.py`: pure example parser and synthetic logical catalog.
  It contains no appliance driver or execution service.
- `decision_workflows.py`: declared dependencies, batching, conditions and rules.
- `decision_calibration.py`: temperature scaling, correctness bins, Brier/NLL/ECE,
  Wilson intervals and model/question-scope checks.
- `decision_server.py`: loopback HTTP API and browser demo.
- `decision_client.py`: bounded shared-service client; proxy/redirect bypass is
  disabled and HTTP error bodies are not exposed.
- `decision_mcp.py` and `decision_hooks.py`: optional client integrations.

## HTTP routes

Start with `aiden-decisions serve`. It binds only `127.0.0.1`.

| Method and path | Body / result |
| --- | --- |
| `GET /` | Interactive routing demo |
| `GET /health` | Model inventory/capability readiness; not an inference test |
| `POST /v1/decide` | `{ "state": ..., "questions": ... }` |
| `POST /v1/systemone` | Alias of `/v1/decide` |
| `POST /v1/route` | `{ "request": "..." }` → draft or model-suggested handler |
| `POST /v1/preflight` | Same request → routing, confidence and verification plan |
| `POST /v1/workflow` | `{ "state": ..., "stages": [...] }` → stage trace |

Send `Content-Type: application/json`. Request size is at most 64 KiB, with
1–64 named questions. Choice/score questions accept 2–24 options; a `score`
is the probability-weighted zero-based rubric level. A graph allows 1–12 stages,
64 total questions and 16 comparisons per rule. Question IDs are bounded ASCII.
Unsupported fields and execution types are rejected before inference.

Independent graph stages sharing state and dependency context batch into one
native request. A stage has an `id`, optional `after` and `when`, and exactly
one of `questions` or `rule`. Dependencies must name earlier stages. Rules use
`all`/`any`; comparisons use `eq`/`gte`/`lte`. There is no evaluation of code.

## Runtime behavior

Model requests stay on literal loopback addresses. The model inventory is
checked for cloud-backed tags; redirect/proxy forwarding is disabled. Generic
decisions have a configurable timeout, default 45 seconds. Workflows have a
five-second decision budget; an already-running native computation may finish
after the caller's socket timeout. There are no automatic retries.

The service admits at most two concurrent HTTP requests. A third receives 429;
it is not queued. Cache defaults: 128 entries, five-minute expiry. Cache hits
report zero new inference tokens and preserve the original usage separately.
The cache is in memory, is lost on process exit, and is invalidated by input,
ordered questions/options and model digest changes.

Health checks may pass while a real inference fails (for example an incompatible
cached model format). Use the support-ticket example to verify inference.
An unsupported-format error after an Ollama update may require refreshing the
same model tag with `ollama pull`; do not treat health alone as proof of success.

## Security and deployment scope

This is a trusted local development service, without authentication. Host and
Origin checks reduce browser-origin attacks; they do not isolate untrusted local
programs. Do not expose its port to a LAN or the internet. Do not submit secrets.
The engine does not fetch user-supplied URLs or execute returned intents. An
application that acts on a suggestion needs its own authorization, target
resolution, fresh state and result checks.

No cloud service, user account, device configuration or model weights ship in
this repository. Telemetry/request logging is not enabled. Installing the
package does not register hooks, start a service or modify an assistant client.
