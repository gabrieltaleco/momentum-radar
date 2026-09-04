import os
import unittest
from unittest.mock import patch

from src import auth


class AuthTests(unittest.TestCase):
    def setUp(self):
        auth._sessions.clear()
        auth._failed_attempts.clear()

    def test_credentials_are_required_and_compare_without_plaintext_logs(self):
        with patch.dict(os.environ, {"RADAR_AUTH_USERNAME": "owner", "RADAR_AUTH_PASSWORD": "correct horse"}, clear=False):
            self.assertTrue(auth.verify_credentials("owner", "correct horse"))
            self.assertFalse(auth.verify_credentials("owner", "wrong"))
            self.assertFalse(auth.verify_credentials("other", "correct horse"))

    def test_session_expires_and_can_be_deleted(self):
        with patch.dict(os.environ, {"RADAR_AUTH_PASSWORD": "secret"}, clear=False):
            token, expires = auth.create_session("admin", now=100.0)
            self.assertGreater(expires, 100)
            self.assertEqual(auth.session_for(token, now=100.0).username, "admin")
            self.assertIsNone(auth.session_for(token, now=100.0 + auth.SESSION_TTL_SECONDS + 1))
            auth.delete_session(token)
            self.assertIsNone(auth.session_for(token, now=100.0))

    def test_five_failed_attempts_lock_an_address(self):
        for _ in range(auth.MAX_LOGIN_ATTEMPTS):
            auth.record_failed_login("127.0.0.1", now=10.0)
        self.assertFalse(auth.login_allowed("127.0.0.1", now=10.0))
        self.assertTrue(auth.login_allowed("127.0.0.1", now=10.0 + auth.LOCKOUT_SECONDS + 1))

    def test_failed_attempts_accumulate_before_lock_even_when_spaced(self):
        for attempt in range(auth.MAX_LOGIN_ATTEMPTS):
            now = 20.0 + attempt * 30.0
            self.assertTrue(auth.login_allowed("127.0.0.1", now=now))
            auth.record_failed_login("127.0.0.1", now=now)
        self.assertFalse(auth.login_allowed("127.0.0.1", now=140.0))

    def test_cookie_parser_handles_only_the_named_cookie(self):
        self.assertEqual(auth.parse_cookie("theme=dark; radar_session=abc123; other=x"), "abc123")
        self.assertIsNone(auth.parse_cookie("theme=dark"))

    def test_missing_password_requires_setup(self):
        with patch.dict(os.environ, {"RADAR_AUTH_PASSWORD": ""}, clear=False):
            self.assertTrue(auth.setup_required())


if __name__ == "__main__":
    unittest.main()
