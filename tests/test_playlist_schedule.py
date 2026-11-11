import unittest

from fastapi import HTTPException

from pi_player.playlist_schedule import export_item_schedule, import_item_schedule


class PortableScheduleTests(unittest.TestCase):
    def test_scheduled_window_roundtrip(self):
        original = {
            "schedule_enabled": 1, "schedule_mode": "window",
            "schedule_start_date": "2026-11-12", "schedule_end_date": "2026-11-14",
            "schedule_start_time": "06:00", "schedule_end_time": "18:00",
            "schedule_weekdays": "0,1,2,3,4,5,6",
        }
        exported = export_item_schedule(original)
        self.assertEqual(import_item_schedule(exported), (1, "window", "2026-11-12", "2026-11-14", "0,1,2,3,4,5,6", "06:00", "18:00"))

    def test_recurring_roundtrip(self):
        original = {
            "schedule_enabled": 1, "schedule_mode": "recurring",
            "schedule_start_date": None, "schedule_end_date": None,
            "schedule_start_time": "08:00", "schedule_end_time": "11:00",
            "schedule_weekdays": "0,2,4",
        }
        self.assertEqual(import_item_schedule(export_item_schedule(original)),
                         (1, "recurring", None, None, "0,2,4", "08:00", "11:00"))

    def test_old_package_defaults_to_always(self):
        self.assertEqual(import_item_schedule({"enabled": True}),
                         (0, "recurring", None, None, "0,1,2,3,4,5,6", None, None))

    def test_untrusted_schedule_rejected(self):
        valid = export_item_schedule({
            "schedule_enabled": 1, "schedule_mode": "window",
            "schedule_start_date": "2026-11-12", "schedule_end_date": "2026-11-14",
            "schedule_start_time": "06:00", "schedule_end_time": "18:00",
        })
        invalid = [
            {**valid, "schedule_mode": "invalid"},
            {**valid, "schedule_end_date": "2026-11-11"},
            {**valid, "schedule_end_time": "bad"},
            {**valid, "schedule_weekdays": [9]},
            {**valid, "schedule_start_date": None},
            {**valid, "schedule_start_time": None},
            {**valid, "schedule_weekdays": "0,1"},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(HTTPException):
                    import_item_schedule(payload)


if __name__ == "__main__":
    unittest.main()
