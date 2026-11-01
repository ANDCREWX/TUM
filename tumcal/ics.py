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


# --- Schreiben ---------------------------------------------------------------
#
# Die Gegenrichtung: Termine als .ics, zum Import in Google Calendar, Apple
# Kalender oder Outlook. Geschrieben wird in UTC statt mit TZID, denn ein
# TZID-Verweis verlangt laut RFC 5545 eine mitgelieferte VTIMEZONE-Komponente -
# ohne sie verwerfen manche Clients den Termin oder verschieben ihn still.

_WRITE_ESCAPES = ((chr(92), r"\\"), (";", r"\;"), (",", r"\,"))


def escape_text(value: str) -> str:
    """Sonderzeichen für ein TEXT-Feld maskieren (RFC 5545, 3.3.11)."""
    out = value or ""
    for zeichen, ersatz in _WRITE_ESCAPES:
        out = out.replace(zeichen, ersatz)
    return out.replace("\r\n", r"\n").replace("\n", r"\n").replace("\r", r"\n")


def fold_line(line: str) -> list[str]:
    """Zeile auf 75 Oktette umbrechen, Folgezeilen mit einem Leerzeichen.

    Gezählt werden Oktette, nicht Zeichen - ein Umbruch mitten in einem
    UTF-8-Zeichen macht die Datei kaputt, deshalb wird zeichenweise gefüllt.
    """
    teile: list[str] = []
    rest = line
    grenze = 75
    while len(rest.encode("utf-8")) > grenze:
        stueck = ""
        for zeichen in rest:
            if len((stueck + zeichen).encode("utf-8")) > grenze:
                break
            stueck += zeichen
        teile.append(stueck)
        rest = rest[len(stueck):]
        grenze = 74  # Folgezeilen tragen ein führendes Leerzeichen
    teile.append(rest)
    return [teile[0]] + [" " + t for t in teile[1:]]


def _utc(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("Europe/Berlin"))
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slug(value: str) -> str:
    roh = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return roh or "termin"


def render_calendar(events, name: str = "", stamp: datetime | None = None) -> str:
    """Termine als iCalendar-Text.

    `events` ist jede Folge von Objekten mit `start`, `end`, `summary` und
    optional `location`, `description`, `course_code`, `cancelled` - also
    insbesondere CourseEvent. Absichtlich per Duck-Typing, damit dieses
    Modul nichts aus model importieren muss.
    """
    jetzt = _utc(stamp or datetime.now(timezone.utc))
    zeilen = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//tumcal//Stundenplan//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    if name:
        zeilen.append(f"X-WR-CALNAME:{escape_text(name)}")

    # Mehrere Termine derselben LV am selben Tag brauchen verschiedene UIDs;
    # die Uhrzeit darf nicht hineinfließen, sonst legt eine Zeitkorrektur
    # beim Reimport einen zweiten Termin an statt den alten zu ändern.
    zaehler: dict[tuple[str, str], int] = {}
    for event in sorted(events, key=lambda e: (e.start, getattr(e, "summary", ""))):
        # Art mit in die Kennung: Vorlesung und Übung eines Moduls haben
        # denselben Modulcode und dürfen sich die UID nicht teilen.
        code = getattr(event, "course_code", "") or event.summary
        art = getattr(event, "kind", "") or ""
        kennung = _slug(f"{code}-{art}" if art else code)
        tag = event.start.strftime("%Y%m%d")
        nummer = zaehler.get((kennung, tag), 0)
        zaehler[(kennung, tag)] = nummer + 1
        uid = f"{kennung}-{tag}" + (f"-{nummer}" if nummer else "") + "@tumcal"

        zeilen += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{jetzt}",
            f"DTSTART:{_utc(event.start)}",
            f"DTEND:{_utc(event.end)}",
            f"SUMMARY:{escape_text(event.summary)}",
        ]
        ort = getattr(event, "location", "") or ""
        if ort:
            zeilen.append(f"LOCATION:{escape_text(ort)}")
        text = getattr(event, "description", "") or ""
        if text:
            zeilen.append(f"DESCRIPTION:{escape_text(text)}")
        if getattr(event, "cancelled", False):
            zeilen.append("STATUS:CANCELLED")
        zeilen.append("END:VEVENT")

    zeilen.append("END:VCALENDAR")
    gefaltet = [teil for zeile in zeilen for teil in fold_line(zeile)]
    return "\r\n".join(gefaltet) + "\r\n"
