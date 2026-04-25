from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as dt_timezone
import json
import re
from pathlib import Path
from typing import Any
import zoneinfo


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DURATION_RE = re.compile(r"^([1-9]\d*)([mhdw])$")
_FRONT_MATTER_LINE_RE = re.compile(
    r"^(\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:\s*)(.*?)(\r?\n)?$"
)
_DURATION_UNITS = {
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}


@dataclass(frozen=True)
class SuspensionStatus:
    raw_until: str | None
    reason: str | None
    until: datetime | None = None
    is_suspended: bool = False
    is_invalid: bool = False
    error: str | None = None

    @property
    def summary(self) -> str:
        if not self.raw_until:
            return "-"
        if self.is_invalid:
            return f"invalid: {self.raw_until}"
        if self.until is None:
            return "-"
        prefix = "until" if self.is_suspended else "expired"
        return f"{prefix}: {self.until.isoformat(timespec='seconds')}"


def _resolve_timezone(tz_name: str | None) -> dt_timezone | zoneinfo.ZoneInfo:
    if not tz_name:
        return dt_timezone.utc
    try:
        return zoneinfo.ZoneInfo(tz_name)
    except zoneinfo.ZoneInfoNotFoundError:
        return dt_timezone.utc


def _aware_now(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(dt_timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=dt_timezone.utc)
    return now


def parse_suspension_duration(value: str) -> timedelta:
    token = value.strip()
    match = _DURATION_RE.fullmatch(token)
    if not match:
        raise ValueError("duration must be one token like 30m, 3h, 14d, or 2w")
    amount = int(match.group(1))
    unit = match.group(2)
    return timedelta(**{_DURATION_UNITS[unit]: amount})


def suspension_deadline_from_duration(
    value: str,
    *,
    now: datetime | None = None,
    tz_name: str | None = None,
) -> datetime:
    tz = _resolve_timezone(tz_name)
    local_now = _aware_now(now).astimezone(tz)
    deadline_utc = local_now.astimezone(dt_timezone.utc) + parse_suspension_duration(
        value
    )
    return deadline_utc.astimezone(tz)


def parse_suspension_deadline(
    value: str,
    *,
    tz_name: str | None = None,
) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValueError("suspended_until must not be empty")

    tz = _resolve_timezone(tz_name)
    if _DATE_RE.fullmatch(raw):
        parsed_date = date.fromisoformat(raw)
        return datetime(
            parsed_date.year,
            parsed_date.month,
            parsed_date.day,
            tzinfo=tz,
        )

    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid suspended_until: {value}") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def get_suspension_status(
    task: Any,
    *,
    now: datetime | None = None,
    tz_name: str | None = None,
) -> SuspensionStatus:
    raw_until = getattr(task, "suspended_until", None)
    reason = getattr(task, "suspended_reason", None)
    if raw_until is None:
        return SuspensionStatus(raw_until=None, reason=reason)

    effective_tz = getattr(task, "timezone", None) or tz_name
    try:
        until = parse_suspension_deadline(str(raw_until), tz_name=effective_tz)
    except ValueError as exc:
        return SuspensionStatus(
            raw_until=str(raw_until),
            reason=reason,
            is_suspended=True,
            is_invalid=True,
            error=str(exc),
        )

    local_now = _aware_now(now).astimezone(until.tzinfo or dt_timezone.utc)
    return SuspensionStatus(
        raw_until=str(raw_until),
        reason=reason,
        until=until,
        is_suspended=local_now < until,
    )


def is_task_suspended(
    task: Any,
    *,
    now: datetime | None = None,
    tz_name: str | None = None,
) -> bool:
    return get_suspension_status(task, now=now, tz_name=tz_name).is_suspended


def format_front_matter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def update_markdown_front_matter_text(
    text: str,
    *,
    updates: dict[str, Any] | None = None,
    remove_keys: set[str] | None = None,
) -> str:
    updates = dict(updates or {})
    remove_keys = set(remove_keys or set())

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("Markdown task file is missing front matter")

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise ValueError("Markdown task file has unterminated front matter")

    seen: set[str] = set()
    new_front_lines: list[str] = []
    default_newline = "\n"
    for raw_line in lines[1:end_idx]:
        if raw_line.endswith("\r\n"):
            default_newline = "\r\n"
        elif raw_line.endswith("\n"):
            default_newline = "\n"
        match = _FRONT_MATTER_LINE_RE.match(raw_line)
        if not match:
            new_front_lines.append(raw_line)
            continue

        indent, key, sep, _value, newline = match.groups()
        if key in remove_keys:
            seen.add(key)
            continue
        if key in updates:
            seen.add(key)
            line_end = newline or default_newline
            new_front_lines.append(
                f"{indent}{key}{sep}{format_front_matter_value(updates[key])}{line_end}"
            )
        else:
            new_front_lines.append(raw_line)

    missing_updates = [
        key for key in updates if key not in seen and key not in remove_keys
    ]
    for key in missing_updates:
        new_front_lines.append(
            f"{key}: {format_front_matter_value(updates[key])}{default_newline}"
        )

    return "".join([lines[0], *new_front_lines, *lines[end_idx:]])


def update_markdown_front_matter(
    task_file: Path,
    *,
    updates: dict[str, Any] | None = None,
    remove_keys: set[str] | None = None,
) -> None:
    content = task_file.read_text(encoding="utf-8")
    new_content = update_markdown_front_matter_text(
        content,
        updates=updates,
        remove_keys=remove_keys,
    )
    task_file.write_text(new_content, encoding="utf-8")


def update_task_file_metadata(
    task_file: Path,
    *,
    task_name: str,
    updates: dict[str, Any] | None = None,
    remove_keys: set[str] | None = None,
) -> None:
    if task_file.suffix.lower() == ".md":
        update_markdown_front_matter(
            task_file,
            updates=updates,
            remove_keys=remove_keys,
        )
        return
    if task_file.suffix.lower() != ".toml":
        raise ValueError(f"Unsupported task file format: {task_file}")

    import tomlkit

    doc = tomlkit.loads(task_file.read_text(encoding="utf-8"))
    updates = dict(updates or {})
    remove_keys = set(remove_keys or set())

    target = None
    task_section = doc.get("task")
    if hasattr(task_section, "get") and task_section.get("name") == task_name:
        target = task_section
    else:
        for key, value in doc.items():
            if key.startswith("task") and hasattr(value, "get"):
                if value.get("name") == task_name:
                    target = value
                    break

    if target is None:
        raise ValueError(f"Task '{task_name}' not found in {task_file}")

    for key in remove_keys:
        if key in target:
            del target[key]
    for key, value in updates.items():
        target[key] = value

    task_file.write_text(tomlkit.dumps(doc), encoding="utf-8")
