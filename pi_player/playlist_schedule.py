"""Portable serialization of per-item playback scheduling.

Playlist packages are untrusted input. Validate before writing SQLite records.
Older v1 packages without schedule fields are imported as Always.
"""
from datetime import date, datetime, time

from fastapi import HTTPException


def export_item_schedule(record):
    raw = record.get("schedule_weekdays")
    days = [int(v) for v in raw.split(",") if v != ""] if raw else list(range(7))
    return {
        "schedule_enabled": bool(record.get("schedule_enabled", 0)),
        "schedule_mode": record.get("schedule_mode") or "recurring",
        "schedule_start_date": record.get("schedule_start_date"),
        "schedule_end_date": record.get("schedule_end_date"),
        "schedule_start_time": record.get("schedule_start_time"),
        "schedule_end_time": record.get("schedule_end_time"),
        "schedule_weekdays": days,
    }


def import_item_schedule(item):
    def invalid(message):
        raise HTTPException(status_code=400, detail=message)

    enabled = item.get("schedule_enabled", False)
    if not isinstance(enabled, bool):
        invalid("Invalid schedule enabled flag")
    mode = item.get("schedule_mode", "recurring")
    if mode not in ("recurring", "window"):
        invalid("Invalid schedule mode")

    dates = []
    for field in ("schedule_start_date", "schedule_end_date"):
        value = item.get(field)
        if value in (None, ""):
            dates.append(None)
        elif isinstance(value, str):
            try:
                dates.append(date.fromisoformat(value).isoformat())
            except ValueError:
                invalid("Invalid schedule date")
        else:
            invalid("Invalid schedule date")

    times = []
    for field in ("schedule_start_time", "schedule_end_time"):
        value = item.get(field)
        if value in (None, ""):
            times.append(None)
        elif isinstance(value, str):
            try:
                value_time = time.fromisoformat(value)
            except ValueError:
                invalid("Invalid schedule time")
            if value_time.tzinfo is not None:
                invalid("Timezone offsets are not supported in local schedules")
            times.append(value_time.strftime("%H:%M"))
        else:
            invalid("Invalid schedule time")

    raw_days = item.get("schedule_weekdays", list(range(7)))
    if not isinstance(raw_days, list) or not raw_days or any(type(v) is not int or not 0 <= v <= 6 for v in raw_days):
        invalid("Invalid schedule weekdays")
    days = ",".join(str(v) for v in sorted(set(raw_days)))
    start_date, end_date = dates
    start_time, end_time = times

    if enabled and mode == "window":
        if not all([start_date, end_date, start_time, end_time]):
            invalid("Scheduled period requires start and end dates and times")
        if datetime.combine(date.fromisoformat(start_date), time.fromisoformat(start_time)) >= datetime.combine(date.fromisoformat(end_date), time.fromisoformat(end_time)):
            invalid("Scheduled period must end after it starts")
    if enabled and mode == "recurring":
        if start_date and end_date and start_date > end_date:
            invalid("Recurring schedule dates are reversed")

    return (int(enabled), mode, start_date, end_date, days, start_time, end_time)
