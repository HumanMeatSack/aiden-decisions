"""Loopback-only decision API. No device, filesystem, credential or execution API."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .decisions import DecisionBackendError, DecisionEngine, DecisionInputError, MAX_BYTES, encode
from .decision_workflows import WorkflowEngine


class DecisionServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, engine: DecisionEngine, port=8841, *, calibration_path=None):
        if not isinstance(port, int) or not 0 <= port <= 65535:
            raise ValueError("Invalid local port")
        super().__init__(("127.0.0.1", port), Handler)
        self.engine = engine
        self.workflows = WorkflowEngine(engine, calibration_path=calibration_path)
        self.slots = threading.BoundedSemaphore(2)


class Handler(BaseHTTPRequestHandler):
    server_version = "AidenDecisions/1"

    def log_message(self, format, *args):
        # Do not persist request paths, user text or private decision state.
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(50)

    def _send(self, status, body, content_type="application/json"):
        raw = body.encode() if isinstance(body, str) else encode(body)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def _local(self):
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "") not in hosts:
            self._send(403, {"error": "Only the local application host is accepted"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://"+host for host in hosts}:
            self._send(403, {"error": "Cross-site requests are not accepted"})
            return False
        return True

    def do_GET(self):
        if not self._local():
            return
        if self.path == "/":
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path == "/health":
            try:
                self._send(200, self.server.engine.health())
            except DecisionBackendError:
                self._send(503, {"ok": False, "error": "Local decision model unavailable"})
        else:
            self._send(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        if not self._local():
            return
        if self.path not in {"/v1/systemone", "/v1/decide", "/v1/route", "/v1/preflight", "/v1/workflow"}:
            self._send(404, {"error": "Unknown endpoint"}); return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self._send(415, {"error": "Send application/json"}); return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if self.headers.get("Transfer-Encoding") or not 0 < size <= MAX_BYTES:
            self._send(413, {"error": "Body must contain 1–65536 bytes with Content-Length"}); return
        if not self.server.slots.acquire(blocking=False):
            self._send(429, {"error": "Local decision engine is busy; no request was queued"}); return
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise DecisionInputError("Incomplete request body")
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise DecisionInputError("Request body must be a JSON object")
            if self.path in {"/v1/route", "/v1/preflight"}:
                if not isinstance(value, dict) or set(value) != {"request"}:
                    raise DecisionInputError("Route accepts only a request string")
                result = (self.server.workflows.preflight(value["request"]) if self.path == "/v1/preflight"
                          else self.server.engine.home_route(value["request"]))
            elif self.path == "/v1/workflow":
                result = self.server.workflows.run(value)
            else:
                result = self.server.engine.decide(value)
            self._send(200, result)
        except (DecisionInputError, ValueError, UnicodeError, RecursionError):
            self._send(422, {"error": "Invalid decision request; check question types, criteria and input limits"})
        except DecisionBackendError:
            self._send(503, {"error": "Local model could not answer; no cloud fallback or action was attempted"})
        except Exception:
            self._send(500, {"error": "Internal local decision error; no action was performed"})
        finally:
            self.server.slots.release()


def serve(engine, port=8841, *, calibration_path=None):
    server = DecisionServer(engine, port, calibration_path=calibration_path)
    print(f"Aiden Decisions: http://127.0.0.1:{server.server_address[1]} (classification only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


PAGE = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aiden Decisions</title><style>
body{margin:0;background:#101820;color:#e9f1f5;font:16px system-ui}main{max-width:780px;margin:auto;padding:38px 22px}
h1{margin-bottom:6px}p{color:#aabdc9;line-height:1.5}textarea{box-sizing:border-box;width:100%;min-height:115px;background:#1a2934;color:#fff;border:1px solid #405968;border-radius:12px;padding:15px;font:inherit}
button{background:#61d5b5;color:#102821;border:0;padding:13px 20px;border-radius:9px;font:600 16px system-ui;cursor:pointer;margin:12px 8px 8px 0}button:disabled{opacity:.5;cursor:wait}.examples button{background:#243b48;color:#deedf5;font-size:13px;padding:9px}
.box{margin-top:18px;padding:20px;background:#182933;border:1px solid #334c58;border-radius:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;color:#cee3ec}#summary{font-size:22px;font-weight:650}.tag{color:#61d5b5;font-size:13px}
</style><main><div class="tag">LOCAL ON YOUR COMPUTER</div><h1>Aiden Decisions</h1><p>Choose a handler, estimate a probability, or score a rubric. No subscription or cloud calls. This page classifies requests; it does not operate your devices.</p>
<label for="request">What would you like Aiden to understand?</label><textarea id="request">Put Bluey on the living room TV</textarea>
<div class="examples"><button data-text="Put Bluey on the living room TV">TV request</button><button data-text="Make the kitchen lights brighter">Lights</button><button data-text="Show me yesterday’s front-door camera events">Cameras</button><button data-text="Fix the bug that stops the video player">Coding</button></div>
<button id="decide">Run workflow</button><span id="state" aria-live="polite"></span><section class="box" hidden id="result"><div id="summary"></div><p id="detail"></p><details><summary>Decision steps and confidence</summary><pre id="json"></pre></details></section>
<p>Common supported commands use Aiden’s existing parser with zero model tokens. Broader requests use a local decision model. Model confidence is not a guarantee of correctness.</p>
<script>
const input=document.getElementById('request'),button=document.getElementById('decide'),status=document.getElementById('state');
document.querySelectorAll('[data-text]').forEach(b=>b.onclick=()=>{input.value=b.dataset.text;input.focus()});
button.onclick=async()=>{button.disabled=true;status.textContent='Checking locally…';try{
const response=await fetch('/v1/preflight',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request:input.value})});const data=await response.json();if(!response.ok)throw new Error(data.error);
document.getElementById('result').hidden=false;document.getElementById('summary').textContent='Handler: '+data.route;
document.getElementById('detail').textContent=(data.needs_review?'The request needs further review.':'The request is ready for the next checks.')+' No device action was performed.';
document.getElementById('json').textContent=JSON.stringify(data,null,2);status.textContent=data.latency_ms+' ms'+(data.cache_hit?' · cached':'');
}catch(error){status.textContent=error.message}finally{button.disabled=false}};
</script></main></html>'''
