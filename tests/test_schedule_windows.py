"""Boundary regression coverage for continuous date/time playlist windows.

Run with the project's Python test environment: pytest -q tests/test_schedule_windows.py
"""
from datetime import datetime, timezone

from pi_player.scheduling import schedule_matches, _finite_schedule_expired


def item():
    return {
        "schedule_enabled": True,
        "schedule_mode": "window",
        "schedule_start_date": "2026-11-05",
        "schedule_start_time": "00:00",
        "schedule_end_date": "2026-11-12",
        "schedule_end_time": "00:00",
        "schedule_weekdays": "0,1,2,3,4,5,6",
    }


def test_window_stays_on_during_intermediate_nights():
    scheduled = item()
    assert schedule_matches(scheduled, datetime(2026, 11, 11, 23, 59, 59))
    assert schedule_matches(scheduled, datetime(2026, 11, 7, 2, 0))


def test_window_start_inclusive_end_exclusive():
    scheduled = item()
    assert not schedule_matches(scheduled, datetime(2026, 11, 4, 23, 59, 59))
    assert schedule_matches(scheduled, datetime(2026, 11, 5, 0, 0))
    assert not schedule_matches(scheduled, datetime(2026, 11, 12, 0, 0))
    assert not _finite_schedule_expired(scheduled, datetime(2026, 11, 11, 23, 59, 59))
    assert _finite_schedule_expired(scheduled, datetime(2026, 11, 12, 0, 0))


def test_next_window_activates_on_same_midnight():
    old = item()
    new = {
        **item(),
        "schedule_start_date": "2026-11-12",
        "schedule_end_date": "2026-11-19",
    }
    changeover = datetime(2026, 11, 12, 0, 0)
    assert not schedule_matches(old, changeover)
    assert schedule_matches(new, changeover)


def test_legacy_recurring_still_uses_weekdays():
    scheduled = {
        **item(),
        "schedule_mode": "recurring",
        "schedule_start_date": None,
        "schedule_end_date": None,
        "schedule_start_time": "08:00",
        "schedule_end_time": "17:00",
        "schedule_weekdays": "0,1,2,3,4",
    }
    assert schedule_matches(scheduled, datetime(2026, 11, 9, 9, 0))
    assert not schedule_matches(scheduled, datetime(2026, 11, 8, 9, 0))
