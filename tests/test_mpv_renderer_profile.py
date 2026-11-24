import unittest
from pi_player.mpv_player import renderer_arguments
from pi_player.mpv_scope_launcher import ScopedMpvLauncher


class RendererProfileTests(unittest.TestCase):
    def test_silent_software_profile(self):
        args = renderer_arguments(muted=True, loop=False)
        for value in ("--hwdec=no", "--audio=no", "--fullscreen=yes",
                      "--gpu-context=wayland", "--loop-file=no"):
            self.assertIn(value, args)

    def test_audible_loop_preserves_settings(self):
        args = renderer_arguments(muted=False, loop=True)
        self.assertIn("--mute=no", args)
        self.assertIn("--loop-file=inf", args)
        self.assertNotIn("--audio=no", args)

    def test_scope_reuses_profile(self):
        argv = ScopedMpvLauncher.scope_command(
            "pi-player-mpv-" + "a" * 32 + ".scope", 9,
            muted=True, loop=False)
        for value in renderer_arguments(muted=True, loop=False):
            self.assertIn(value, argv)

    def test_rejects_nonboolean_options(self):
        with self.assertRaises(ValueError):
            renderer_arguments(muted="false", loop=False)
