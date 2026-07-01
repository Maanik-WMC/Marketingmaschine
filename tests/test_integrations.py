import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.integrations import check_openai_compatible_models


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class IntegrationTests(unittest.TestCase):
    def test_openai_compatible_check_does_not_pass_without_key(self):
        result = check_openai_compatible_models("kimi", "https://api.example.invalid/v1", "")
        self.assertFalse(result["ok"])
        self.assertFalse(result["configured"])
        self.assertEqual(result["error"], "API key not configured")

    def test_openai_compatible_check_verifies_configured_model(self):
        payload = {"data": [{"id": "kimi-best"}, {"id": "kimi-safe-review"}]}
        with patch("marketing_machine.integrations.urlopen", return_value=FakeResponse(payload)):
            result = check_openai_compatible_models(
                "kimi",
                "https://api.example.invalid/v1",
                "secret-value",
                "kimi-safe-review",
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["configured"])
        self.assertTrue(result["model_present"])
        self.assertEqual(result["available_models"], ["kimi-best", "kimi-safe-review"])


if __name__ == "__main__":
    unittest.main()
