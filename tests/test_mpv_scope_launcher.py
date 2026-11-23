"""Pure scope command and state tests. Never launches MPV/systemd."""
import os
import unittest
from unittest.mock import patch, Mock
from pathlib import Path

from pi_player.mpv_scope_launcher import ScopedMpvLauncher, ScopeError, ScopeHandle
from pi_player.mpv_fd_transport import ReceivedVideo


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.launcher = ScopedMpvLauncher()

    def test_scope_command_is_argument_only(self):
        unit = "pi-player-mpv-" + "a"*32 + ".scope"
        argv = self.launcher.scope_command(unit, 9, muted=True, loop=False)
        self.assertIn("--scope", argv)
        self.assertIn("--unit=" + unit, argv)
        self.assertEqual(argv[-1], "/proc/self/fd/9")
        self.assertIn("--fullscreen=yes", argv)
        self.assertIn("--wayland-app-id=" + unit[:-6], argv)
        self.assertNotIn("sh", argv)

    def test_scope_name_rejects_operator_commands(self):
        with self.assertRaises(ScopeError):
            self.launcher.scope_command("bad;command", 9, muted=True, loop=False)

    def test_invalid_fd_denied(self):
        unit = "pi-player-mpv-" + "f"*32 + ".scope"
        with self.assertRaises(ScopeError):
            self.launcher.scope_command(unit, 2, muted=True, loop=False)

    def test_stale_scope_cannot_reconcile(self):
        with self.assertRaises(ScopeError):
            self.launcher.reconcile_empty(
                ScopeHandle("a", "b", 1), group_empty=True, helper_exited=True)

    def test_same_scope_requires_exit_and_empty(self):
        handle = ScopeHandle("pi-player-mpv-"+"a"*32+".scope", "b", 123)
        process = Mock()
        process.poll.return_value = None
        self.launcher._handle = handle
        self.launcher._proc = process
        with self.assertRaises(ScopeError):
            self.launcher.reconcile_empty(
                handle, group_empty=True, helper_exited=True)
        process.poll.return_value = 0
        with self.assertRaises(ScopeError):
            self.launcher.reconcile_empty(
                handle, group_empty=False, helper_exited=True)
        self.launcher.reconcile_empty(
            handle, group_empty=True, helper_exited=True)
        self.assertIsNone(self.launcher._handle)


if __name__ == "__main__":
    unittest.main()
