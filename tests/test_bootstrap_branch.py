import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BootstrapBranchTests(unittest.TestCase):
    def test_single_branch_clone_can_fetch_explicit_branch(self):
        script = (ROOT / "bootstrap-install.sh").read_text()
        self.assertIn('"+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"', script)
        self.assertIn('"refs/remotes/origin/$BRANCH"', script)
        self.assertNotIn('fetch origin "$BRANCH"', script)

    def test_current_checkout_default(self):
        script = (ROOT / "bootstrap-install.sh").read_text()
        self.assertIn('PI_PLAYER_BRANCH:-', script)
        self.assertIn('symbolic-ref --quiet --short HEAD', script)
        self.assertIn('Pi Player source branch:', script)


if __name__ == "__main__":
    unittest.main()
