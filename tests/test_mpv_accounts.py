"""Static separation contract: no account commands are executed."""
import unittest
from pathlib import Path


class AccountPlanTests(unittest.TestCase):
    def test_sysusers_proposal_does_not_touch_existing_kiosk_identity(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "deploy/pi-player-mpv.sysusers.conf").read_text()
        users = [line for line in text.splitlines()
                 if line and not line.lstrip().startswith("#")]
        self.assertTrue(any(line.startswith("u pi-player-mpv ") for line in users))
        self.assertTrue(any(line.startswith("u pi-player-broker ") for line in users))
        self.assertFalse(any(line.startswith("u pi ") for line in users))
        self.assertFalse(any(line.startswith("u pi-player ") for line in users))

    def test_broker_unit_requires_dedicated_account(self):
        root = Path(__file__).resolve().parents[1]
        unit = (root / "deploy/pi-player-mpv-broker.lab.service").read_text()
        self.assertIn("User=pi-player-broker", unit)
        self.assertIn("Group=pi-player-mpv", unit)
        self.assertIn("RuntimeDirectoryMode=0710", unit)


if __name__ == "__main__":
    unittest.main()
