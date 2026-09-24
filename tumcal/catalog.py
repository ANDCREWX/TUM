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
from collections import Counter
from itertools import product
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


class NoOptionLeft(RuntimeError):
    """Kein Wahlblock-Eintrag hat den Filter überlebt."""

    def __init__(self, blocks: list[str]):
        self.blocks = blocks
        namen = ", ".join(b.split("|")[0] for b in blocks)
        super().__init__(
            f"Für {namen} bleibt unter diesen Vorgaben keine einzige Gruppe übrig."
        )


@dataclass(frozen=True)
class Slot:
    """Ein konkreter, aus TUMonline übernommener Einzeltermin."""

    day: date
    start: time
    end: time
    room: str = ""


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
    registration_start: date | None = None
    withdraw_until: date | None = None
    provisional: bool = False         # Termin angenommen, nicht bestätigt
    participants: int | None = None   # aktuell angemeldet
    capacity: int | None = None       # Platzobergrenze
    # Liegen konkrete Termine vor, haben sie Vorrang vor Wochentag/Rhythmus:
    # TUMonline kennt Ausfalltermine und Raumwechsel, die keine Regel abbildet.
    slots: tuple[Slot, ...] = ()

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
        if self.provisional:
            return self._label() + " [vorläufig]"
        return self._label()

    def _label(self) -> str:
        if not self.group:
            return f"{self.title} ({self.kind_label})"
        group = self.group if self.group.lower().startswith("gruppe") else f"Gruppe {self.group}"
        return f"{self.title} ({self.kind_label}) · {group}"

    @property
    def online(self) -> bool:
        """Kein Weg an die Uni: Videokonferenz, Stream, reines Online-Format."""
        orte = [self.room] + [slot.room for slot in self.slots]
        text = " ".join(o for o in orte if o).lower()
        return bool(text) and any(
            wort in text for wort in ("online", "videokonferenz", "zoom", "digital", "stream")
        )

    @property
    def size(self) -> int | None:
        """Maß für 'wie voll ist die Gruppe' - gemeldete Zahl vor Kontingent."""
        return self.participants if self.participants is not None else self.capacity

    @property
    def earliest_start(self) -> time | None:
        starts = [s.start for s in self.slots]
        if self.start_time is not None:
            starts.append(self.start_time)
        return min(starts) if starts else None

    def weekly_patterns(self, min_count: int = 3) -> list[tuple[int, time, time, int]]:
        """Die wiederkehrenden Wochentermine als (Wochentag, von, bis, Anzahl).

        Eine LV hat oft mehrere Schienen zu verschiedenen Zeiten (Vorlesung
        und Übung). Ein einzelner Wert wie typical_start bildet das nicht ab.
        """
        if self.slots:
            zaehler = Counter((s.day.weekday(), s.start, s.end) for s in self.slots)
            regulaer = [(wd, von, bis, n) for (wd, von, bis), n in zaehler.items()
                        if n >= min_count]
            if not regulaer:  # sehr kurze Reihen: alles gilt als regulär
                regulaer = [(wd, von, bis, n) for (wd, von, bis), n in zaehler.items()]
            return sorted(regulaer)
        if self.weekday is not None and self.start_time and self.end_time:
            return [(self.weekday, self.start_time, self.end_time, 0)]
        return []

    @property
    def earliest_regular_start(self) -> time | None:
        """Frühester Beginn unter den regelmäßigen Terminen.

        Maßgeblich für 'nichts vor X Uhr': Wer die LV belegt, muss zu allen
        ihren Schienen, nicht nur zur häufigsten.
        """
        muster = self.weekly_patterns()
        return min(m[1] for m in muster) if muster else self.typical_start

    @property
    def typical_start(self) -> time | None:
        """Übliche Anfangszeit. Ein einzelner verschobener Termin darf eine
        Gruppe nicht aus der Auswahl kippen - er wird gesondert gemeldet."""
        if self.slots:
            zaehler = Counter(slot.start for slot in self.slots)
            return zaehler.most_common(1)[0][0]
        return self.start_time

    def early_slots(self, not_before: time) -> list[Slot]:
        """Einzeltermine, die vor der Wunschzeit beginnen."""
        return [s for s in self.slots if s.start < not_before]

    @property
    def exclusive_key(self) -> str:
        """Gruppen derselben Veranstaltung schließen einander aus.

        Leer, wenn die LV nur eine Gruppe hat - dann ist nichts zu wählen.
        """
        if not self.group:
            return ""
        return f"{self.module or self.lv_id or self.title}|{self.kind}"

    @property
    def slots_known(self) -> bool:
        if self.slots:
            return True
        return self.start_time is not None and self.end_time is not None

    def occurrences(self, semester: Semester) -> list[date]:
        """Konkrete Termine über die Vorlesungszeit."""
        if self.slots:
            return sorted({slot.day for slot in self.slots})
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
        if self.slots:
            return [self._event(s.day, s.start, s.end, s.room) for s in sorted(
                self.slots, key=lambda s: (s.day, s.start))]
        if self.start_time is None or self.end_time is None:
            return []
        return [
            self._event(day, self.start_time, self.end_time, self.room)
            for day in self.occurrences(semester)
        ]

    def _event(self, day: date, start_time: time, end_time: time, room: str) -> CourseEvent:
        start = datetime.combine(day, start_time, tzinfo=BERLIN)
        end = datetime.combine(day, end_time, tzinfo=BERLIN)
        if end <= start:  # über Mitternacht ist im LV-Betrieb nicht vorgesehen
            end = start + timedelta(hours=2)
        return CourseEvent(
            summary=self.label,
            title=self.title,
            start=start,
            end=end,
            location=room,
            room=extract_room(room),
            course_code=self.module or self.lv_id,
            kind=self.kind,
            lecturer=self.lecturer,
            description=self.note,
        )


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

    options: list[CourseOption] = []
    for item, row in zip(data, rows):
        option = _row_to_option(row, mapping)
        if option is None:
            continue
        raw_slots = item.get("slots") if isinstance(item, dict) else None
        if isinstance(raw_slots, list) and raw_slots:
            slots = tuple(
                Slot(
                    day=parse_date_value(str(s.get("date", ""))),
                    start=parse_time(str(s.get("start", ""))),
                    end=parse_time(str(s.get("end", ""))),
                    room=str(s.get("room", "")),
                )
                for s in raw_slots
                if parse_date_value(str(s.get("date", "")))
                and parse_time(str(s.get("start", "")))
                and parse_time(str(s.get("end", "")))
            )
            option = replace(option, slots=slots)
        options.append(option)
    return options


