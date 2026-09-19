"""Einlesen möglicher Lehrveranstaltungen (Angebot) aus CSV/TSV/JSON.

Anders als der persönliche Kalender ist das Angebot in TUMonline kein
iCal-Feed. Es wird deshalb aus einem Export bzw. einer gepflegten Tabelle
gelesen und anhand von Wochentag + Rhythmus über die Vorlesungszeit ausgerollt.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .model import TYPE_LABELS, CourseEvent, detect_kind, extract_room, BERLIN
from .semester import Semester

WEEKDAY_CODES = {
    "mo": 0, "montag": 0, "monday": 0,
    "di": 1, "die": 1, "dienstag": 1, "tuesday": 1, "tu": 1,
    "mi": 2, "mit": 2, "mittwoch": 2, "wednesday": 2, "we": 2,
    "do": 3, "don": 3, "donnerstag": 3, "thursday": 3, "th": 3,
    "fr": 4, "fre": 4, "freitag": 4, "friday": 4,
    "sa": 5, "sam": 5, "samstag": 5, "saturday": 5,
    "so": 6, "son": 6, "sonntag": 6, "sunday": 6, "su": 6,
}

# Spaltenüberschriften, wie sie in TUMonline-Exporten und von Hand vorkommen.
FIELD_ALIASES = {
    "lv_id": ("lv-nummer", "lvnummer", "lv-nr", "lvnr", "nummer", "id", "kennung", "course number"),
    "title": ("titel", "lehrveranstaltung", "veranstaltung", "name", "title", "bezeichnung"),
    "kind": ("art", "lv-art", "typ", "type", "kind"),
    "module": ("modul", "modulnummer", "modul-nr", "module", "modulkennung"),
    "ects": ("ects", "credits", "cp", "leistungspunkte"),
    "group": ("gruppe", "group", "übungsgruppe", "uebungsgruppe"),
    "weekday": ("tag", "wochentag", "day", "weekday"),
    "start_time": ("von", "beginn", "start", "uhrzeit von", "from"),
    "end_time": ("bis", "ende", "end", "uhrzeit bis", "to"),
    "rhythm": ("rhythmus", "turnus", "frequenz", "wiederholung", "rhythm"),
    "room": ("raum", "ort", "room", "location"),
    "lecturer": ("dozent", "dozentin", "lehrende", "lehrender", "vortragende", "lecturer"),
    "first_date": ("erster termin", "ab", "startdatum", "first date", "datum"),
    "last_date": ("letzter termin", "bis datum", "enddatum", "last date"),
    "url": ("link", "url", "tumonline", "anmeldung", "anmeldelink"),
    "deadline": ("anmeldefrist", "frist", "deadline", "anmeldung bis"),
    "note": ("hinweis", "bemerkung", "note", "kommentar"),
}

RHYTHM_WEEKLY = "woechentlich"
RHYTHM_BIWEEKLY = "14-taegig"
RHYTHM_SINGLE = "einzeltermin"

_TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})")


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class CourseOption:
    """Eine anmeldbare Lehrveranstaltung bzw. Übungsgruppe."""

    title: str
    lv_id: str = ""
    kind: str = "SONSTIGES"
    module: str = ""
    ects: float = 0.0
    group: str = ""
    weekday: int | None = None
    start_time: time | None = None
    end_time: time | None = None
    rhythm: str = RHYTHM_WEEKLY
    room: str = ""
    lecturer: str = ""
    first_date: date | None = None
    last_date: date | None = None
    url: str = ""
    deadline: date | None = None
    note: str = ""

    @property
    def kind_label(self) -> str:
        if self.kind == "PRUEFUNG":
            return "Prüfung"
        return TYPE_LABELS.get(self.kind, "Sonstiges")

    @property
    def key(self) -> str:
        """Stabile ID für Auswahl und Wiedererkennung."""
        base = self.lv_id or f"{self.module}-{self.title}"
        return re.sub(r"[^a-z0-9]+", "-", f"{base}-{self.kind}-{self.group}".lower()).strip("-")

    @property
    def label(self) -> str:
        if not self.group:
            return f"{self.title} ({self.kind_label})"
        group = self.group if self.group.lower().startswith("gruppe") else f"Gruppe {self.group}"
        return f"{self.title} ({self.kind_label}) · {group}"

    @property
    def slots_known(self) -> bool:
        return self.start_time is not None and self.end_time is not None

    def occurrences(self, semester: Semester) -> list[date]:
        """Konkrete Termine über die Vorlesungszeit."""
        if self.weekday is None:
            return [self.first_date] if self.first_date else []

        days = semester.lecture_days(self.weekday)
        if self.first_date:
            days = [d for d in days if d >= self.first_date]
        if self.last_date:
            days = [d for d in days if d <= self.last_date]

        if self.rhythm == RHYTHM_SINGLE:
            return days[:1]
        if self.rhythm == RHYTHM_BIWEEKLY:
            return days[::2]
        return days

    def events(self, semester: Semester) -> list[CourseEvent]:
        if self.start_time is None or self.end_time is None:
            return []
        out: list[CourseEvent] = []
        for day in self.occurrences(semester):
            start = datetime.combine(day, self.start_time, tzinfo=BERLIN)
            end = datetime.combine(day, self.end_time, tzinfo=BERLIN)
            if end <= start:  # über Mitternacht ist im LV-Betrieb nicht vorgesehen
                end = start + timedelta(hours=2)
            out.append(
                CourseEvent(
                    summary=self.label,
                    title=self.title,
                    start=start,
                    end=end,
                    location=self.room,
                    room=extract_room(self.room),
                    course_code=self.module or self.lv_id,
                    kind=self.kind,
                    lecturer=self.lecturer,
                    description=self.note,
                )
            )
        return out


def _normalize_header(name: str) -> str:
    return (name or "").strip().lower().lstrip("﻿")


def _map_headers(fieldnames: list[str]) -> dict[str, str]:
    """Ordnet die Spalten der Datei den bekannten Feldern zu."""
    mapping: dict[str, str] = {}
    for raw in fieldnames or []:
        norm = _normalize_header(raw)
        for field_name, aliases in FIELD_ALIASES.items():
            if norm in aliases and field_name not in mapping:
                mapping[field_name] = raw
                break
    return mapping


def parse_weekday(value: str) -> int | None:
    token = (value or "").strip().lower().rstrip(".,")
    if not token:
        return None
    if token.isdigit():
        number = int(token)
        return number - 1 if 1 <= number <= 7 else None
    for prefix_len in (len(token), 3, 2):
        if token[:prefix_len] in WEEKDAY_CODES:
            return WEEKDAY_CODES[token[:prefix_len]]
    return None


def parse_time(value: str) -> time | None:
    match = _TIME_RE.search(value or "")
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour, minute)
    token = (value or "").strip()
    if token.isdigit() and 0 <= int(token) <= 23:
        return time(int(token), 0)
    return None


def parse_date_value(value: str) -> date | None:
    token = (value or "").strip()
    if not token:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def parse_rhythm(value: str) -> str:
    token = (value or "").strip().lower()
    if not token:
        return RHYTHM_WEEKLY
    if any(w in token for w in ("14", "zweiw", "biweek", "gerade", "ungerade", "alle zwei")):
        return RHYTHM_BIWEEKLY
    if any(w in token for w in ("einzel", "block", "einmal", "single")):
        return RHYTHM_SINGLE
    return RHYTHM_WEEKLY


def parse_ects(value: str) -> float:
    match = re.search(r"\d+(?:[.,]\d+)?", value or "")
    return float(match.group(0).replace(",", ".")) if match else 0.0


def _row_to_option(row: dict[str, str], mapping: dict[str, str]) -> CourseOption | None:
    def get(field_name: str) -> str:
        column = mapping.get(field_name)
        return (row.get(column) or "").strip() if column else ""

    title = get("title")
    if not title:
        return None

    kind_raw = get("kind")
    kind = detect_kind(f"{kind_raw} {title}") if kind_raw or title else "SONSTIGES"

    return CourseOption(
        title=title,
        lv_id=get("lv_id"),
        kind=kind,
        module=get("module"),
        ects=parse_ects(get("ects")),
        group=get("group"),
        weekday=parse_weekday(get("weekday")),
        start_time=parse_time(get("start_time")),
        end_time=parse_time(get("end_time")),
        rhythm=parse_rhythm(get("rhythm")),
        room=get("room"),
        lecturer=get("lecturer"),
        first_date=parse_date_value(get("first_date")),
        last_date=parse_date_value(get("last_date")),
        url=get("url"),
        deadline=parse_date_value(get("deadline")),
        note=get("note"),
    )


def _sniff_dialect(text: str) -> csv.Dialect | type[csv.Dialect]:
    sample = "\n".join(text.splitlines()[:5])
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        return csv.excel_tab if "\t" in sample else csv.excel


def load_catalog_csv(text: str) -> list[CourseOption]:
    reader = csv.DictReader(io.StringIO(text), dialect=_sniff_dialect(text))
    mapping = _map_headers(list(reader.fieldnames or []))
    if "title" not in mapping:
        raise CatalogError(
            "Keine Titelspalte gefunden. Erwartet wird eine Spalte wie "
            "'Titel' oder 'Lehrveranstaltung'. Vorlage: python3 -m tumcal template"
        )
    options = [opt for row in reader if (opt := _row_to_option(row, mapping))]
    if not options:
        raise CatalogError("Die Datei enthält keine auswertbaren Zeilen.")
    return options


def load_catalog_json(text: str) -> list[CourseOption]:
    """Best effort für JSON-Exporte bzw. selbst gepflegte Listen."""
    data = json.loads(text)
    if isinstance(data, dict):
        for candidate in ("courses", "lehrveranstaltungen", "items", "data", "resource"):
            if isinstance(data.get(candidate), list):
                data = data[candidate]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise CatalogError("JSON enthält keine Liste von Lehrveranstaltungen.")

    rows = [{str(k): ("" if v is None else str(v)) for k, v in item.items()}
            for item in data if isinstance(item, dict)]
    if not rows:
        raise CatalogError("JSON enthält keine Objekte.")
    mapping = _map_headers(sorted({key for row in rows for key in row}))
    if "title" not in mapping:
        raise CatalogError("JSON enthält kein erkennbares Titelfeld.")
    return [opt for row in rows if (opt := _row_to_option(row, mapping))]


def load_catalog(path: str | Path) -> list[CourseOption]:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() == ".json" or text.lstrip()[:1] in "[{":
        return load_catalog_json(text)
    return load_catalog_csv(text)


@dataclass
class Conflict:
    """Zwei gewählte Veranstaltungen überschneiden sich an einem Tag."""

    day: date
    first: CourseOption
    second: CourseOption
    start: time
    end: time

    def describe(self) -> str:
        return (
            f"{self.day.strftime('%d.%m.%Y')} {self.start:%H:%M}-{self.end:%H:%M}: "
            f"{self.first.label} ↔ {self.second.label}"
        )


def find_conflicts(options: list[CourseOption], semester: Semester) -> list[Conflict]:
    """Paarweise Überschneidungen konkreter Termine."""
    slots: list[tuple[date, time, time, CourseOption]] = []
    for option in options:
        for event in option.events(semester):
            slots.append((event.day, event.start.time(), event.end.time(), option))

    conflicts: list[Conflict] = []
    slots.sort(key=lambda s: (s[0], s[1]))
    for i, (day_a, start_a, end_a, opt_a) in enumerate(slots):
        for day_b, start_b, end_b, opt_b in slots[i + 1 :]:
            if day_b != day_a:
                break
            if start_b >= end_a:
                continue
            if opt_a.key == opt_b.key:
                continue
            conflicts.append(
                Conflict(
                    day=day_a,
                    first=opt_a,
                    second=opt_b,
                    start=max(start_a, start_b),
                    end=min(end_a, end_b),
                )
            )
    return conflicts


TEMPLATE_CSV = """\
LV-Nummer;Titel;Art;Modul;ECTS;Gruppe;Tag;Von;Bis;Rhythmus;Raum;Dozent;Erster Termin;Anmeldefrist;Link;Hinweis
IN0001;Einführung in die Informatik 1;VO;IN0001;6;;Mo;10:00;12:00;wöchentlich;MI HS 1;;;;https://campus.tum.de/tumonline/...;
IN0001;Einführung in die Informatik 1;UE;IN0001;;Gruppe 01;Mi;14:00;16:00;wöchentlich;5605.EG.011;;;;https://campus.tum.de/tumonline/...;Übungsgruppe - nur eine wählen
IN0001;Einführung in die Informatik 1;UE;IN0001;;Gruppe 02;Do;10:00;12:00;wöchentlich;5605.EG.011;;;;https://campus.tum.de/tumonline/...;Übungsgruppe - nur eine wählen
"""
