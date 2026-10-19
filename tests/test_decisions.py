import copy
import json
import io
import unittest
from unittest.mock import patch

from aiden_decisions.decisions import (
    DEFAULT_MODEL, DecisionBackendError, DecisionEngine, DecisionInputError,
    review_flags, validate_request, validate_response,
)


def request(state="A customer asks for a refund"):
    return {"state": state, "questions": {
        "topic": {"type": "choice", "instructions": "Choose the topic", "criteria": {"billing": "Payments", "other": "Anything else"}},
        "refund": {"type": "noul", "instructions": "Is a refund requested?"},
        "severity": {"type": "score", "instructions": "Rate severity", "criteria": ["Routine", "Critical"]},
    }}


def response():
    return {"model": DEFAULT_MODEL, "answers": {
        "topic": {"type": "choice", "choice": "billing", "probabilities": {"billing": .95, "other": .05}, "confidence": .7},
        "refund": {"type": "noul", "noul": .97},
        "severity": {"type": "score", "score": .4, "probabilities": {"0": .6, "1": .4}, "confidence": .03, "legend": {"0": "Routine", "1": "Critical"}},
    }, "usage": {"input_tokens": 100, "output_tokens": 3}}


class InputTests(unittest.TestCase):
    def test_mixed_types_and_structured_state(self):
        for state in ["hello", {"facts": [1, 2]}, ["first", "second"]]:
            self.assertEqual(validate_request(request(state)), request(state))

    def test_unsupported_execution_and_images_are_not_accepted(self):
        for key in ["tools", "execute", "url", "images", "keep_alive"]:
            with self.subTest(key=key), self.assertRaises(DecisionInputError):
                validate_request({**request(), key: "anything"})

    def test_input_is_never_silently_truncated(self):
        for state in ["", " ", False, None, "z"*65536, {"value": float("nan")}]:
            with self.subTest(state=str(type(state))), self.assertRaises(DecisionInputError):
                validate_request(request(state))

    def test_invalid_question_shapes(self):
        for question in [{}, {"type": "shell", "instructions": "run"},
                         {"type": "choice", "instructions": "choose", "criteria": {"one": "only option"}},
                         {"type": "score", "instructions": "rate", "criteria": ["only level"]},
                         {"type": "noul", "instructions": "test", "criteria": {"yes": "Yes", "no": "No"}}]:
            with self.subTest(question=question), self.assertRaises(DecisionInputError):
                validate_request({"state": "state", "questions": {"q": question}})

    def test_arbitrary_model_values_rejected(self):
        for model in [[], {}, False, ""]:
            with self.assertRaises(DecisionInputError):
                validate_request({**request(), "model": model})


