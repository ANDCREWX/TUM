"""Aufbereitung der TUMonline-Termine: Typerkennung, Bereinigung, Dedupe."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .ics import parse_vevents

BERLIN = ZoneInfo("Europe/Berlin")

# TUMonline-Kürzel für Lehrveranstaltungsarten.
TYPE_LABELS = {
    "VO": "Vorlesung",
    "VI": "Vorlesung mit Integrierter Übung",
    "VU": "Vorlesung mit Übung",
    "UE": "Übung",
    "SE": "Seminar",
    "PR": "Praktikum",
    "PS": "Proseminar",
    "TT": "Tutorium",
    "KO": "Kolloquium",
    "EX": "Exkursion",
    "RE": "Repetitorium",
    "PT": "Projektpraktikum",
}

# Freitext-Erkennung, falls kein Kürzel im Titel steht.
_TEXT_TYPES = [
    ("Zentralübung", "UE"),
    ("Tutorübung", "UE"),
    ("Übung", "UE"),
    ("Uebung", "UE"),
    ("Tutorium", "TT"),
    ("Vorlesung", "VO"),
    ("Seminar", "SE"),
    ("Praktikum", "PR"),
    ("Klausur", "PRUEFUNG"),
    ("Prüfung", "PRUEFUNG"),
    ("Wiederholungsklausur", "PRUEFUNG"),
]

_CANCELLED_MARKERS = ("abgesagt", "entfällt", "entfaellt", "cancelled", "verschoben")

# Modulkennungen wie IN0001, WI001234, MA0901
_COURSE_CODE = re.compile(r"\b([A-Z]{2}[A-Z]?\d{3,6})\b")
_TYPE_CODE = re.compile(r"(?<![A-Za-z])(%s)(?![A-Za-z])" % "|".join(TYPE_LABELS))
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class CourseEvent:
    """Ein einzelner Termin einer Lehrveranstaltung."""

    summary: str
    title: str
    start: datetime
    end: datetime
    location: str = ""
    room: str = ""
    course_code: str = ""
    kind: str = "SONSTIGES"
    lecturer: str = ""
    description: str = ""
    cancelled: bool = False
    categories: tuple[str, ...] = field(default_factory=tuple)

    @property
    def kind_label(self) -> str:
        if self.kind == "PRUEFUNG":
            return "Prüfung"
        return TYPE_LABELS.get(self.kind, "Sonstiges")

    @property
    def day(self) -> date:
        return self.start.date()

    @property
    def all_day(self) -> bool:
        """Ganztagstermine kommen als DATE-Werte ohne Uhrzeit aus TUMonline."""
        return (
            self.start.hour == 0
            and self.start.minute == 0
            and self.duration_minutes >= 24 * 60
        )

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)

    def dedupe_key(self) -> tuple:
        return (self.title.lower(), self.kind, self.start, self.end, self.room.lower())


def _clean(value: str) -> str:
    return _WHITESPACE.sub(" ", (value or "").replace("\n", " ")).strip()


def detect_kind(summary: str, description: str = "", categories=()) -> str:
    """Bestimmt die Veranstaltungsart aus Kürzel, Kategorie oder Freitext."""
    haystack = " ".join([summary or "", " ".join(categories or ()), description or ""])

    for marker, kind in _TEXT_TYPES:
        if marker.lower() in haystack.lower():
            # Prüfungsbegriffe schlagen die generische Kürzelsuche.
            if kind == "PRUEFUNG":
                return kind
            break

    match = _TYPE_CODE.search(summary or "")
    if match:
        return match.group(1)

    for marker, kind in _TEXT_TYPES:
        if marker.lower() in haystack.lower():
            return kind
    return "SONSTIGES"


def extract_course_code(summary: str, description: str = "") -> str:
    for text in (summary, description):
        match = _COURSE_CODE.search(text or "")
        if match:
            return match.group(1)
    return ""


def clean_title(summary: str, course_code: str = "", kind: str = "") -> str:
    """Entfernt Modulnummer und Art-Kürzel aus dem Titel."""
    title = _clean(summary)
    if course_code:
        title = title.replace(course_code, " ")
    if kind and kind in TYPE_LABELS:
        title = _TYPE_CODE.sub(" ", title)
    title = re.sub(r"\(\s*\)|\[\s*\]", " ", title)
    title = title.strip(" -–—,;:()[]")
    return _WHITESPACE.sub(" ", title).strip() or _clean(summary)


def extract_room(location: str) -> str:
    """'5602.EG.001 (MI HS 1)' -> 'MI HS 1'; sonst der Originalwert."""
    location = _clean(location)
    match = re.search(r"\(([^)]+)\)\s*$", location)
    if match:
        return match.group(1).strip()
    return location


def is_cancelled(event: dict) -> bool:
    if (event.get("STATUS") or "").upper() == "CANCELLED":
        return True
    haystack = f"{event.get('SUMMARY', '')} {event.get('DESCRIPTION', '')}".lower()
    return any(marker in haystack for marker in _CANCELLED_MARKERS)


def _as_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(BERLIN) if value.tzinfo else value.replace(tzinfo=BERLIN)
    return datetime(value.year, value.month, value.day, tzinfo=BERLIN)


def build_event(raw: dict) -> CourseEvent | None:
    start_raw = raw.get("DTSTART")
    if start_raw is None:
        return None

    start = _as_datetime(start_raw)
    if raw.get("DTEND") is not None:
        end = _as_datetime(raw["DTEND"])
    elif isinstance(raw.get("DURATION"), timedelta):
        end = start + raw["DURATION"]
    elif isinstance(start_raw, date) and not isinstance(start_raw, datetime):
        end = start + timedelta(days=1)
    else:
        end = start + timedelta(hours=1)

    summary = _clean(raw.get("SUMMARY", ""))
    description = _clean(raw.get("DESCRIPTION", ""))
    categories = tuple(raw.get("CATEGORIES", []) or ())
    kind = detect_kind(summary, description, categories)
    course_code = extract_course_code(summary, description)
    location = _clean(raw.get("LOCATION", ""))

    return CourseEvent(
        summary=summary,
        title=clean_title(summary, course_code, kind),
        start=start,
        end=end,
        location=location,
        room=extract_room(location),
        course_code=course_code,
        kind=kind,
        lecturer=_clean(raw.get("ORGANIZER", "")).replace("mailto:", ""),
        description=description,
        cancelled=is_cancelled(raw),
        categories=categories,
    )


def load_events(ics_text: str) -> list[CourseEvent]:
    """Parst einen ICS-Export und liefert deduplizierte, sortierte Termine."""
    events: list[CourseEvent] = []
    for raw in parse_vevents(ics_text):
        event = build_event(raw)
        if event is not None:
            events.append(event)

    # TUMonline liefert Termine gelegentlich doppelt (z. B. Gruppe + LV).
    seen: set[tuple] = set()
    unique: list[CourseEvent] = []
    for event in sorted(events, key=lambda e: (e.start, e.title)):
        key = event.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def filter_events(
    events: list[CourseEvent],
    kinds: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
    include_cancelled: bool = True,
) -> list[CourseEvent]:
    selected = events
    if kinds:
        wanted = {k.upper() for k in kinds}
        selected = [e for e in selected if e.kind in wanted]
    if start:
        selected = [e for e in selected if e.day >= start]
    if end:
        selected = [e for e in selected if e.day <= end]
    if not include_cancelled:
        selected = [e for e in selected if not e.cancelled]
    return selected
