import json
import os
import tempfile
import unittest
from synthetic_credentials import TEST_PASSWORD, TEST_TOKEN
from pathlib import Path

from agency_store import AgencyStore
from api_server import make_server


class AgencyStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "agency.db"
        self.store = AgencyStore(self.db)
        self.store.initialize()

    def tearDown(self):
        self.tmp.cleanup()

    def test_seeded_templates_include_short_and_longform_workflows(self):
        templates = self.store.list_templates()
        ids = {template["id"] for template in templates}
        self.assertIn("animated-science-short-v1", ids)
        self.assertIn("animated-science-longform-v1", ids)

    def test_prompt_pack_is_queryable_by_template(self):
        prompts = self.store.list_prompt_blocks("animated-science-short-v1")
        self.assertTrue(any(prompt["stage"] == "script" for prompt in prompts))
        self.assertTrue(any(prompt["stage"] == "image" for prompt in prompts))

    def test_research_channel_keeps_evidence_and_analysis_separate(self):
        channel_id = self.store.add_channel(
            name="Synthetic channel",
            url="https://www.youtube.com/sample_account",
            analysis_status="partial",
            notes="Direct visual review blocked by YouTube consent wall; validate against a supplied export before treating as channel evidence.",
        )
        channel = self.store.get_channel(channel_id)
        self.assertEqual(channel["analysis_status"], "partial")
        self.assertIn("consent wall", channel["notes"])


class ApiTests(unittest.TestCase):
    def test_api_rejects_missing_token_and_accepts_unique_token(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "agency.db"
        store = AgencyStore(db)
        store.initialize()
        app = make_server(store, TEST_TOKEN)

        status, body = app.dispatch("GET", "/v1/templates", None)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "unauthorized")

        status, body = app.dispatch("GET", "/v1/templates", f'Bearer {TEST_TOKEN}')
        self.assertEqual(status, 200)
        self.assertTrue(any(item["id"] == "animated-science-short-v1" for item in body["items"]))

        store.add_channel("Example", "https://youtube.com/@sample_account", notes="Research pending")
        status, body = app.dispatch("GET", "/v1/channels", f'Bearer {TEST_TOKEN}')
        self.assertEqual(status, 200)
        self.assertEqual(body["items"][0]["name"], "Example")

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
