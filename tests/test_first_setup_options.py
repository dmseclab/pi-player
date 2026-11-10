import unittest
from pydantic import ValidationError
from fastapi import HTTPException

from pi_player.appliance import FirstSetupRequest, _validate_support_user


class FirstTimeSetupOptionsTests(unittest.TestCase):
    def test_keep_existing_ssh_account_requires_no_support_credentials(self):
        request = FirstSetupRequest(
            bootstrap_username="pi", bootstrap_password="pi",
            admin_username="newadmin", admin_password="long-password-123",
            hostname="pi-player-lab",
        )
        self.assertFalse(request.create_support_user)
        self.assertIsNone(request.support_username)
        self.assertIsNone(request.support_password)

    def test_new_support_account_fields_can_be_supplied(self):
        request = FirstSetupRequest(
            bootstrap_username="pi", bootstrap_password="pi",
            admin_username="newadmin", admin_password="long-password-123",
            create_support_user=True,
            support_username="supporttech", support_password="long-password-456",
            hostname="pi-player-lab",
        )
        self.assertTrue(request.create_support_user)
        self.assertEqual(_validate_support_user(request.support_username), "supporttech")

    def test_reserved_support_user_rejected(self):
        with self.assertRaises(HTTPException):
            _validate_support_user("pi-player")


if __name__ == "__main__":
    unittest.main()
