"""Reference catalog acceptance tests; isolated temporary DB, never production."""
import unittest
from synthetic_credentials import TEST_PASSWORD, TEST_TOKEN
import threading
import json
import subprocess
import shutil
from pathlib import Path
import test_web
import api_server


class ReferenceTests(unittest.TestCase):
    setUp = test_web.WebTests.setUp
    stop = test_web.WebTests.stop
    request = test_web.WebTests.request
    login = test_web.WebTests.login
    bearer = {'Authorization': f'Bearer {TEST_TOKEN}'}

    def item(self, **changes):
        item = dict(source_id='SAMPLE00001', channel_id='UC_SYNTHETIC_CHANNEL', channel_name='Test channel',
                    channel_url='https://www.youtube.com/@sample_account', content_type='short',
                    title='<img src=x onerror=alert(1)> A factual title',
                    url='https://www.youtube.com/shorts/SAMPLE00001',
                    summary='Title-based hypothesis, not a transcript.', topic='Science',
                    agent_angle='Original explanation, not a copied script',
                    evidence_basis='title/description', observed_at='2026-10-29T12:00:00Z')
        return {**item, **changes}

    def run_info(self):
        return dict(channel_id='UC_SYNTHETIC_CHANNEL', channel_name='Test channel',
                    source_url='https://www.youtube.com/@sample_account/shorts',
                    canonical_url='https://www.youtube.com/@sample_account',
                    observed_at='2026-10-29T12:00:00Z', status='partial',
                    notes='Posts not inspected', counts={'short': 999})

    def test_import_list_detail_upsert_separate_from_owned(self):
        before = self.request('GET', '/v1/channels', headers=self.bearer)[2]
        payload = {'items': [self.item()], 'run': self.run_info()}
        status, _, result = self.request('POST', '/v1/references/import', payload, self.bearer)
        self.assertEqual(status, 200, result)
        self.assertEqual(result, {'imported': 1, 'total': 1})
        rows = self.request('GET', '/v1/references', headers=self.bearer)[2]['items']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['title'], payload['items'][0]['title'])
        self.assertIsNone(row['views'])
        self.assertIsNone(row['likes'])
        self.assertIsNone(row['published_at'])
        self.assertEqual(self.request('GET', '/v1/references/' + str(row['id']), headers=self.bearer)[2], row)
        payload['items'][0]['views'] = 1200
        payload['items'][0]['views_approximate'] = True
        payload['items'][0]['views_text'] = '1.2K'
        self.assertEqual(self.request('POST', '/v1/references/import', payload, self.bearer)[2], {'imported': 1, 'total': 1})
        updated = self.request('GET', '/v1/references', headers=self.bearer)[2]['items'][0]
        self.assertEqual((updated['id'], updated['views'], updated['views_approximate']), (row['id'], 1200, True))
        self.assertEqual(self.request('GET', '/v1/shorts', headers=self.bearer)[2], {'items': []})
        self.assertEqual(self.request('GET', '/v1/channels', headers=self.bearer)[2], before)


    def test_status_filters_posts_and_restart(self):
        status, _, empty = self.request('GET', '/v1/references/status', headers=self.bearer)
        self.assertEqual(status, 200)
        self.assertEqual(empty, {'latest_run': None, 'total': 0, 'counts': {'short': 0, 'video': 0, 'live': 0, 'post': 0}})
        post = self.item(source_id='UgkxTestPost', content_type='post', url='https://www.youtube.com/post/UgkxTestPost', topic='Community', likes=0)
        payload = {'items': [self.item(), post, post], 'run': self.run_info()}
        self.assertEqual(self.request('POST', '/v1/references/import', payload, self.bearer)[2], {'imported': 2, 'total': 2})
        result = self.request('GET', '/v1/references/status', headers=self.bearer)[2]
        self.assertEqual(result['counts'], {'short': 1, 'video': 0, 'live': 0, 'post': 1})
        self.assertEqual(result['latest_run']['counts'], {'short': 999})
        self.assertEqual(result['latest_run']['status'], 'partial')
        self.assertEqual(len(self.request('GET', '/v1/references?q=community&type=post', headers=self.bearer)[2]['items']), 1)
        self.assertEqual(self.request('GET', '/v1/references?q=missing', headers=self.bearer)[2], {'items': []})
        self.assertEqual(self.request('GET', '/v1/references?type=script', headers=self.bearer)[0], 400)
        self.assertEqual(self.request('GET', '/v1/references/999', headers=self.bearer)[0], 404)
        self.assertEqual(self.request('PATCH', '/v1/references/1', {}, self.bearer)[0], 405)
        self.stop()
        self.server = api_server.create_http_server(self.store, TEST_TOKEN, '127.0.0.1', 0, root=self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.assertEqual(self.request('GET', '/v1/references/status', headers=self.bearer)[2], result)

    def test_public_metadata_basis_and_legacy_channel_url(self):
        run = {**self.run_info(), 'source_url': 'https://www.youtube.com/sample_account'}
        item = self.item(evidence_basis='public_title_description', published_at='2026-10-29')
        status, _, body = self.request('POST', '/v1/references/import', {'items': [item], 'run': run}, self.bearer)
        self.assertEqual(status, 200, body)
        row = self.request('GET', '/v1/references', headers=self.bearer)[2]['items'][0]
        self.assertEqual(row['evidence_basis'], 'public_title_description')
        self.assertEqual(row['published_at'], '2026-10-29')

    def test_browser_reference_library(self):
        import os
        if os.environ.get('RUN_BROWSER_TESTS') != '1':
            self.skipTest('Optional browser QA: set RUN_BROWSER_TESTS=1')
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.skipTest('Optional browser QA requires Python Playwright and Chromium')
        project = Path(api_server.__file__).parent
        for filename in ('index.html', 'app.js', 'style.css'):
            shutil.copyfile(project / 'static' / filename, self.root / 'static' / filename)
        items = [self.item(views=1200, views_approximate=True, published_at='2026-10-29', evidence_basis='public_title_description'),
                 self.item(source_id='aaaaaaaaaaa', url='https://youtu.be/aaaaaaaaaaa', title='Exact video', content_type='video', views=5, likes=0, published_at='2026-10-30'),
                 self.item(source_id='UgkxTestPost', url='https://www.youtube.com/post/UgkxTestPost', title='Community update', content_type='post', topic='Community')]
        self.assertEqual(self.request('POST', '/v1/references/import', {'items': items, 'run': self.run_info()}, self.bearer)[0], 200)
        session, _, _ = self.login()
        origin = 'http://127.0.0.1:' + str(self.server.server_address[1])
        with sync_playwright() as pw:
            executable = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE') or pw.chromium.executable_path
            if not Path(executable).is_file():
                self.skipTest('Optional browser QA requires an installed Chromium browser')
            browser = pw.chromium.launch(executable_path=executable, headless=True)

            context = browser.new_context(viewport={'width': 1365, 'height': 900})
            name, value = session['Cookie'].split('=', 1)
            context.add_cookies([{'name': name, 'value': value, 'url': origin}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('https://**/*', lambda route: route.abort())
            page.goto(origin)
            page.locator('#workspace').wait_for(state='visible')
            page.locator('#new-short').click()
            page.fill('#short-title', 'Unsaved owned draft')
            page.fill('#script', 'Keep my original script')
            # Cancelling navigation preserves the entire unsaved draft.
            page.once('dialog', lambda dialog: dialog.dismiss())
            page.locator('#library-references').click(timeout=2000)
            self.assertTrue(page.locator('#detail').is_visible())
            self.assertEqual(page.input_value('#short-title'), 'Unsaved owned draft')
            self.assertEqual(page.input_value('#script'), 'Keep my original script')
            # Explicitly accepting discards it and opens the external catalog.
            page.once('dialog', lambda dialog: dialog.accept())
            page.locator('#library-references').click(timeout=2000)
            page.locator('#reference-list button').first.wait_for()
            self.assertEqual(page.locator('#reference-list button').count(), 3)
            self.assertIn('parcial', page.locator('#reference-notice').inner_text().lower())
            page.select_option('#reference-sort', 'date')
            self.assertIn('Exact video', page.locator('#reference-list button').first.inner_text())
            page.select_option('#reference-sort', 'views')
            page.locator('#reference-list button').first.click()
            self.assertIn('<img src=x', page.locator('#reference-title').inner_text())
            self.assertEqual(page.locator('#reference-title img').count(), 0)
            self.assertIn('aproximadas', page.locator('#reference-metrics').inner_text())
            self.assertIn('título/descripción', page.locator('#reference-basis').inner_text())
            self.assertIn('2026-10-29', page.locator('#reference-dates').inner_text())
            self.assertIn('Original explanation', page.locator('#reference-angle').inner_text())
            page.screenshot(path=str(self.root / 'references-desktop.png'), full_page=True)
            self.assertEqual(page.locator('#reference-preview iframe').count(), 0)
            page.get_by_role('button', name='Cargar referencia de YouTube').click()
            self.assertIn('/embed/SAMPLE00001', page.locator('#reference-preview iframe').get_attribute('src'))
            page.fill('#reference-search', 'community')
            self.assertEqual(page.locator('#reference-list button').count(), 1)
            page.locator('#reference-list button').click()
            self.assertEqual(page.locator('#reference-preview iframe').count(), 0)
            self.assertEqual(page.locator('#reference-preview button').count(), 0)
            self.assertIn('/post/UgkxTestPost', page.locator('#reference-open').get_attribute('href'))
            self.assertIn('no disponibles', page.locator('#reference-metrics').inner_text())
            page.fill('#reference-search', '')
            page.select_option('#reference-type', 'video')
            self.assertEqual(page.locator('#reference-list button').count(), 1)
            page.locator('#reference-list button').click()
            self.assertIn('5 visualizaciones', page.locator('#reference-metrics').inner_text())
            self.assertIn('0 Me gusta', page.locator('#reference-metrics').inner_text())
            page.set_viewport_size({'width': 390, 'height': 844})
            self.assertTrue(page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.screenshot(path=str(self.root / 'references-mobile.png'), full_page=True)
            page.fill('#reference-search', 'no-such-title')
            self.assertEqual(page.locator('#reference-list button').count(), 0)
            self.assertIn('No hay referencias', page.locator('#reference-list').inner_text())
            page.locator('#library-owned').click()
            self.assertTrue(page.locator('#new-short').is_visible())
            self.assertFalse(page.locator('#reference-detail').is_visible())
            self.assertFalse(page.locator('#detail').is_visible())
            page.locator('#new-short').click()
            self.assertEqual(page.input_value('#short-title'), '')
            self.assertEqual(page.input_value('#script'), '')
            self.assertEqual(errors, [])
            browser.close()


    def test_validation_atomicity_and_bearer_only_auth(self):
        payload = {'items': [self.item()], 'run': self.run_info()}
        self.assertEqual(self.request('GET', '/v1/references')[0], 401)
        self.assertEqual(self.request('POST', '/v1/references/import', payload)[0], 401)
        session, _, _ = self.login()
        self.assertEqual(self.request('POST', '/v1/references/import', payload, session)[0], 403)
        self.assertEqual(self.request('GET', '/v1/references', headers=session)[0], 200)
        bad = [dict(views=-1), dict(views=True), dict(views=1.1), dict(views=10**40),
               dict(likes='1'), dict(views_approximate='false'), dict(duration_seconds=-1),
               dict(duration_seconds=10**400), dict(content_type='script'), dict(title=''),
               dict(source_id='wrong'), dict(observed_at='yesterday'), dict(published_at='tomorrow'),
               dict(url='javascript:alert(1)'), dict(url='https://youtube.com.evil.test/watch?v=SAMPLE00001'),
               dict(url='https://youtube.com:444/watch?v=SAMPLE00001'),
               dict(url='https://youtube.com/watch?v=SAMPLE00001&v=SAMPLE00001'),
               dict(url='https://user@youtube.com/watch?v=SAMPLE00001'),
               dict(url='https://youtube.com/watch?v=SAMPLE00001\n'),
               dict(thumbnail_url='https://evil.test/image.jpg'), dict(channel_url='https://evil.test/@sample_account'),
               dict(extra='not stored'), dict(title='\ud800')]
        for changes in bad:
            with self.subTest(changes=str(changes)[:90]):
                invalid = {'items': [self.item(), self.item(**changes)], 'run': self.run_info()}
                self.assertEqual(self.request('POST', '/v1/references/import', invalid, self.bearer)[0], 400)
                self.assertEqual(self.request('GET', '/v1/references', headers=self.bearer)[2], {'items': []})
        for payload in [{}, {'items': []}, {'items': 'bad', 'run': self.run_info()},
                        {'items': [self.item()], 'run': {**self.run_info(), 'status': 'invented'}},
                        {'items': [self.item()], 'run': {**self.run_info(), 'counts': {'short': -1}}}]:
            self.assertEqual(self.request('POST', '/v1/references/import', payload, self.bearer)[0], 400)
        self.assertEqual(self.request('POST', '/v1/references/import', 'x' * (256 * 1024 + 1), self.bearer)[0], 413)


if __name__ == '__main__':
    unittest.main()
