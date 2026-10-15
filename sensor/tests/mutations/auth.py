"""Password hashing: a weakened KDF still logs you in, so only tests see it."""
TARGET = "spectre/auth.py"
TESTS = "tests/test_auth.py"

MUTATIONS = [
    ("work-factor-dropped",
     "_ITERATIONS = 200_000", "_ITERATIONS = 1_000",
     "test_hash_is_pbkdf2_sha256_at_200k_iterations"),
    ("static-salt",
     "salt = salt or secrets.token_hex(16)", 'salt = salt or "00" * 16',
     "test_new_salt_per_hash"),
    ("verify-always-true",
     "return hmac.compare_digest(candidate, expected_hash)", "return True",
     "test_verify_accepts_right_and_rejects_wrong"),
    ("short-tokens",
     "return secrets.token_urlsafe(32)", "return secrets.token_urlsafe(8)",
     "test_session_tokens_are_long_and_unique"),
]
SURVIVORS = {}
