"""Preview metadata acceptance against isolated real HTTP and SQLite."""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
import test_web
from synthetic_credentials import TEST_PASSWORD, TEST_TOKEN
from web_store import WebStore


class PreviewTests(unittest.TestCase):
    setUp = test_web.WebTests.setUp
    stop = test_web.WebTests.stop
    request = test_web.WebTests.request

    def test_thumbnail_metadata_validation_persistence_and_old_records(self):
        auth = {'Authorization': 'Bearer ' + TEST_TOKEN}
        status, _, item = self.request('POST', '/v1/shorts', {'title': 'Synthetic preview', 'script': 'Original', 'thumbnail_url': 'https://images.example/cover.jpg'}, auth)
        self.assertEqual(status, 201, item)
        path = '/v1/shorts/' + str(item['id'])
        self.assertEqual(self.request('PATCH', path, {'status': 'published'}, auth)[0], 200)
        new_url = 'https://images.example/new.jpg'
        self.assertEqual(self.request('PATCH', path, {'thumbnail_url': new_url}, auth)[0], 200)
        self.assertEqual(self.request('GET', path, headers=auth)[2]['thumbnail_url'], new_url)
        reopened = WebStore(self.store.database_path)
        self.assertEqual(reopened.get_short(item['id'])['thumbnail_url'], new_url)
        self.assertEqual(self.request('PATCH', path, {'script': 'Changed', 'thumbnail_url': ''}, auth)[0], 409)
        self.assertEqual(reopened.get_short(item['id'])['script'], 'Original')
        for value in [None, 1, [], 'http://images.example/a', '//images.example/a', 'javascript:alert(1)', 'data:image/png;base64,a', 'https://user:pass@images.example/a', 'https://@images.example/a', 'https://images.example/\na', 'https://images.example/\x7fa', 'https://images.example/\\a', 'https://images.example:bad/a', 'https://images.example/' + 'a' * 4096]:
            with self.subTest(value=value):
                self.assertEqual(self.request('PATCH', path, {'thumbnail_url': value}, auth)[0], 400)
        boundary = 'https://images.example/' + 'a' * (4096 - len('https://images.example/'))
        self.assertEqual(self.request('PATCH', path, {'thumbnail_url': boundary}, auth)[0], 200)
        self.assertEqual(self.request('PATCH', path, {'thumbnail_url': '', 'undeclared': ''}, auth)[0], 400)
        self.assertEqual(self.request('PATCH', path, {'thumbnail_url': ''}, auth)[0], 200)
        default = self.request('POST', '/v1/shorts', {'title': 'No cover'}, auth)[2]
        self.assertEqual(default['thumbnail_url'], '')
        with reopened.connect() as db:
            db.execute('INSERT INTO web_shorts(document) VALUES (?)', (json.dumps({'title': 'Legacy', 'status': 'draft'}),))
        old = self.request('GET', '/v1/shorts', headers=auth)[2]['items'][0]
        self.assertEqual(old['thumbnail_url'], '')
        patched = self.request('PATCH', '/v1/shorts/' + str(old['id']), {'notes': 'Legacy metadata'}, auth)[2]
        self.assertEqual(patched.get('thumbnail_url'), '')

    def test_browser_previews(self):
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
        result = subprocess.run(['node', str(project / 'tests/previews_browser.cjs')], env={**os.environ, 'TEST_URL': origin, 'TEST_PASSWORD': TEST_PASSWORD}, capture_output=True, text=True, timeout=100)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())
