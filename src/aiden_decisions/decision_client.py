"""Bounded client for the running decision helper; no control-service imports."""
from __future__ import annotations

import ipaddress
import os
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .decisions import (
    DecisionBackendError, DecisionInputError, encode, validate_request, validate_response,
)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DecisionClient:
    """Reuse the service cache with a short timeout and no automatic retries."""

    def __init__(self, base_url=None, *, timeout=5):
        if base_url is None:
            base_url = os.environ.get("AIDEN_DECISIONS_URL", "http://127.0.0.1:8841")
        parsed = urlparse(base_url)
        try:
            local = ipaddress.ip_address(parsed.hostname or "").is_loopback
            port_ok = parsed.port is None or 1 <= parsed.port <= 65535
        except ValueError:
            local = port_ok = False
        if (not local or not port_ok or parsed.scheme != "http" or parsed.username
                or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            raise DecisionInputError("Helper URL must be a literal loopback HTTP address")
        if isinstance(timeout, bool) or not 0 < timeout <= 5:
            raise DecisionInputError("Helper timeout must be at most five seconds")
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self.opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _request(self, path, body=None):
        if path not in {"/health", "/v1/route", "/v1/decide", "/v1/preflight", "/v1/workflow"}:
            raise DecisionInputError("Unsupported helper endpoint")
        req = Request(self.base_url + path, data=None if body is None else encode(body),
                      headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise DecisionBackendError("Helper response exceeds the limit")
            result = json.loads(raw)
        except HTTPError as exc:
            exc.close()
            raise DecisionBackendError("Local helper rejected the request; continue normal reasoning") from None
        except (URLError, TimeoutError, OSError):
            raise DecisionBackendError("Local helper unavailable or timed out; continue normal reasoning") from None
        except (ValueError, UnicodeError, RecursionError):
            raise DecisionBackendError("Invalid local helper response; continue normal reasoning") from None
        if not isinstance(result, dict):
            raise DecisionBackendError("Invalid local helper response")
        return result

    @staticmethod
    def _authority(result):
        meta = result.get("aiden", {})
        if not isinstance(meta, dict) or result.get("device_action_authority", meta.get("device_action_authority")) != "none":
            raise DecisionBackendError("Helper response has an invalid authority boundary")
        return meta

    def health(self):
        result = self._request("/health")
        self._authority(result)
        return result

    def route(self, request):
        if not isinstance(request, str) or not request.strip() or len(request.encode()) > 4000:
            raise DecisionInputError("Routing requires 1–4000 UTF-8 bytes")
        started = time.monotonic()
        result = self._request("/v1/route", {"request": request})
        meta = self._authority(result)
        if (result.get("route") not in {"tv", "lights", "climate", "security", "knowledge", "coding", "other"}
                or result.get("source") not in {"deterministic_parser", "local_decision_model"}
                or not isinstance(result.get("needs_review"), bool)):
            raise DecisionBackendError("Invalid route suggestion")
        answers = result.get("answers", {})
        room = answers.get("room", {}).get("choice")
        return {"route": result["route"], "source": result["source"],
                "draft_intent": result.get("draft_intent"), "room": room,
                "needs_review": result["needs_review"] or result["source"] == "local_decision_model",
                "device_action_authority": "none", "confidence_calibrated": False,
                "cache_hit": bool(meta.get("cache_hit", False)),
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "usage": result.get("usage", {})}

    def decide(self, state, questions):
        body = validate_request({"state": state, "questions": questions})
        result = self._request("/v1/decide", body)
        meta = self._authority(result)
        validate_response(result, body["questions"])
        return {"answers": result["answers"], "needs_review": meta.get("needs_review", True),
                "question_review": meta.get("question_review", {}),
                "confidence_calibrated": False, "device_action_authority": "none",
                "cache_hit": bool(meta.get("cache_hit", False)),
                "latency_ms": meta.get("latency_ms"), "usage": result.get("usage", {})}

    def preflight(self, request):
        if not isinstance(request, str) or not request.strip() or len(request.encode()) > 4000:
            raise DecisionInputError("Preflight requires 1–4000 UTF-8 bytes")
        result = self._request('/v1/preflight', {'request': request})
        self._authority(result)
        return result

    def workflow(self, state, stages):
        from .decision_workflows import validate_graph
        body = validate_graph({'state': state, 'stages': stages})
        result = self._request('/v1/workflow', body)
        self._authority(result)
        return result
