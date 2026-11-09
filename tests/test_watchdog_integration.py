"""Offline watchdog integration test. Does NOT operate on production services.

Runs a copied shell watchdog with mocked curl/pgrep/systemctl, a fake
GPU monitor, a fake recovery gate and a temporary log path.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy/pi-player-watchdog.sh"


class WatchdogIntegration(unittest.TestCase):
    def exercise(self, *, api_ok=True, chromium=True, stalled=False, gpu_exit=0, gate_allow=True, followup=None):
        with tempfile.TemporaryDirectory(prefix="pi-player-watchdog-test-") as directory:
            root = Path(directory)
            fakebin = root / "bin"
            fakebin.mkdir()
            journal = root / "actions.log"
            log = root / "watchdog.log"
            gate = root / "gate.py"
            gpu = root / "gpu.py"
            gate.write_text("import os,sys\nprint('mock gate',sys.argv[1])\nsys.exit(0 if os.environ['MOCK_GATE']=='allow' else 1)\n")
            gpu.write_text("import os,sys\nprint('mock gpu sample')\nsys.exit(int(os.environ['MOCK_GPU_EXIT']))\n")
            for name, script in {
                "curl": '#!/bin/sh\ncase "$*" in\n  *api/health*) test "$MOCK_API" = ok ;;\n  *api/player/watchdog*) printf \'{"stalled":%s,"heartbeat_age_seconds":3.5}\\n\' "$MOCK_STALLED" ;;\n  *) exit 9 ;;\nesac\n',
                "pgrep": '#!/bin/sh\ntest "$MOCK_CHROMIUM" = yes\n',
                "systemctl": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$MOCK_ACTION_LOG"\n',
            }.items():
                path = fakebin / name
                path.write_text(script)
                path.chmod(0o755)
            script = SOURCE.read_text()
            script = script.replace("LOG=/var/log/pi-player/watchdog.log", f"LOG={log}")
            script = script.replace("GPU_MONITOR=/opt/pi-player-rk/deploy/pi-player-gpu-watchdog.py", f"GPU_MONITOR={gpu}")
            script = script.replace("RECOVERY_GATE=/opt/pi-player-rk/deploy/pi-player-recovery-gate.py", f"RECOVERY_GATE={gate}")
            script = script.replace("PENDING_KIOSK=/var/lib/pi-player/kiosk-recovery-pending", f"PENDING_KIOSK={root / 'pending'}")
            testfile = root / "watchdog.sh"
            testfile.write_text(script)
            env = dict(os.environ,
                       PATH=f"{fakebin}:{os.environ['PATH']}",
                       MOCK_API="ok" if api_ok else "fail",
                       MOCK_CHROMIUM="yes" if chromium else "no",
                       MOCK_STALLED="true" if stalled else "false",
                       MOCK_GPU_EXIT=str(gpu_exit),
                       MOCK_GATE="allow" if gate_allow else "deny",
                       MOCK_ACTION_LOG=str(journal))
            result = subprocess.run(["bash", str(testfile)], env=env, capture_output=True, text=True, timeout=10)
            if followup is not None:
                env["MOCK_STALLED"] = "true" if followup else "false"
                follow = subprocess.run(["bash", str(testfile)], env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(follow.returncode, 0, follow.stdout + follow.stderr)
                self.assertFalse((root / "pending").exists(), "pending verification marker must be consumed")
            actions = journal.read_text().splitlines() if journal.exists() else []
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return actions, log.read_text() if log.exists() else result.stdout

    def test_healthy_no_restart(self):
        actions, _ = self.exercise()
        self.assertEqual(actions, [])

    def test_api_failed_authorized(self):
        actions, _ = self.exercise(api_ok=False)
        self.assertEqual(actions, ["--no-block restart pi-player-api.service"])

    def test_api_failed_denied(self):
        actions, _ = self.exercise(api_ok=False, gate_allow=False)
        self.assertEqual(actions, [])

    def test_chromium_missing_authorized(self):
        actions, _ = self.exercise(chromium=False)
        self.assertEqual(actions, ["--no-block restart getty@tty1.service"])

    def test_chromium_missing_denied(self):
        actions, _ = self.exercise(chromium=False, gate_allow=False)
        self.assertEqual(actions, [])

    def test_stalled_heartbeat_authorized(self):
        actions, _ = self.exercise(stalled=True)
        self.assertEqual(actions, ["--no-block restart getty@tty1.service"])

    def test_stalled_heartbeat_denied(self):
        actions, _ = self.exercise(stalled=True, gate_allow=False)
        self.assertEqual(actions, [])

    def test_gpu_threshold_authorized(self):
        actions, _ = self.exercise(gpu_exit=10)
        self.assertEqual(actions, ["--no-block restart getty@tty1.service"])

    def test_gpu_threshold_denied(self):
        actions, _ = self.exercise(gpu_exit=10, gate_allow=False)
        self.assertEqual(actions, [])

    def test_restart_verified_on_next_healthy_heartbeat(self):
        actions, logs = self.exercise(stalled=True, followup=False)
        self.assertEqual(actions, ["--no-block restart getty@tty1.service"])
        self.assertIn("Previous kiosk restart verified: fresh heartbeat reported", logs)

    def test_restart_unverified_on_next_stale_heartbeat(self):
        actions, logs = self.exercise(stalled=True, followup=True)
        self.assertEqual(actions, ["--no-block restart getty@tty1.service"])
        self.assertIn("Previous kiosk restart NOT verified:", logs)

    def test_gpu_monitor_error_no_restart(self):
        actions, _ = self.exercise(gpu_exit=2)
        self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
