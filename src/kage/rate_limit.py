from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, available_timezones

from .config import KAGE_GLOBAL_DIR

RATE_LIMIT_STATE_PATH: Path = KAGE_GLOBAL_DIR / "rate_limit_state.json"

# Detection keywords / phrases (case-insensitive)
_LIMIT_KEYWORDS = [
    "rate limit",
    "usage limit",
    "usage limit reached",
    "quota exceeded",
    "quota reached",
    "individual quota",
    "too many requests",
    "resource exhausted",
    "you've hit your limit",
    "you have hit your limit",
    "you've hit your usage limit",
    "you have hit your usage limit",
    "refreshes in",
    "resets in",
]

_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

# e.g. "2 days", "17 hours", "14 minutes", "30 seconds", "1 week",
# "122h48m19s"
_DURATION_TOKEN_RE = re.compile(
    r"(~?\d+)\s*(weeks?|w|days?|d|hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)",
    re.IGNORECASE,
)

# Absolute reset: "resets Jan 29 at 1pm (Asia/Tokyo)"
_ABSOLUTE_RESET_RE = re.compile(
    r"resets?\s+([A-Za-z]{3})\s+(\d{1,2})\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([A-Za-z_/,]+)\))?",
    re.IGNORECASE,
)

# Relative reset: "try again in 2 days 17 hours 14 minutes"
_RELATIVE_RESET_RE = re.compile(
    r"(?:try\s+again|retry|refreshes?|resets?|will\s+reset|reset)\s+in\s+([^\.\n;]+)",
    re.IGNORECASE,
)

# Time-only reset: "try again at 3:51 PM"
_TIME_ONLY_RESET_RE = re.compile(
    r"(?:try\s+again|retry)\s+at\s+(\d{1,2}):(\d{2})\s*(am|pm)?(?:\s*\(([A-Za-z_/,]+)\))?",
    re.IGNORECASE,
)

# Retry-After header in output
_RETRY_AFTER_RE = re.compile(r"retry-after:\s*(\d+)", re.IGNORECASE)


@dataclass
class RateLimitInfo:
    is_limited: bool = False
    reset_at: Optional[datetime] = None
    retry_after_seconds: Optional[int] = None
    raw_hint: Optional[str] = None


def _now_tz() -> datetime:
    return datetime.now().astimezone()


def _load_state() -> dict:
    if not RATE_LIMIT_STATE_PATH.exists():
        return {}
    try:
        text = RATE_LIMIT_STATE_PATH.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_state(state: dict) -> None:
    RATE_LIMIT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = RATE_LIMIT_STATE_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp_path.replace(RATE_LIMIT_STATE_PATH)


def _parse_duration_tokens(segment: str) -> Optional[timedelta]:
    total = timedelta()
    found = False
    for match in _DURATION_TOKEN_RE.finditer(segment):
        found = True
        value = int(match.group(1).lstrip("~"))
        unit = match.group(2).lower()
        if unit.startswith("week") or unit == "w":
            total += timedelta(weeks=value)
        elif unit.startswith("day") or unit == "d":
            total += timedelta(days=value)
        elif unit.startswith("hour") or unit.startswith("hr") or unit == "h":
            total += timedelta(hours=value)
        elif unit.startswith("minute") or unit.startswith("min") or unit == "m":
            total += timedelta(minutes=value)
        elif unit.startswith("second") or unit.startswith("sec") or unit == "s":
            total += timedelta(seconds=value)
    return total if found else None


def _resolve_timezone(tz_name: Optional[str]) -> Optional[ZoneInfo]:
    if not tz_name:
        return None
    name = tz_name.strip()
    if name in available_timezones():
        return ZoneInfo(name)
    return None


def _normalize_to_now_tz(
    dt: datetime, tz: Optional[ZoneInfo], now: datetime
) -> datetime:
    if tz is not None:
        dt = dt.replace(tzinfo=tz)
    elif now.tzinfo is not None:
        dt = dt.replace(tzinfo=now.tzinfo)
    return dt.astimezone(now.tzinfo)


def _parse_absolute_reset(text: str, now: datetime) -> Optional[datetime]:
    match = _ABSOLUTE_RESET_RE.search(text)
    if not match:
        return None
    mon_str, day_str, hour_str, min_str, ampm, tz_name = match.groups()
    month = _MONTHS.get(mon_str.lower()[:3])
    if month is None:
        return None
    day = int(day_str)
    hour = int(hour_str)
    minute = int(min_str) if min_str else 0
    if ampm:
        if ampm.lower() == "pm" and hour != 12:
            hour += 12
        elif ampm.lower() == "am" and hour == 12:
            hour = 0
    tz = _resolve_timezone(tz_name)
    year = now.year
    try:
        dt = datetime(year, month, day, hour, minute)
    except ValueError:
        return None
    dt = _normalize_to_now_tz(dt, tz, now)
    # If the date already passed this year, assume next year.
    if dt < now - timedelta(days=1):
        try:
            dt = datetime(year + 1, month, day, hour, minute)
        except ValueError:
            return None
        dt = _normalize_to_now_tz(dt, tz, now)
    return dt


