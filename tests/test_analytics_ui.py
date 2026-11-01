"""Analytics acceptance uses isolated real HTTP/SQLite and synthetic data."""
import os
import shutil
import subprocess
import unittest
from pathlib import Path
import test_web
from synthetic_credentials import TEST_PASSWORD


class AnalyticsBrowserTests(unittest.TestCase):
    setUp = test_web.WebTests.setUp
    stop = test_web.WebTests.stop

    def test_analytics_browser(self):
        if os.environ.get('RUN_BROWSER_TESTS') != '1':
            self.skipTest('Set RUN_BROWSER_TESTS=1')
        project = Path(__file__).resolve().parents[1]
        for name in ('index.html', 'app.js', 'style.css'):
            shutil.copyfile(project / 'static' / name, self.root / 'static' / name)
        import web_backend
        origin = f'http://127.0.0.1:{self.server.server_port}'
        old = web_backend.ORIGINS
        web_backend.ORIGINS = set(old) | {origin}
        self.addCleanup(setattr, web_backend, 'ORIGINS', old)
        result = subprocess.run(['node', str(project / 'tests/analytics_browser.cjs')], env={**os.environ, 'TEST_URL': origin, 'TEST_PASSWORD': TEST_PASSWORD}, capture_output=True, text=True, timeout=160)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
