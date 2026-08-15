import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from axon.providers import ProviderStore, chat, choose_candidates, fetch_models


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class ProviderCatalogTests(unittest.TestCase):
    def store(self, directory):
        return ProviderStore(Path(directory) / "providers.json")

    @patch("axon.providers.requests.get")
    def test_gemini_import_persists_capability_and_reloads_routable(self, get):
        get.return_value = FakeResponse({"models": [{
            "name": "models/gemini-2.5-flash",
            "displayName": "Gemini Flash",
            "supportedGenerationMethods": ["generateContent", "countTokens"],
            "inputTokenLimit": 1000000,
        }]})
        imported = fetch_models("Google Gemini", "test-key")
        self.assertTrue(imported[0]["routable"])
        self.assertEqual(imported[0]["supported_generation_methods"], ["generateContent", "countTokens"])

        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            store.set_key("Google Gemini", "test-key")
            store.set_models("Google Gemini", imported)
            reloaded = self.store(directory)
            reloaded.set_key("Google Gemini", "test-key")
            saved = reloaded.models("Google Gemini")[0]
            self.assertEqual(saved["kind"], "chat")
            self.assertTrue(saved["routable"])
            self.assertEqual(choose_candidates(reloaded, "hello"), [("Google Gemini", "gemini-2.5-flash")])
            self.assertNotIn("keys", json.loads((Path(directory) / "providers.json").read_text()))

    def test_legacy_gemini_catalog_is_reclassified_conservatively(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "providers.json"
            path.write_text(json.dumps({"models": {"Google Gemini": [
                {"id": "gemini-2.5-flash", "kind": "specialized", "routable": False},
                {"id": "gemini-embedding-001", "kind": "chat", "routable": True},
                {"id": "aqa", "kind": "chat", "routable": True},
                {"id": "gemini-2.5-flash-image", "kind": "chat", "routable": True},
                {"id": "gemini-1.5-pro", "releaseStage": "DEPRECATED", "kind": "chat", "routable": True},
            ]}}))
            store = self.store(directory)
            models = {model["id"]: model for model in store.models("Google Gemini")}
            self.assertTrue(models["gemini-2.5-flash"]["routable"])
            for model_id in ("gemini-embedding-001", "aqa", "gemini-2.5-flash-image", "gemini-1.5-pro"):
                self.assertEqual(models[model_id]["kind"], "specialized")
                self.assertFalse(models[model_id]["routable"])

    @patch("axon.providers.requests.post")
    def test_offline_ollama_does_not_block_online_gemini_routing(self, post):
        post.return_value = FakeResponse({"candidates": [{"content": {"parts": [{"text": "cloud reply"}]}}]})
        with tempfile.TemporaryDirectory() as directory:
            store = self.store(directory)
            store.set_key("Google Gemini", "test-key")
            store.set_models("Ollama", [{"id": "local", "kind": "chat", "routable": True, "health": "OFFLINE"}])
            store.set_models("Google Gemini", [{
                "id": "gemini-2.5-flash", "kind": "chat", "routable": True,
                "supported_generation_methods": ["generateContent"], "health": None,
            }])
            self.assertEqual(choose_candidates(store, "hello"), [("Google Gemini", "gemini-2.5-flash")])
            self.assertEqual(chat(store, "hello")[:3], ("cloud reply", "Google Gemini", "gemini-2.5-flash"))
            self.assertIn("generativelanguage.googleapis.com", post.call_args.args[0])

    def test_no_candidate_error_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "No verified chat model is available"):
                chat(self.store(directory), "hello")
