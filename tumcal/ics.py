"""Minimaler RFC-5545-Parser - bewusst ohne externe Abhängigkeiten,
damit das Tool auf jedem Rechner mit Python 3.9+ ohne pip-Install läuft."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_ESCAPES = {"n": "\n", "N": "\n", ",": ",", ";": ";", "\\": "\\"}


def unfold(text: str) -> list[str]:
    """Faltet die in ICS üblichen Zeilenumbrüche (CRLF + Space/Tab) auf."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return [line for line in lines if line.strip()]


def unescape(value: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            out.append(_ESCAPES.get(value[i + 1], value[i + 1]))
            i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


def split_property(line: str) -> tuple[str, dict[str, str], str]:
    """'DTSTART;TZID=Europe/Berlin:20261020T100000' -> (name, params, value)."""
    # Der Doppelpunkt darf in Parameterwerten in Anführungszeichen stehen.
    in_quotes = False
    for idx, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == ":" and not in_quotes:
            head, value = line[:idx], line[idx + 1 :]
            break
    else:
        return line.upper(), {}, ""

    parts = head.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, val = part.split("=", 1)
            params[key.upper()] = val.strip('"')
    return name, params, value


def parse_datetime(value: str, params: dict[str, str]) -> datetime | date:
    """DATE, floating DATE-TIME, UTC (Z) und TZID-behaftete Werte."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and "T" not in value):
        return datetime.strptime(value, "%Y%m%d").date()

    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)

    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    if tzid:
        try:
            return naive.replace(tzinfo=ZoneInfo(tzid))
        except Exception:
            # Unbekannte TZID (z. B. Windows-Namen): als lokale TUM-Zeit deuten.
            return naive.replace(tzinfo=ZoneInfo("Europe/Berlin"))
    return naive.replace(tzinfo=ZoneInfo("Europe/Berlin"))


def parse_duration(value: str) -> timedelta:
    match = re.fullmatch(
        r"(?P<sign>[+-])?P(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?"
        r"(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?",
        value.strip(),
    )
    if not match:
        return timedelta()
    nums = {k: int(v) for k, v in match.groupdict().items() if k != "sign" and v}
    delta = timedelta(
        weeks=nums.get("w", 0),
        days=nums.get("d", 0),
        hours=nums.get("h", 0),
        minutes=nums.get("m", 0),
        seconds=nums.get("s", 0),
    )
    return -delta if match.group("sign") == "-" else delta


def parse_vevents(text: str) -> list[dict]:
    """Liefert alle VEVENT-Komponenten als Dicts (Mehrfachwerte als Liste)."""
    events: list[dict] = []
    current: dict | None = None
    depth_other = 0  # VTIMEZONE o. Ä. überspringen

    for line in unfold(text):
        name, params, value = split_property(line)
        upper_value = value.strip().upper()

        if name == "BEGIN" and upper_value == "VEVENT":
            current = {}
            continue
        if name == "END" and upper_value == "VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None:
            if name == "BEGIN":
                depth_other += 1
            elif name == "END":
                depth_other = max(0, depth_other - 1)
            continue

        if name in ("DTSTART", "DTEND", "RECURRENCE-ID"):
            current[name] = parse_datetime(value, params)
        elif name == "DURATION":
            current[name] = parse_duration(value)
        elif name == "CATEGORIES":
            current.setdefault("CATEGORIES", []).extend(
                unescape(part).strip() for part in value.split(",") if part.strip()
            )
        else:
            current[name] = unescape(value).strip()

    return events
