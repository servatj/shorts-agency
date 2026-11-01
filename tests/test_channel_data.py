"""Run the synthetic channel-summary browser regression when explicitly enabled."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


class ChannelDataBrowserTests(unittest.TestCase):
    def test_channel_metadata_provenance_and_safety(self):
        if os.environ.get('RUN_BROWSER_TESTS') != '1':
            self.skipTest('Set RUN_BROWSER_TESTS=1 for browser acceptance')
        if not shutil.which('node'):
            self.skipTest('Optional browser QA requires Node.js')
        probe = subprocess.run(['node', '-e', 'require(process.env.PLAYWRIGHT_MODULE || "playwright")'], capture_output=True)
        if probe.returncode:
            self.skipTest('Optional browser QA requires Playwright Node')
        project = Path(__file__).resolve().parents[1]
        result = subprocess.run(['node', str(project / 'tests/channel_data_browser.cjs')], capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