def looks_like_paste(text: str) -> bool:
    """Aus TUMonline kopierter Text statt Tabelle?"""
    if len(re.findall(r"^\s*Termin\s+", text, flags=re.MULTILINE)) >= 2:
        return True
    # Einzelne LV-Seite: Titel/Nummer als Label plus kompakte Serienangabe.
    return bool(
        re.search(r"^\s*Titel\s*$", text, flags=re.MULTILINE)
        and re.search(r"\bvon\s+\d{1,2}\.\d{1,2}\.\d{4}\s+bis\s+\d{1,2}\.\d{1,2}\.\d{4}", text)
    )


def load_catalog(path: str | Path) -> list[CourseOption]:
    from .export import _decode, looks_like_export, parse_export

    path = Path(path)
    text = _decode(path)
    if looks_like_export(text):
        return parse_export(text)
    if path.suffix.lower() == ".json" or text.lstrip()[:1] in "[{":
        return load_catalog_json(text)
    if looks_like_paste(text):
        from .paste import parse_paste

        options = parse_paste(text)
        if not options:
            from .paste import parse_lv_page

            options = parse_lv_page(text)
        if not options:
            raise CatalogError(
                "Der Text sieht nach einer TUMonline-Kopie aus, enthält aber keine "
                "erkennbaren Veranstaltungen. Bitte Kopfzeile der LV mitkopieren."
            )
        return options
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


