"""Regression checks for the three-choice per-item scheduling interface.

This checks repository integration without requiring Node.js on the Pi.
It does not replace an actual JavaScript parser or browser acceptance test.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SchedulingUIIntegrationTests(unittest.TestCase):
    def test_exactly_three_exclusive_radio_choices(self):
        source = (ROOT / "static" / "schedule-ui.js").read_text()
        choices = re.findall(r'name="schedule-choice" value="([^"]+)"', source)
        self.assertEqual(choices, ["always", "window", "recurring"])
        self.assertIn("input[name=\"schedule-choice\"]:checked", source)

    def test_always_clears_schedule_without_disabling_playlist_item(self):
        source = (ROOT / "static" / "schedule-ui.js").read_text()
        self.assertIn("schedule_enabled:false", source)
        self.assertIn("schedule_start_date:null", source)
        self.assertIn("schedule_end_time:null", source)
        self.assertNotRegex(source, r"(?<!schedule_)enabled\\s*:\\s*false")

    def test_required_fields_change_by_choice(self):
        source = (ROOT / "static" / "schedule-ui.js").read_text()
        self.assertIn("required=mode==='window'", source)
        self.assertIn("required=mode==='window'||mode==='recurring'", source)
        self.assertIn("mode==='recurring'&&!weekdays.length", source)

    def test_loader_has_updated_cache_key(self):
        loader = (ROOT / "static" / "admin-render.js").read_text()
        self.assertIn("/static/schedule-ui.js?v=dev-schedule-3", loader)
        self.assertIn("window.addEventListener('load'", loader)


if __name__ == "__main__":
    unittest.main()
