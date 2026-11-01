"""Publication invariants against isolated SQLite and real HTTP servers."""
import tempfile
import threading
import json
from concurrent.futures import ThreadPoolExecutor
import unittest
from pathlib import Path

import web_store
import test_web
from synthetic_credentials import TEST_TOKEN


class PublicationStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'publication.db'
        self.store = web_store.WebStore(self.path)

    def test_published_script_change_is_rejected_atomically(self):
        original = self.store.create_short({'title': 'Sample', 'script': 'Final\nrevision', 'status': 'published'})
        with self.assertRaisesRegex(Exception, '^published_script_locked$') as raised:
            self.store.patch_short(original['id'], {'script': 'Replacement', 'title': 'Must not save'})
        self.assertEqual(type(raised.exception).__name__, 'PublishedScriptLocked')
        self.assertEqual(self.store.get_short(original['id']), original)

    def test_published_status_cannot_roll_back(self):
        original = self.store.create_short({'title': 'Sample', 'script': 'Final', 'status': 'published'})
        for status in ('draft', 'review', 'ready'):
            with self.subTest(status=status):
                with self.assertRaises(web_store.PublishedScriptLocked):
                    self.store.patch_short(original['id'], {'status': status})
                self.assertEqual(self.store.get_short(original['id']), original)


    def test_unchanged_resends_and_metadata_edits_are_allowed(self):
        script = 'Exact résumé\n  spacing\n' + 'x' * 90000
        original = self.store.create_short({'title': 'Sample', 'script': script, 'status': 'published'})
        for fields in ({'script': script}, {'status': 'published'}, {'script': script, 'status': 'published'}, {'notes': 'New metadata', 'title': 'Updated'}):
            saved = self.store.patch_short(original['id'], fields)
            self.assertEqual(saved['script'], script)
            self.assertEqual(saved['status'], 'published')
            for key, value in fields.items():
                self.assertEqual(saved[key], value)
        self.assertEqual(self.store.get_short(original['id']), saved)

    def test_final_revision_is_frozen_for_reopened_and_stale_store(self):
        original = self.store.create_short({'title': 'Sample', 'script': 'Draft'})
        stale_store = web_store.WebStore(self.path)
        self.assertEqual(stale_store.get_short(original['id'])['status'], 'draft')
        for state in ('draft', 'review', 'ready'):
            saved = self.store.patch_short(original['id'], {'script': state + ' revision', 'status': state})
            self.assertEqual(saved['script'], state + ' revision')
        published = self.store.patch_short(original['id'], {'script': 'Final revision', 'status': 'published'})
        for store in (stale_store, web_store.WebStore(self.path)):
            for fields in ({'script': 'Other'}, {'status': 'draft'}, {'script': 'Other', 'status': 'draft'}, {'script': 'Final revision', 'status': 'ready'}):
                with self.subTest(fields=fields):
                    with self.assertRaises(web_store.PublishedScriptLocked):
                        store.patch_short(original['id'], fields)
                    self.assertEqual(store.get_short(original['id']), published)

    def test_pending_patch_reads_publication_after_other_writer_commits(self):
        original = self.store.create_short({'title': 'Sample', 'script': 'Draft'})
        started = threading.Event()

        def edit():
            started.set()
            return self.store.patch_short(original['id'], {'script': 'Stale edit', 'status': 'draft'})

        # Hold a real SQLite writer open while a second connection tries to edit.
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                document = json.loads(db.execute('SELECT document FROM web_shorts WHERE id=?', (original['id'],)).fetchone()[0])
                document.update(script='Final revision', status='published')
                db.execute('UPDATE web_shorts SET document=? WHERE id=?', (json.dumps(document), original['id']))
                future = pool.submit(edit)
                self.assertTrue(started.wait(2))
            with self.assertRaises(web_store.PublishedScriptLocked):
                future.result(timeout=5)
        saved = self.store.get_short(original['id'])
        self.assertEqual(saved['script'], 'Final revision')
        self.assertEqual(saved['status'], 'published')

    def test_unknown_id_stays_key_error(self):
        with self.assertRaises(KeyError):
            self.store.patch_short(9999, {'script': 'Missing', 'status': 'published'})

    def test_metrics_append_does_not_modify_published_short(self):
        original = self.store.create_short({'title': 'Sample', 'status': 'published'})
        metric = self.store.append_metric(original['id'], {'observed_at': '2026-01-01T00:00:00Z', 'views': 12})
        self.assertEqual(self.store.list_metrics(original['id']), [metric])
        self.assertEqual(self.store.get_short(original['id']), original)