def project_to_semester(
    options: list[CourseOption], semester: Semester
) -> list[CourseOption]:
    """Rechnet Einträge aus einem anderen Semester auf die Vorlesungszeit um.

    Übernommen werden nur Wochentag und Uhrzeit - das Einzige, was sich aus
    einem vergangenen Semester überhaupt vernünftig übertragen lässt. Das
    Ergebnis ist ausdrücklich als vorläufig gekennzeichnet.
    """
    fremd = {id(o) for o, _ in out_of_semester(options, semester)}
    out: list[CourseOption] = []
    for option in options:
        if id(option) not in fremd:
            out.append(option)
            continue

        wochentag = option.weekday
        von, bis = option.start_time, option.end_time
        if wochentag is None and option.slots:
            # Aus Einzelterminen den üblichen Wochentag und die Regelzeit ziehen.
            wochentag = Counter(s.day.weekday() for s in option.slots).most_common(1)[0][0]
            von = option.typical_start
            bis = Counter(s.end for s in option.slots).most_common(1)[0][0]
        if wochentag is None or von is None or bis is None:
            out.append(option)
            continue

        herkunft = option.note or "aus einem anderen Semester übernommen"
        out.append(
            replace(
                option,
                slots=(),
                weekday=wochentag,
                start_time=von,
                end_time=bis,
                first_date=None,
                last_date=None,
                rhythm=RHYTHM_WEEKLY,
                provisional=True,
                note=f"Zeitslot übernommen ({herkunft}) — für dieses Semester unbestätigt",
            )
        )
    return out


def out_of_semester(
    options: list[CourseOption], semester: Semester
) -> list[tuple[CourseOption, str]]:
    """Einträge, deren Termine außerhalb der Vorlesungszeit liegen.

    Ein LV-Eintrag aus einem anderen Semester liefert sonst schlicht keine
    Termine und verschwindet unbemerkt aus dem Kalender.
    """
    draussen: list[tuple[CourseOption, str]] = []
    for option in options:
        if not option.slots_known:
            continue

        if option.slots:
            tage = [slot.day for slot in option.slots]
        elif option.first_date or option.last_date:
            tage = [d for d in (option.first_date, option.last_date) if d]
        else:
            continue  # reine Wochentagsregel gilt per Definition im Semester

        if any(semester.lecture_start <= tag <= semester.lecture_end for tag in tage):
            continue
        zeitraum = (f"{min(tage):%d.%m.%Y}–{max(tage):%d.%m.%Y}"
                    if len(tage) > 1 else f"{tage[0]:%d.%m.%Y}")
        draussen.append((option, zeitraum))
    return draussen


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


@dataclass
class Combination:
    """Eine konfliktfreie Auswahl: je eine Gruppe pro Wahlpflichtblock."""

    options: list[CourseOption]
    days: int
    campus_days: int          # Tage, an denen man tatsächlich vor Ort sein muss
    gap_minutes: int          # Leerlauf zwischen Terminen, Schnitt pro Woche

    @property
    def total_size(self) -> int:
        """Summe der Gruppengrößen - kleiner ist voller Hörsaal-freier."""
        return sum(o.size or 0 for o in self.groups)

    @property
    def earliest(self) -> time | None:
        starts = [o.earliest_start for o in self.options if o.earliest_start]
        return min(starts) if starts else None

    def exceptions(self, not_before: time) -> list[tuple[CourseOption, Slot]]:
        """Einzelne Ausreißer-Termine trotz eingehaltener Regelzeit."""
        # Nur wählbare Gruppen: fest stehende Veranstaltungen werden einmal
        # zentral gemeldet, nicht bei jeder Kombination erneut.
        out = []
        for option in self.groups:
            if option.earliest_regular_start and option.earliest_regular_start >= not_before:
                out.extend((option, slot) for slot in option.early_slots(not_before))
        return out

    @property
    def groups(self) -> list[CourseOption]:
        return [o for o in self.options if o.group]

    def shape(self, semester: Semester) -> tuple:
        """Zeitliche Signatur - Kombinationen, die sich nur im Raum
        unterscheiden, sind für die Planung dieselbe Woche."""
        slots = set()
        for option in self.groups:
            for event in option.events(semester):
                slots.add((event.start.weekday(), event.start.strftime("%H:%M"),
                           event.end.strftime("%H:%M"), option.exclusive_key))
        return tuple(sorted(slots))


