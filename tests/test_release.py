"""Portable release checks; all runtime state is synthetic and temporary."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import web_auth


class ReleaseTests(unittest.TestCase):
    def test_bootstrap_creates_private_credentials_and_empty_local_app(self):
        import hashlib
        import importlib.util
        import json
        import secrets
        import stat
        import tempfile
        from agency_store import AgencyStore
        from web_store import WebStore
        from web_auth import Auth
        self.assertIsNotNone(importlib.util.find_spec('bootstrap'), 'bootstrap.py is missing')
        import bootstrap
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            password = secrets.token_urlsafe(24)
            with patch('builtins.input', return_value='admin'), patch('getpass.getpass', side_effect=[password, password]) as prompt:
                bootstrap.setup(root)
            self.assertEqual(prompt.call_count, 2)
            admin_path = root / 'secrets/admin.json'
            token_path = root / 'secrets/api_token'
            admin = json.loads(admin_path.read_text())
            self.assertEqual(admin['algorithm'], 'scrypt')
            self.assertEqual(len(bytes.fromhex(admin['salt'])), 32)
            expected = hashlib.scrypt(password.encode(), salt=bytes.fromhex(admin['salt']), n=16384, r=8, p=1, dklen=64).hex()
            self.assertEqual(admin['password_hash'], expected)
            self.assertNotIn(password, admin_path.read_text())
            self.assertGreaterEqual(len(token_path.read_text().strip()), 43)
            if os.name == 'posix':
                self.assertEqual(stat.S_IMODE(admin_path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(token_path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(admin_path.parent.stat().st_mode), 0o700)
            self.assertEqual(json.loads((root / 'data/social-inventory.json').read_text())['accounts'], [])
            store = AgencyStore(root / 'data/shorts_agency.db')
            self.assertEqual(store.list_channels(), [])
            web = WebStore(store.database_path)
            self.assertEqual(web.list_shorts(), [])
            self.assertIsNotNone(Auth(web, root).login('admin', password))
            with web.connect() as db:
                db.execute("UPDATE templates SET name='Customized'")
            before = (admin_path.read_bytes(), token_path.read_bytes())
            with patch('getpass.getpass', side_effect=AssertionError('must preserve password')), patch('builtins.input', side_effect=AssertionError('must preserve username')):
                bootstrap.setup(root)
            self.assertEqual(before, (admin_path.read_bytes(), token_path.read_bytes()))
            self.assertTrue(all(t['name'] == 'Customized' for t in store.list_templates()))

    def test_bootstrap_rejects_password_confirmation_without_writing_secrets(self):
        import tempfile
        import bootstrap
        from synthetic_credentials import TEST_PASSWORD
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('builtins.input', return_value='admin'), patch('getpass.getpass', side_effect=[TEST_PASSWORD, 'different']):
                with self.assertRaisesRegex(ValueError, 'match'):
                    bootstrap.setup(root)
            self.assertFalse((root / 'secrets/admin.json').exists())
            self.assertFalse((root / 'secrets/api_token').exists())

    def test_bootstrap_refuses_echoing_password_fallback(self):
        import getpass
        import tempfile
        import warnings
        import bootstrap
        def unsafe_prompt(_):
            warnings.warn('No safe terminal', getpass.GetPassWarning)
            return 'not-a-real-password'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('builtins.input', return_value='admin'), patch('getpass.getpass', side_effect=unsafe_prompt):
                with self.assertRaises(getpass.GetPassWarning):
                    bootstrap.setup(root)
            self.assertFalse((root / 'secrets/admin.json').exists())

    def test_store_closes_connections(self):
        import gc
        import tempfile
        import warnings
        from agency_store import AgencyStore
        gc.collect()
        with tempfile.TemporaryDirectory() as directory, warnings.catch_warnings(record=True) as found:
            warnings.simplefilter('always', ResourceWarning)
            store = AgencyStore(Path(directory) / 'test.db')
            store.initialize()
            store.list_templates()
            gc.collect()
            self.assertEqual([str(w.message) for w in found if issubclass(w.category, ResourceWarning)], [])

    def test_image_templates_require_operator_selected_model(self):
        from agency_store import PROMPT_BLOCKS
        images = [p for p in PROMPT_BLOCKS if p['stage'] == 'image']
        self.assertTrue(images)
        for prompt in images:
            self.assertIn('{{image_model}}', prompt['prompt'])
            self.assertIn('available', prompt['prompt'])

    def test_launcher_fails_clearly_before_serving_missing_credentials(self):
        import json
        import tempfile
        import run_local
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'secrets').mkdir()
            token = root / 'secrets/api_token'
            with patch.object(run_local, 'ROOT', root), patch.object(run_local, 'TOKEN_FILE', token), patch.object(run_local, 'serve') as serve:
                with self.assertRaisesRegex(SystemExit, 'bootstrap.py'):
                    run_local.main()
                token.write_text('synthetic-test-token')
                with self.assertRaisesRegex(SystemExit, 'admin.json.*bootstrap.py'):
                    run_local.main()
                (root / 'secrets/admin.json').write_text('{}')
                with self.assertRaisesRegex(SystemExit, 'admin.json'):
                    run_local.main()
                serve.assert_not_called()
        self.assertTrue(os.access(Path(run_local.__file__), os.X_OK))

    def test_allowed_origins_are_local_by_default_and_env_configurable(self):
        self.assertTrue(callable(getattr(web_auth, 'allowed_origins', None)),
                        'origin configuration helper is missing')
        local = {'http://localhost:8765', 'http://127.0.0.1:8765'}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(web_auth.allowed_origins(), local)
        with patch.dict(os.environ, {'SHORTS_AGENCY_ORIGIN': 'https://agency.example'}, clear=True):
            self.assertEqual(web_auth.allowed_origins(), local | {'https://agency.example'})
        for bad in ['*', 'null', 'https://agency.example/path', 'https://user@agency.example', 'https://agency.example/', 'https://agency.example?x=1']:
            with self.subTest(origin=bad), patch.dict(os.environ, {'SHORTS_AGENCY_ORIGIN': bad}, clear=True):
                with self.assertRaises(ValueError):
                    web_auth.allowed_origins()