class PublicationHTTPTests(unittest.TestCase):
    setUp = test_web.WebTests.setUp
    request = test_web.WebTests.request
    login = test_web.WebTests.login
    stop = test_web.WebTests.stop

    def test_new_shell_routes_are_exact_and_keep_old_urls(self):
        for path in ('/videos', '/references', '/social', '/scripts'):
            with self.subTest(path=path):
                status, headers, content = self.request('GET', path)
                self.assertEqual(status, 200)
                self.assertEqual(content, (self.root / 'static/index.html').read_bytes())
                self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        for path in ('/videos/extra', '/references/extra'):
            self.assertEqual(self.request('GET', path, headers={'Authorization': f'Bearer {TEST_TOKEN}'})[0], 404)

    def test_bearer_and_csrf_session_receive_explicit_conflict(self):
        session, _, _ = self.login()
        for headers in ({'Authorization': f'Bearer {TEST_TOKEN}'}, session):
            with self.subTest(auth='bearer' if 'Authorization' in headers else 'session'):
                status, _, original = self.request('POST', '/v1/shorts', {
                    'title': 'Sample', 'script': 'Final', 'status': 'published',
                }, headers)
                self.assertEqual(status, 201, original)
                path = '/v1/shorts/' + str(original['id'])
                status, response_headers, body = self.request('PATCH', path, {'script': 'Changed'}, headers)
                self.assertEqual((status, body), (409, {'error': 'published_script_locked'}))
                self.assertEqual(response_headers['Cache-Control'], 'no-store')
                self.assertEqual(self.request('GET', path, headers=headers)[2], original)

    def test_published_http_mutations_are_atomic_for_both_auth_modes(self):
        session, _, _ = self.login()
        for headers in ({'Authorization': f'Bearer {TEST_TOKEN}'}, session):
            original = self.request('POST', '/v1/shorts', {'title': 'Sample', 'script': 'Final', 'status': 'published'}, headers)[2]
            path = '/v1/shorts/' + str(original['id'])
            for fields in ({'status': 'draft'}, {'status': 'review'}, {'status': 'ready'}, {'script': 'Changed', 'status': 'draft', 'title': 'Rejected'}, {'script': 'Final', 'status': 'draft'}, {'script': 'Changed', 'status': 'published'}, {'script': ''}):
                with self.subTest(fields=fields, session='Cookie' in headers):
                    status, _, body = self.request('PATCH', path, fields, headers)
                    self.assertEqual((status, body), (409, {'error': 'published_script_locked'}))
                    self.assertEqual(self.request('GET', path, headers=headers)[2], original)
            status, _, body = self.request('PATCH', '/v1/shorts/9999', {'script': 'Missing'}, headers)
            self.assertEqual((status, body), (404, {'error': 'not_found'}))

    def test_publish_final_revision_resend_metadata_and_metrics(self):
        session, _, _ = self.login()
        for headers in ({'Authorization': f'Bearer {TEST_TOKEN}'}, session):
            original = self.request('POST', '/v1/shorts', {'title': 'Sample', 'script': 'Draft'}, headers)[2]
            path = '/v1/shorts/' + str(original['id'])
            status, _, draft = self.request('PATCH', path, {'script': 'Edited draft'}, headers)
            self.assertEqual(status, 200, draft)
            self.assertEqual(draft['script'], 'Edited draft')
            script = 'Final résumé\n  spacing\n' + 'x' * 90000
            status, _, published = self.request('PATCH', path, {'script': script, 'status': 'published'}, headers)
            self.assertEqual(status, 200, published)
            self.assertEqual(published['script'], script)
            self.assertEqual(published['status'], 'published')
            for fields in ({'script': script, 'status': 'published'}, {'title': 'Metadata', 'notes': 'Editable', 'tags': ['sample'], 'description': 'New description'}):
                status, _, saved = self.request('PATCH', path, fields, headers)
                self.assertEqual(status, 200, saved)
                self.assertEqual(saved['script'], script)
                self.assertEqual(saved['status'], 'published')
                for key, value in fields.items():
                    self.assertEqual(saved[key], value)
                self.assertEqual(self.request('GET', path, headers=headers)[2], saved)
            metric = {'observed_at': '2026-01-01T00:00:00Z', 'views': 12, 'source': 'manual' if 'Cookie' in headers else 'agent'}
            status, _, added = self.request('POST', path + '/metrics', metric, headers)
            self.assertEqual(status, 201, added)
            self.assertEqual(self.request('GET', path + '/metrics', headers=headers)[2]['items'], [added])
            self.assertEqual(self.request('GET', path, headers=headers)[2], saved)
            self.assertEqual(self.request('PATCH', path, {'script': 'Changed'}, headers)[0], 409)

    def test_csrf_and_validation_precede_lock_conflict(self):
        session, _, _ = self.login()
        original = self.request('POST', '/v1/shorts', {'title': 'Sample', 'status': 'published'}, session)[2]
        path = '/v1/shorts/' + str(original['id'])
        self.assertEqual(self.request('PATCH', path, {'script': 'Changed'})[0], 401)
        for omitted in ('Origin', 'X-CSRF-Token'):
            headers = {key: value for key, value in session.items() if key != omitted}
            status, _, body = self.request('PATCH', path, {'notes': 'Denied'}, headers)
            self.assertEqual((status, body), (403, {'error': 'csrf_failed'}))
        for payload in ({'script': None}, {'script': 'x' * 100001}, {'status': 'invalid'}, {'unknown': 'field'}):
            self.assertEqual(self.request('PATCH', path, payload, session)[0], 400)
        self.assertEqual(self.request('GET', path, headers=session)[2], original)
