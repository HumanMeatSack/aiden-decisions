import importlib.resources
import json
import os
import unittest
from unittest.mock import patch

from aiden_decisions import DecisionClient, DecisionInputError


class StandaloneTests(unittest.TestCase):
    def test_catalog_contains_logical_examples_without_connection_details(self):
        resource = importlib.resources.files("aiden_decisions").joinpath("decision_routes.json")
        data = json.loads(resource.read_text())
        self.assertTrue(data["targets"])
        for device in data["devices"]:
            self.assertEqual(set(device), {"id", "actions"})
        for target in data["targets"]:
            self.assertLessEqual(set(target), {"id", "name", "aliases", "kind", "devices"})

    def test_client_environment_port_and_explicit_override(self):
        with patch.dict(os.environ, {"AIDEN_DECISIONS_URL": "http://127.0.0.1:8842"}):
            self.assertEqual(DecisionClient().base_url, "http://127.0.0.1:8842")
            self.assertEqual(DecisionClient("http://127.0.0.1:8843").base_url, "http://127.0.0.1:8843")

    def test_client_environment_cannot_redirect_to_remote_backend(self):
        with patch.dict(os.environ, {"AIDEN_DECISIONS_URL": "https://example.invalid"}):
            with self.assertRaises(DecisionInputError):
                DecisionClient()