def _day_shape(options: list[CourseOption], semester: Semester) -> tuple[int, int, int]:
    """Belegte Wochentage, davon Präsenztage, und Leerlauf zwischen Terminen."""
    per_day: dict[date, list[tuple[time, time]]] = {}
    campus: set[int] = set()
    for option in options:
        for event in option.events(semester):
            per_day.setdefault(event.day, []).append((event.start.time(), event.end.time()))
            if not option.online:
                campus.add(event.day.weekday())

    weekdays = {day.weekday() for day in per_day}
    gaps = 0
    for spans in per_day.values():
        spans.sort()
        for (_, end), (start, _) in zip(spans, spans[1:]):
            if start > end:
                gaps += (start.hour * 60 + start.minute) - (end.hour * 60 + end.minute)

    wochen = len({(day.isocalendar()[0], day.isocalendar()[1]) for day in per_day}) or 1
    return len(weekdays), len(campus), round(gaps / wochen)


def combinations(
    options: list[CourseOption],
    semester: Semester,
    limit: int = 2000,
    not_before: time | None = None,
    prefer_small: bool = False,
) -> tuple[list[Combination], int]:
    """Alle konfliktfreien Kombinationen; je eine Gruppe pro Wahlblock.

    not_before  - wählbare Gruppen, die früher beginnen, entfallen. Fest
                  stehende Veranstaltungen bleiben davon unberührt; sie sind
                  nicht wählbar und müssen gesondert gemeldet werden.
    prefer_small - kleine Gruppen vor kompakter Woche einsortieren.

    Gibt zusätzlich zurück, wie viele Kombinationen insgesamt möglich waren.
    """
    blocks: dict[str, list[CourseOption]] = {}
    fixed: list[CourseOption] = []
    alle_bloecke: set[str] = {
        o.exclusive_key for o in options if o.exclusive_key and o.slots_known
    }
    for option in options:
        if not option.slots_known:
            # Ohne Termine lässt sich nichts kombinieren; der Eintrag bleibt
            # trotzdem im Plan, damit er nicht vergessen wird.
            fixed.append(option)
            continue
        if option.exclusive_key:
            if (not_before and option.earliest_regular_start
                    and option.earliest_regular_start < not_before):
                continue
            blocks.setdefault(option.exclusive_key, []).append(option)
        else:
            fixed.append(option)

    leer = sorted(alle_bloecke - set(blocks))
    if leer:
        # Ein Block ohne verbleibende Gruppe heißt: diese Veranstaltung ist
        # unter den Vorgaben gar nicht belegbar.
        raise NoOptionLeft(leer)

    if not blocks:
        conflicts = find_conflicts(fixed, semester)
        if conflicts:
            return [], 1
        days, campus, gaps = _day_shape(fixed, semester)
        return [Combination(options=list(fixed), days=days, campus_days=campus,
                            gap_minutes=gaps)], 1

    keys = sorted(blocks)
    total = 1
    for key in keys:
        total *= len(blocks[key])

    found: list[Combination] = []
    checked = 0
    for picks in product(*(blocks[key] for key in keys)):
        checked += 1
        if checked > limit:
            break
        selection = fixed + list(picks)
        if find_conflicts(selection, semester):
            continue
        days, campus, gaps = _day_shape(selection, semester)
        found.append(Combination(options=selection, days=days, campus_days=campus,
                                 gap_minutes=gaps))

    # Präsenztage zählen zuerst: online zu Hause ist kein Uni-Besuch.
    if prefer_small:
        found.sort(key=lambda c: (c.campus_days, c.days, c.total_size, c.gap_minutes))
    else:
        found.sort(key=lambda c: (c.campus_days, c.days, c.gap_minutes))
    return found, total


TEMPLATE_CSV = """\
LV-Nummer;Titel;Art;Modul;ECTS;Gruppe;Tag;Von;Bis;Rhythmus;Raum;Dozent;Erster Termin;Anmeldefrist;Link;Hinweis
IN0001;Einführung in die Informatik 1;VO;IN0001;6;;Mo;10:00;12:00;wöchentlich;MI HS 1;;;;https://campus.tum.de/tumonline/...;
IN0001;Einführung in die Informatik 1;UE;IN0001;;Gruppe 01;Mi;14:00;16:00;wöchentlich;5605.EG.011;;;;https://campus.tum.de/tumonline/...;Übungsgruppe - nur eine wählen
IN0001;Einführung in die Informatik 1;UE;IN0001;;Gruppe 02;Do;10:00;12:00;wöchentlich;5605.EG.011;;;;https://campus.tum.de/tumonline/...;Übungsgruppe - nur eine wählen
"""
