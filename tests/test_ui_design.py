"""Clarity integration QA: synthetic records in an isolated HTTP fixture only."""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
import test_web
import test_references
from synthetic_credentials import TEST_PASSWORD, TEST_TOKEN


class DesignBrowserTests(unittest.TestCase):
    request = test_web.WebTests.request
    login = test_web.WebTests.login
    stop = test_web.WebTests.stop
    setUp = test_web.WebTests.setUp

    def test_external_reference_catalog_and_responsive_shell(self):
        if os.environ.get('RUN_BROWSER_TESTS') != '1':
            self.skipTest('Set RUN_BROWSER_TESTS=1 for browser acceptance')
        project = Path(__file__).resolve().parents[1]
        for filename in ('index.html', 'app.js', 'style.css'):
            shutil.copyfile(project / 'static' / filename, self.root / 'static' / filename)
        bearer = {'Authorization': 'Bearer ' + TEST_TOKEN}
        items = [test_references.ReferenceTests.item(self, source_id=f'QA{i:09d}', url=f'https://youtu.be/QA{i:09d}', title=f'Referencia externa {i:03d}', content_type='video' if i == 0 else 'short', views=12 if i == 0 else None) for i in range(125)]
        for start in range(0, len(items), 100):
            status, _, body = self.request('POST', '/v1/references/import', {'items': items[start:start + 100], 'run': test_references.ReferenceTests.run_info(self)}, bearer)
            self.assertEqual(status, 200, body)
        self.assertEqual(len(self.request('GET', '/v1/references', headers=bearer)[2]['items']), 125)
        self.assertEqual(self.request('GET', '/v1/shorts', headers=bearer)[2]['items'], [])
        import web_backend
        origin = f'http://127.0.0.1:{self.server.server_port}'
        old = web_backend.ORIGINS
        web_backend.ORIGINS = set(old) | {origin}
        self.addCleanup(setattr, web_backend, 'ORIGINS', old)
        result = subprocess.run(['node', str(project / 'tests/redesign_browser.cjs')], env={**os.environ, 'TEST_URL': origin, 'TEST_PASSWORD': TEST_PASSWORD}, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
