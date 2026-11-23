"""B3 cgroup evidence tests (uses disposable simulated control files)."""
import os
import tempfile
import unittest
from pathlib import Path

from pi_player.mpv_process_evidence import EvidenceError, inspect_cgroup


class CgroupEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("cgroup.events", "populated 0\nfrozen 0\n")
        self.write("cgroup.procs", "")

    def write(self, name, value):
        (self.root / name).write_text(value)

    def test_empty_cgroup_required_for_retirement(self):
        report = inspect_cgroup(str(self.root))
        self.assertTrue(report.empty)
        self.assertEqual(report.pids, ())

    def test_pid_present_is_never_empty(self):
        self.write("cgroup.events", "populated 1\n")
        self.write("cgroup.procs", "101\n102\n")
        report = inspect_cgroup(str(self.root))
        self.assertFalse(report.empty)
        self.assertEqual(report.pids, (101, 102))

    def test_conflicting_sources_fail_closed(self):
        self.write("cgroup.events", "populated 0\n")
        self.write("cgroup.procs", "101\n")
        self.assertFalse(inspect_cgroup(str(self.root)).empty)
        self.write("cgroup.events", "populated 1\n")
        self.write("cgroup.procs", "")
        self.assertFalse(inspect_cgroup(str(self.root)).empty)

    def test_missing_events_or_procs_denied(self):
        (self.root / "cgroup.events").unlink()
        with self.assertRaises(EvidenceError):
            inspect_cgroup(str(self.root))
        self.write("cgroup.events", "populated 0\n")
        (self.root / "cgroup.procs").unlink()
        with self.assertRaises(EvidenceError):
            inspect_cgroup(str(self.root))

    def test_malformed_or_duplicate_data_denied(self):
        for data in ("", "populated maybe\n", "populated 0\npopulated 1\n",
                     "populated 2\n"):
            self.write("cgroup.events", data)
            with self.subTest(data=data), self.assertRaises(EvidenceError):
                inspect_cgroup(str(self.root))
        self.write("cgroup.events", "populated 0\n")
        for data in ("1\n1\n", "0\n", "abc\n", "-4\n"):
            self.write("cgroup.procs", data)
            with self.subTest(procs=data), self.assertRaises(EvidenceError):
                inspect_cgroup(str(self.root))

    def test_symlink_control_files_denied(self):
        (self.root / "cgroup.events").unlink()
        (self.root / "real").write_text("populated 0\n")
        (self.root / "cgroup.events").symlink_to("real")
        with self.assertRaises(EvidenceError):
            inspect_cgroup(str(self.root))

    def test_untrusted_relative_directory_denied(self):
        with self.assertRaises(EvidenceError):
            inspect_cgroup("relative")


if __name__ == "__main__":
    unittest.main()
