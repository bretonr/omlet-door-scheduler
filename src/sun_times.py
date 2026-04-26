import math
import os
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Tuple

import numpy as np
import astropy.units as u
from astropy.time import Time
from astropy.coordinates import EarthLocation
from astroplan import Observer

import math
import os
from dataclasses import dataclass
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Tuple

import numpy as np
import astropy.units as u
from astropy.time import Time
from astropy.coordinates import EarthLocation
from astroplan import Observer


@dataclass
class SunSchedule:
    sunrise_local: datetime
    sunset_local: datetime

    @property
    def open_hhmm(self) -> str:
        return self.sunrise_local.strftime("%H:%M")

    @property
    def close_hhmm(self) -> str:
        return self.sunset_local.strftime("%H:%M")


def _is_masked(t: Time) -> bool:
    # Astroplan may return masked Time if event doesn't occur
    m = getattr(t, "mask", None)
    if m is None:
        return False
    if isinstance(m, (np.ndarray, list)):
        return bool(np.any(m))
    return bool(m)


def compute_sun_times(
    target_date: date,
    latitude: float,
    longitude: float,
    tz_name: str,
    open_offset_min: int = 0,
    close_offset_min: int = 0,
    min_open_time_str: str = "06:00:00",
) -> SunSchedule:
    """
    Compute local sunrise and sunset for the given date and location, then apply offsets.

    Returns SunSchedule with localized datetimes and HH:MM helpers.
    Offsets are in minutes (can be negative).
    """
    tzinfo = ZoneInfo(tz_name)

    # Observer at the coop location
    loc = EarthLocation(lat=latitude * u.deg, lon=longitude * u.deg, height=0 * u.m)
    observer = Observer(location=loc, timezone=tzinfo)

    # Start from local midnight of the target date
    local_midnight = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tzinfo)
    t0 = Time(local_midnight)

    # Helper to attempt multiple method names for compatibility across astroplan versions
    def _try_observer(name_candidates, *args, **kwargs):
        for name in name_candidates:
            fn = getattr(observer, name, None)
            if fn is None:
                continue
            try:
                return fn(*args, **kwargs)
            except TypeError:
                # some versions may have different signature
                try:
                    return fn(*args)
                except Exception:
                    continue
        return None

    # Compute sunrise/sunset; handle masked results (e.g., polar day/night)
    sr = _try_observer(["sunrise_time", "sun_rise_time", "sun_rise_time"], t0, which="next")
    ss = _try_observer(["sunset_time", "sun_set_time", "sun_set_time"], t0, which="next")

    # Fallbacks if masked: try civil twilight as a pragmatic substitute
    if _is_masked(sr) or sr is None:
        # Try civil twilight variants, then fallback to a sensible default hour
        sr = _try_observer(["twilight_morning_civil", "twilight_morning_civil_time"], t0, which="next")
        if sr is None or _is_masked(sr):
            sr = Time(local_midnight.replace(hour=8))
    if _is_masked(ss) or ss is None:
        ss = _try_observer(["twilight_evening_civil", "twilight_evening_civil_time"], t0, which="next")
        if ss is None or _is_masked(ss):
            ss = Time(local_midnight.replace(hour=16))

    # Convert to localized datetimes
    sr_dt = sr.to_datetime(timezone=tzinfo) if isinstance(sr, Time) else local_midnight.replace(hour=8)
    ss_dt = ss.to_datetime(timezone=tzinfo) if isinstance(ss, Time) else local_midnight.replace(hour=16)

    # Apply offsets
    sr_dt = sr_dt + timedelta(minutes=int(open_offset_min))
    ss_dt = ss_dt + timedelta(minutes=int(close_offset_min))

    # Parse minimum open time from HH:MM:SS format
    time_parts = min_open_time_str.split(":")
    min_hour = int(time_parts[0])
    min_minute = int(time_parts[1]) if len(time_parts) > 1 else 0
    min_second = int(time_parts[2]) if len(time_parts) > 2 else 0

    # Enforce minimum open time
    min_open_time = local_midnight.replace(hour=min_hour, minute=min_minute, second=min_second, microsecond=0)
    if sr_dt < min_open_time:
        sr_dt = min_open_time

    return SunSchedule(sunrise_local=sr_dt, sunset_local=ss_dt)


def parse_float_env(name: str) -> float:
    v = os.getenv(name)
    if v is None:
        raise ValueError(f"Missing required environment variable: {name}")
    try:
        return float(v)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be a number, got: {v}")


def parse_int_env(name: str, default: int = 0) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be an integer, got: {v}")
