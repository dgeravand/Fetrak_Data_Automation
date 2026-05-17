# ------------------------------------------------------------------------------
# TIMEZONE UTILITIES
# ------------------------------------------------------------------------------
import os
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

# Default timezone
default_tz = "Asia/Tehran"

# Config file path
TZ_CONFIG_FILE = Path("data/timezone.conf")


def get_timezone():
    """Get the configured timezone string."""
    if TZ_CONFIG_FILE.exists():
        tz = TZ_CONFIG_FILE.read_text(encoding="utf-8").strip()
        if tz:
            return tz
    return default_tz


def set_timezone(tz_string):
    """Set the configured timezone string."""
    TZ_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    TZ_CONFIG_FILE.write_text(tz_string.strip(), encoding="utf-8")


def get_timezone_obj():
    """Get the configured timezone as a zoneinfo/pytz object."""
    tz_name = get_timezone()
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name)
    except Exception:
        try:
            import pytz
            return pytz.timezone(tz_name)
        except Exception:
            return dt_timezone.utc


def now():
    """Get current time in configured timezone."""
    return datetime.now(get_timezone_obj())


def utc_to_local(dt):
    """Convert a UTC datetime to configured timezone."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt.astimezone(get_timezone_obj())


def format_dt(dt, fmt="%Y-%m-%d %H:%M:%S"):
    """Format a datetime in configured timezone."""
    local_dt = utc_to_local(dt)
    if local_dt is None:
        return ""
    return local_dt.strftime(fmt)


def list_timezones():
    """Return a sorted list of common timezone names."""
    try:
        from zoneinfo import available_timezones
        return sorted(available_timezones())
    except Exception:
        try:
            import pytz
            return sorted(pytz.all_timezones)
        except Exception:
            return ["UTC", "Asia/Tehran", "Asia/Dubai", "Europe/London", "America/New_York"]