def _parse_relative_reset(text: str, now: datetime) -> Optional[datetime]:
    match = _RELATIVE_RESET_RE.search(text)
    if not match:
        return None
    delta = _parse_duration_tokens(match.group(1))
    if delta is None or delta.total_seconds() <= 0:
        return None
    return now + delta


def _parse_time_only_reset(text: str, now: datetime) -> Optional[datetime]:
    match = _TIME_ONLY_RESET_RE.search(text)
    if not match:
        return None
    hour_str, min_str, ampm, tz_name = match.groups()
    hour = int(hour_str)
    minute = int(min_str)
    if ampm:
        if ampm.lower() == "pm" and hour != 12:
            hour += 12
        elif ampm.lower() == "am" and hour == 12:
            hour = 0
    tz = _resolve_timezone(tz_name)
    base = now.date()
    try:
        dt = datetime(base.year, base.month, base.day, hour, minute)
    except ValueError:
        return None
    dt = _normalize_to_now_tz(dt, tz, now)
    if dt <= now:
        base = base + timedelta(days=1)
        try:
            dt = datetime(base.year, base.month, base.day, hour, minute)
        except ValueError:
            return None
        dt = _normalize_to_now_tz(dt, tz, now)
    return dt


def _parse_retry_after(text: str, now: datetime) -> Optional[datetime]:
    match = _RETRY_AFTER_RE.search(text)
    if not match:
        return None
    try:
        seconds = int(match.group(1))
    except ValueError:
        return None
    if seconds <= 0:
        return None
    return now + timedelta(seconds=seconds)


def _looks_like_rate_limit(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _LIMIT_KEYWORDS)


def parse_rate_limit_info(
    stdout: str, stderr: str, now: Optional[datetime] = None
) -> RateLimitInfo:
    if now is None:
        now = _now_tz()
    combined = f"{stdout}\n{stderr}"
    if not _looks_like_rate_limit(combined):
        return RateLimitInfo(is_limited=False)

    raw = (stderr.strip() or stdout.strip())[:1000]

    # Prefer explicit retry-after header, then absolute, then relative, then time-only.
    reset_at = (
        _parse_retry_after(combined, now)
        or _parse_absolute_reset(combined, now)
        or _parse_relative_reset(combined, now)
        or _parse_time_only_reset(combined, now)
    )

    retry_after_seconds: Optional[int] = None
    if reset_at is not None:
        delta = reset_at - now
        if delta.total_seconds() > 0:
            retry_after_seconds = int(delta.total_seconds())
        else:
            retry_after_seconds = 0

    return RateLimitInfo(
        is_limited=True,
        reset_at=reset_at,
        retry_after_seconds=retry_after_seconds,
        raw_hint=raw,
    )


def _model_state_key(model: Optional[str]) -> str:
    return model if model is not None else "__none__"


def is_model_rate_limited(
    provider_name: str,
    model_name: Optional[str],
    now: Optional[datetime] = None,
) -> bool:
    if now is None:
        now = _now_tz()
    state = _load_state()
    provider_state = state.get(provider_name, {})
    entry = provider_state.get(_model_state_key(model_name))
    if not entry or not entry.get("reset_at"):
        return False
    try:
        reset_at = datetime.fromisoformat(entry["reset_at"])
    except Exception:
        return False
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=now.tzinfo)
    return reset_at > now


def get_model_rate_limit_reset(
    provider_name: str,
    model_name: Optional[str],
) -> Optional[datetime]:
    state = _load_state()
    entry = state.get(provider_name, {}).get(_model_state_key(model_name))
    if not entry or not entry.get("reset_at"):
        return None
    try:
        return datetime.fromisoformat(entry["reset_at"])
    except Exception:
        return None


def set_model_rate_limit_reset(
    provider_name: str,
    model_name: Optional[str],
    reset_at: Optional[datetime],
    raw_hint: Optional[str] = None,
) -> None:
    state = _load_state()
    provider_state = state.setdefault(provider_name, {})
    key = _model_state_key(model_name)
    if reset_at is None:
        provider_state.pop(key, None)
    else:
        provider_state[key] = {
            "reset_at": reset_at.isoformat(),
            "raw_hint": raw_hint,
        }
    _save_state(state)


def clear_model_rate_limit_reset(
    provider_name: str,
    model_name: Optional[str],
) -> None:
    state = _load_state()
    provider_state = state.get(provider_name, {})
    key = _model_state_key(model_name)
    if key in provider_state:
        del provider_state[key]
        _save_state(state)
