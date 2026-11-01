"""Real HTTP acceptance: isolated roots, never the production database."""
import json
from pathlib import Path
import test_web
from synthetic_inventory import inventory
from synthetic_credentials import TEST_PASSWORD, TEST_TOKEN
import unittest


class SocialScriptsTests(unittest.TestCase):
    request = test_web.WebTests.request
    login = test_web.WebTests.login
    stop = test_web.WebTests.stop

    def setUp(self):
        test_web.WebTests.setUp(self)
        self.inventory = inventory()
        (self.root / 'data/social-inventory.json').write_text(json.dumps(self.inventory))
        self.bearer = {'Authorization': f'Bearer {TEST_TOKEN}'}

    def test_new_page_allowlist_and_reference_separation(self):
        for path in ('/social', '/scripts'):
            status, headers, content = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertIn(b'<html>', content)
            self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
            self.assertNotIn('unsafe-inline', headers['Content-Security-Policy'])
        for path in ('/social/extra', '/scripts/extra', '/static/social-inventory.json'):
            self.assertEqual(self.request('GET', path, headers=self.bearer)[0], 404)
        import test_references
        reference = test_references.ReferenceTests.item(self)
        self.assertEqual(self.request('POST', '/v1/references/import', {'items': [reference], 'run': test_references.ReferenceTests.run_info(self)}, self.bearer)[0], 200)
        self.assertEqual(len(self.request('GET', '/v1/references', headers=self.bearer)[2]['items']), 1)
        self.assertEqual(self.request('GET', '/v1/scripts', headers=self.bearer)[2]['items'], [])
        session, _, _ = self.login()
        self.assertEqual(self.request('GET', '/v1/scripts', headers=session)[2]['items'], [])

    def test_social_inventory_read_only_authenticated_exact_evidence(self):
        self.assertEqual(self.request('GET', '/v1/social-accounts')[0], 401)
        status, _, body = self.request('GET', '/v1/social-accounts', headers=self.bearer)
        self.assertEqual(status, 200)
        self.assertEqual(body['items'], self.inventory['accounts'])
        self.assertEqual(body['total'], len(self.inventory['accounts']))
        self.assertEqual(body['counts'], {'instagram': 1, 'tiktok': 1, 'youtube': 1})
        self.assertTrue(all(a['profile_url'] for a in body['items']))
        self.assertEqual(next(a for a in body['items'] if a['id'] == 'youtube:sample_account_00')['analytics']['subscribers'], 0)
        self.assertTrue(all(a['analytics']['observed_at'] is None for a in body['items'] if a['analytics']))
        session, _, _ = self.login()
        self.assertEqual(self.request('GET', '/v1/social-accounts', headers=session)[2], body)
        self.assertEqual(self.request('POST', '/v1/social-accounts', {}, self.bearer)[0], 405)
        self.assertEqual(self.request('GET', '/data/social-inventory.json', headers=self.bearer)[0], 404)

    def test_script_read_view_and_validated_social_assignment(self):
        self.assertEqual(self.request('GET', '/v1/scripts')[0], 401)
        status, _, first = self.request('POST', '/v1/shorts', {'title': 'Título', 'script': 'Narración COMPLETA\nsegunda línea', 'channel': 'Canal exacto', 'social_account_id': 'youtube:sample_account_00'}, self.bearer)
        self.assertEqual(status, 201, first)
        second = self.request('POST', '/v1/shorts', {'title': 'Vacío'}, self.bearer)[2]
        items = self.request('GET', '/v1/scripts', headers=self.bearer)[2]['items']
        self.assertEqual(items, [second, first])
        for query in ['t%C3%ADtulo', 'completa', 'canal%20exacto']:
            self.assertEqual(self.request('GET', '/v1/scripts?q=' + query, headers=self.bearer)[2]['items'], [first])
        self.assertEqual(self.request('GET', '/v1/scripts?q=missing', headers=self.bearer)[2]['items'], [])
        self.assertEqual(self.request('POST', '/v1/scripts', {}, self.bearer)[0], 405)
        path = '/v1/shorts/' + str(first['id'])
        for value in ['youtube:invented', ' youtube:sample_account_00', 12, {}, 'x' * 501]:
            self.assertEqual(self.request('PATCH', path, {'social_account_id': value}, self.bearer)[0], 400)
        session, _, _ = self.login()
        self.assertEqual(self.request('PATCH', path, {'social_account_id': None}, {'Cookie': session['Cookie']})[0], 403)
        self.assertEqual(self.request('PATCH', path, {'social_account_id': None}, session)[0], 200)
        saved = self.request('GET', path, headers=session)[2]
        self.assertIsNone(saved['social_account_id'])
        self.assertEqual(saved['script'], first['script'])
        self.assertEqual(saved['channel'], 'Canal exacto')
        self.assertEqual(saved['status'], 'draft')


    def test_patch_preserves_removed_social_account_but_rejects_new_unknown_ids(self):
        account_id = 'youtube:sample_account_00'
        status, _, created = self.request('POST', '/v1/shorts', {
            'title': 'Original', 'script': 'Keep narration', 'social_account_id': account_id,
        }, self.bearer)
        self.assertEqual(status, 201, created)
        path = '/v1/shorts/' + str(created['id'])
        self.inventory['accounts'] = [a for a in self.inventory['accounts'] if a['id'] != account_id]
        (self.root / 'data/social-inventory.json').write_text(json.dumps(self.inventory))
        session, _, _ = self.login()
        payload = {'title': 'Edited', 'social_account_id': account_id}
        self.assertEqual(self.request('PATCH', path, payload)[0], 401)
        self.assertEqual(self.request('PATCH', path, payload, {'Cookie': session['Cookie']})[0], 403)
        self.assertEqual(self.request('PATCH', path, {**payload, 'extra': 'unknown'}, session)[0], 400)
        for unknown_id in (account_id, 'youtube:invented'):
            status, _, body = self.request('POST', '/v1/shorts', {
                'title': 'New', 'social_account_id': unknown_id,
            }, self.bearer)
            self.assertEqual((status, body), (400, {'error': 'unknown_social_account_id'}))
        status, _, body = self.request('PATCH', path, {'social_account_id': 'youtube:invented'}, session)
        self.assertEqual((status, body), (400, {'error': 'unknown_social_account_id'}))
        self.assertEqual(self.request('GET', path, headers=self.bearer)[2], created)
        status, _, saved = self.request('PATCH', path, payload, session)
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved['title'], 'Edited')
        self.assertEqual(saved['social_account_id'], account_id)
        self.assertEqual(saved['script'], created['script'])
        self.assertEqual(self.request('GET', path, headers=session)[2], saved)
        status, _, cleared = self.request('PATCH', path, {'social_account_id': None}, session)
        self.assertEqual(status, 200, cleared)
        self.assertIsNone(cleared['social_account_id'])
        self.assertEqual(self.request('PATCH', path, payload, session)[0], 400)

    def test_browser_social_and_script_workflow(self):
        import os
        import shutil
        import subprocess
        import web_backend
        if os.environ.get('RUN_BROWSER_TESTS') != '1':
            self.skipTest('Optional browser QA: set RUN_BROWSER_TESTS=1')
        if not shutil.which('node'):
            self.skipTest('Optional browser QA requires Node.js')
        probe = subprocess.run(['node', '-e', 'require(process.env.PLAYWRIGHT_MODULE || "playwright")'], capture_output=True)
        if probe.returncode:
            self.skipTest('Optional browser QA requires the Playwright Node module')
        self.inventory = inventory({'instagram': 8, 'tiktok': 6, 'youtube': 7})
        (self.root / 'data/social-inventory.json').write_text(json.dumps(self.inventory))
        project = Path(__file__).resolve().parents[1]
        for filename in ('index.html', 'app.js', 'style.css'):
            shutil.copyfile(project / 'static' / filename, self.root / 'static' / filename)
        origin = 'http://127.0.0.1:' + str(self.server.server_port)
        # Only the isolated server process accepts its ephemeral browser origin.
        old_origins = web_backend.ORIGINS
        web_backend.ORIGINS = set(old_origins) | {origin}
        self.addCleanup(setattr, web_backend, 'ORIGINS', old_origins)
        result = subprocess.run(['node', str(project / 'tests/social_scripts_browser.cjs')], env={**os.environ, 'TEST_URL': origin, 'TEST_PASSWORD': TEST_PASSWORD}, capture_output=True, text=True, timeout=100)
        if result.returncode == 77:
            self.skipTest('Optional browser QA requires an installed Chromium browser')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())


if __name__ == '__main__':
    import unittest
    unittest.main()
