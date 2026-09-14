import unittest

from pi_player.security import create_session, hash_password, read_session, verify_password


class SecurityTests(unittest.TestCase):
    def test_password_hash_roundtrip(self):
        stored = hash_password("secret")
        self.assertTrue(verify_password("secret", stored))
        self.assertFalse(verify_password("wrong", stored))

    def test_session_roundtrip(self):
        token = create_session("pi")
        self.assertEqual(read_session(token), "pi")
        self.assertIsNone(read_session(token + "tampered"))


if __name__ == "__main__":
    unittest.main()
