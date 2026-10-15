"""Password hashing and session tokens. Author: gurvinny"""
import hashlib
import unittest

import _support  # noqa: F401  (path setup)

from spectre.auth import hash_password, new_session_token, verify_password


class TestAuth(unittest.TestCase):

    def test_hash_is_pbkdf2_sha256_at_200k_iterations(self):
        # Pins the work factor: a silent drop in iterations is a real downgrade.
        h, salt = hash_password("correct horse", "00" * 16)
        expected = hashlib.pbkdf2_hmac("sha256", b"correct horse",
                                       bytes(16), 200_000).hex()
        self.assertEqual((h, salt), (expected, "00" * 16))

    def test_new_salt_per_hash(self):
        (h1, s1), (h2, s2) = hash_password("pw"), hash_password("pw")
        self.assertNotEqual(s1, s2)
        self.assertNotEqual(h1, h2)
        self.assertEqual(len(bytes.fromhex(s1)), 16)

    def test_verify_accepts_right_and_rejects_wrong(self):
        h, salt = hash_password("hunter22")
        self.assertTrue(verify_password("hunter22", h, salt))
        self.assertFalse(verify_password("hunter23", h, salt))
        self.assertFalse(verify_password("", h, salt))
        self.assertFalse(verify_password("hunter22", h, "11" * 16))

    def test_unicode_password_roundtrips(self):
        h, salt = hash_password("pässwörd✓")
        self.assertTrue(verify_password("pässwörd✓", h, salt))

    def test_session_tokens_are_long_and_unique(self):
        tokens = {new_session_token() for _ in range(200)}
        self.assertEqual(len(tokens), 200)
        self.assertTrue(all(len(t) >= 43 for t in tokens))


if __name__ == "__main__":
    unittest.main()
