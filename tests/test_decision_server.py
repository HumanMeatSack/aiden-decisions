import http.client
import json
import threading
import unittest
from aiden_decisions.decision_server import DecisionServer
from aiden_decisions.decisions import DecisionBackendError, DecisionInputError


class Stub:
    def __init__(self): self.calls=[]; self.fail=False
    def health(self): return {"ok": True, "device_action_authority": "none"}
    def decide(self, value):
        self.calls.append(value)
        if self.fail: raise DecisionBackendError("PRIVATE_FAKE_VALUE")
        return {"answers": {}, "device_action_authority": "none"}
    def home_route(self, value): return {"route": "tv", "device_action_authority": "none"}


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=Stub();cls.server=DecisionServer(cls.engine,0)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown();cls.server.server_close();cls.thread.join()
    def send(self, path="/v1/decide", body=None, headers=None):
        c=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        raw=json.dumps(body or {"state":"synthetic"})
        c.request("POST",path,raw,{"Content-Type":"application/json",**(headers or {})})
        r=c.getresponse();result=r.status,r.read();c.close();return result
    def test_local_json_works_and_no_actions_are_returned(self):
        status,raw=self.send();self.assertEqual(status,200)
        self.assertEqual(json.loads(raw)["device_action_authority"],"none")
    def test_remote_origin_and_dns_rebinding_host_rejected(self):
        for headers in [{"Origin":"https://untrusted.invalid"},{"Host":"untrusted.invalid"}]:
            status,_=self.send(headers=headers);self.assertEqual(status,403)
    def test_form_posts_and_unknown_execution_endpoint_rejected(self):
        self.assertEqual(self.send(headers={"Content-Type":"application/x-www-form-urlencoded"})[0],415)
        self.assertEqual(self.send(path="/execute")[0],404)
    def test_oversized_body_rejected_before_backend(self):
        self.assertEqual(self.send(body={"state":"x"*65536})[0],413)
    def test_backend_failure_does_not_expose_private_error_or_fallback(self):
        self.engine.fail=True
        try:
            status,raw=self.send();self.assertEqual(status,503);self.assertNotIn(b"PRIVATE_FAKE_VALUE",raw)
        finally:self.engine.fail=False
    def test_oversubscription_is_not_queued(self):
        self.server.slots.acquire();self.server.slots.acquire()
        try:self.assertEqual(self.send()[0],429)
        finally:self.server.slots.release();self.server.slots.release()
    def test_deeply_nested_json_returns_bounded_input_error(self):
        c=http.client.HTTPConnection(*self.server.server_address,timeout=5)
        c.request("POST","/v1/decide",'['*2000+'0'+']'*2000,{"Content-Type":"application/json"})
        r=c.getresponse();self.assertEqual(r.status,422);r.read();c.close()


if __name__ == "__main__":unittest.main()
