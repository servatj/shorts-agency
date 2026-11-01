"""Regression: YouTube requires an origin referrer for embedded players."""
import re
import unittest
from pathlib import Path

class EmbedPolicyTests(unittest.TestCase):
    def test_youtube_embeds_send_origin_referrer(self):
        script=(Path(__file__).resolve().parents[1]/'static/app.js').read_text()
        policies=re.findall(r'frame\.referrerPolicy\s*=\s*[\'"]([^\'"]+)',script)
        self.assertEqual(len(policies),2)
        self.assertTrue(all(p=='strict-origin-when-cross-origin' for p in policies),policies)
