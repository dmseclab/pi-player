import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class KioskLauncherTests(unittest.TestCase):
    def test_chromium_args_are_single_shell_command(self):
        script = (ROOT / "deploy" / "launch-kiosk.sh").read_text()
        lines = script.splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith('exec "$BROWSER"'))
        end = next(i for i in range(start, len(lines)) if lines[i].strip() == '"$URL"')
        command_lines = lines[start:end + 1]
        self.assertGreater(len(command_lines), 3)
        for line in command_lines[:-1]:
            self.assertTrue(line.rstrip().endswith("\\"),
                            f"Missing line continuation: {line!r}")
            self.assertFalse(line.rstrip().endswith("\\\\"),
                             f"Double-escaped line continuation: {line!r}")
        self.assertIn('--user-data-dir="$PROFILE_DIR"', script)
        self.assertIn("--kiosk", script)
        self.assertIn("--ozone-platform=wayland", script)


if __name__ == "__main__":
    unittest.main()
