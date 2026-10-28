"""Resolve a local clock-time sleep deadline with midnight and DST handling."""
from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo

MAX_SLEEP_MINUTES = 960


def seconds_to_end_time(clock, zone_name="America/Chicago", now=None):
    if not isinstance(clock, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
        raise ValueError("Enter an end time in HH:MM format.")
    zone = ZoneInfo(zone_name)
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(zone)
    hours, minute = map(int, clock.split(":"))
    possible = []
    for day_offset in (0, 1, 2):
        d = local.date() + timedelta(days=day_offset)
        for fold in (0, 1):
            tentative = datetime(d.year, d.month, d.day, hours, minute, tzinfo=zone, fold=fold)
            utc = tentative.astimezone(timezone.utc)
            if utc <= now:
                continue
            if utc.astimezone(zone).replace(tzinfo=None) == tentative.replace(tzinfo=None):
                possible.append(utc)
    if not possible:
        raise ValueError("No valid upcoming end time.")
    seconds = (min(possible) - now).total_seconds()
    if not 0 < seconds <= MAX_SLEEP_MINUTES * 60:
        raise ValueError("End time must be within the next 16 hours.")
    return seconds
