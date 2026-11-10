"""Boundary and independent-asset regression tests for continuous scheduling.

Uses the application virtualenv, but not pytest:
  python -m unittest discover -s tests -p 'test_schedule_windows.py' -v
"""
import unittest
from datetime import datetime

from pi_player.scheduling import schedule_matches, _finite_schedule_expired


def window(start_date="2026-11-05", start_time="00:00",
           end_date="2026-11-12", end_time="00:00"):
    return {
        "schedule_enabled": True,
        "schedule_mode": "window",
        "schedule_start_date": start_date,
        "schedule_start_time": start_time,
        "schedule_end_date": end_date,
        "schedule_end_time": end_time,
        "schedule_weekdays": "0,1,2,3,4,5,6",
    }


class ScheduleWindowTests(unittest.TestCase):
    def test_intermediate_nights_eligible(self):
        asset = window()
        self.assertTrue(schedule_matches(asset, datetime(2026, 11, 11, 23, 59, 59)))
        self.assertTrue(schedule_matches(asset, datetime(2026, 11, 7, 2)))

    def test_start_inclusive_end_exclusive_and_expiry(self):
        asset = window()
        self.assertFalse(schedule_matches(asset, datetime(2026, 11, 4, 23, 59, 59)))
        self.assertTrue(schedule_matches(asset, datetime(2026, 11, 5, 0)))
        self.assertFalse(schedule_matches(asset, datetime(2026, 11, 12, 0)))
        self.assertFalse(_finite_schedule_expired(asset, datetime(2026, 11, 11, 23, 59, 59)))
        self.assertTrue(_finite_schedule_expired(asset, datetime(2026, 11, 12, 0)))

    def test_independent_assets_allow_gap(self):
        asset1 = window("2026-11-09", "06:00", "2026-11-11", "18:00")
        asset2 = window("2026-11-12", "06:00", "2026-11-19", "08:00")
        for moment, expected in (
            (datetime(2026, 11, 11, 17, 59), (True, False)),
            (datetime(2026, 11, 11, 18, 0), (False, False)),
            (datetime(2026, 11, 12, 5, 59), (False, False)),
            (datetime(2026, 11, 12, 6, 0), (False, True)),
        ):
            with self.subTest(moment=moment):
                self.assertEqual(
                    (schedule_matches(asset1, moment), schedule_matches(asset2, moment)),
                    expected,
                )

    def test_independent_assets_allow_overlap(self):
        asset1 = window("2026-11-09", "06:00", "2026-11-12", "08:00")
        asset2 = window("2026-11-12", "06:00", "2026-11-19", "08:00")
        at_overlap = datetime(2026, 11, 12, 7)
        self.assertTrue(schedule_matches(asset1, at_overlap))
        self.assertTrue(schedule_matches(asset2, at_overlap))

    def test_other_assets_are_unaffected(self):
        scheduled = window("2026-11-09", "06:00", "2026-11-11", "18:00")
        always = {"schedule_enabled": False}
        moment = datetime(2026, 11, 12, 2)
        self.assertFalse(schedule_matches(scheduled, moment))
        self.assertTrue(schedule_matches(always, moment))

    def test_recurring_weekdays_retained(self):
        recurring = {
            **window(),
            "schedule_mode": "recurring",
            "schedule_start_date": None,
            "schedule_end_date": None,
            "schedule_start_time": "08:00",
            "schedule_end_time": "17:00",
            "schedule_weekdays": "0,1,2,3,4",
        }
        self.assertTrue(schedule_matches(recurring, datetime(2026, 11, 9, 9)))
        self.assertFalse(schedule_matches(recurring, datetime(2026, 11, 8, 9)))


if __name__ == "__main__":
    unittest.main()