class OutputTests(unittest.TestCase):
    def test_valid_native_probability_and_expected_score(self):
        validate_response(response(), request()["questions"])
        self.assertEqual(review_flags(response()["answers"]), {"topic": False, "refund": False, "severity": True})

    def test_bad_backend_answers_fail_closed(self):
        mutations = [
            lambda r: r["answers"].pop("refund"),
            lambda r: r["answers"]["topic"].update(choice="execute_shell"),
            lambda r: r["answers"]["topic"]["probabilities"].update(other=.95),
            lambda r: r["answers"]["refund"].update(noul=True),
            lambda r: r["answers"]["refund"].update(noul=float("nan")),
            lambda r: r["answers"]["severity"].update(score=9),
            lambda r: r["answers"]["topic"].update(confidence=2),
        ]
        for change in mutations:
            r = response(); change(r)
            with self.assertRaises(DecisionBackendError):
                validate_response(r, request()["questions"])


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        self.engine = DecisionEngine(clock=lambda: self.now, cache_size=2, cache_ttl=10)
        self.calls = []
        self.remote = False
        self.digest = "digest-one"
        self.capabilities = ["decision"]

        def backend(path, body=None):
            self.calls.append((path, copy.deepcopy(body)))
            if path == "/api/tags":
                return {"models": [{"name": DEFAULT_MODEL, "digest": self.digest,
                                    "remote_host": "https://example.invalid" if self.remote else ""}]}
            if path == "/api/show":
                return {"capabilities": self.capabilities}
            return response()
        self.engine._request = backend

    def test_only_literal_loopback_endpoints(self):
        for value in ["https://typesafe.ai", "http://localhost:11434", "http://192.0.2.1:11434",
                      "http://user:password@127.0.0.1:11434", "http://127.0.0.1:11434/redirect", "http://127.0.0.1:11434?next=evil"]:
            with self.assertRaises(DecisionInputError):
                DecisionEngine(base_url=value)

    def test_expired_workflow_deadline_prevents_backend_calls(self):
        with self.assertRaises(DecisionBackendError):
            self.engine.decide(request(), deadline=self.now)
        self.assertEqual(self.calls, [])
        self.assertIsNone(self.engine.deadline)

    def test_workflow_deadline_restores_budget_after_failure(self):
        self.engine._request=lambda *args: (_ for _ in ()).throw(DecisionBackendError('failure'))
        with self.assertRaises(DecisionBackendError):
            self.engine.decide(request(), deadline=self.now+1)
        self.assertIsNone(self.engine.deadline)

    def test_caching_no_new_model_tokens_and_caller_cannot_corrupt_cache(self):
        first = self.engine.decide(request())
        first["answers"]["topic"]["choice"] = "changed"
        second = self.engine.decide(request())
        self.assertEqual(second["answers"]["topic"]["choice"], "billing")
        self.assertTrue(second["aiden"]["cache_hit"])
        self.assertEqual(second["usage"], {"input_tokens": 0, "output_tokens": 0})
        self.assertEqual(sum(p == "/v1/systemone" for p, _ in self.calls), 1)

    def test_cache_expires_and_model_digest_change_invalidates(self):
        self.engine.decide(request())
        self.now += 11
        self.engine.decide(request())
        self.digest = "digest-two"
        self.engine.decide(request())
        self.assertEqual(sum(p == "/v1/systemone" for p, _ in self.calls), 3)

    def test_option_order_does_not_share_cached_results(self):
        original = request(); changed = request()
        changed["questions"]["topic"]["criteria"] = {"other": "Anything else", "billing": "Payments"}
        self.engine.decide(original); self.engine.decide(changed)
        self.assertEqual(sum(p == "/v1/systemone" for p, _ in self.calls), 2)

    def test_cloud_tag_change_blocked_even_with_a_cached_answer(self):
        self.engine.decide(request()); self.remote = True
        with self.assertRaises(DecisionBackendError):
            self.engine.decide(request())
        self.assertEqual(sum(p == "/v1/systemone" for p, _ in self.calls), 1)

    def test_missing_decision_capability_rejected(self):
        self.capabilities = ["completion"]
        with self.assertRaises(DecisionBackendError):
            self.engine.decide(request())
        self.assertFalse(any(p == "/v1/systemone" for p, _ in self.calls))

    def test_configured_model_cannot_be_overridden_by_a_request(self):
        with self.assertRaises(DecisionInputError):
            self.engine.decide({**request(), "model": "kimi-k2.5:cloud"})
        self.assertFalse(self.calls)

    def test_no_home_backend_or_credentials_used_for_a_fixed_command(self):
        import sys
        r = self.engine.home_route("turn the living room tv on")
        self.assertNotIn("aiden_bridge", sys.modules)
        self.assertEqual(r["route"], "tv")
        self.assertEqual(r["device_action_authority"], "none")
        self.assertFalse(self.calls)

    def test_representative_fixed_control_corpus_stays_read_only(self):
        from pathlib import Path
        p = Path(__file__).parents[1]/"benchmarks/aiden_home_controls/cases.jsonl"
        cases = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
        accepted = [c for c in cases if c["expected"] is not None]
        for c in accepted:
            r = self.engine.home_route(c["request"])
            self.assertEqual(r["draft_intent"], c["expected"], c["id"])
            self.assertEqual(r["usage"]["input_tokens"], 0)
            self.assertEqual(r["device_action_authority"], "none")
        self.assertFalse(self.calls)

    def test_unqualified_default_targets_are_reviewed(self):
        r = self.engine.home_route("turn the tv on")
        self.assertTrue(r["needs_review"])
        self.assertEqual(r["device_action_authority"], "none")

    def test_standalone_cli_uses_the_parser_without_model_or_device_access(self):
        from aiden_decisions.decisions import main
        with patch.object(DecisionEngine, "_request", side_effect=AssertionError("No backend calls")), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            result = main(["route", "turn the living room tv on"])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["device_action_authority"], "none")



if __name__ == "__main__":
    unittest.main()
