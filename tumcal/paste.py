"""Parser für aus TUMonline kopierte LV-Listen.

Die Terminübersicht in TUMonline lässt sich markieren und kopieren. Das
Ergebnis ist unstrukturierter Text - aber mit konkreten Einzelterminen, die
Ausfalltage, Raumwechsel und abweichende Uhrzeiten bereits enthalten. Das ist
verlässlicher als jede aus Wochentag und Rhythmus errechnete Reihe.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time

from .catalog import CourseOption, Slot
from .model import detect_kind

# "Termin  MI, 14.10.2026, 09:45 - 11:15"
_TERMIN = re.compile(
    r"Termin\s+(?:(?P<wd>[A-ZÄÖÜ]{2}),\s*)?(?P<date>\d{1,2}\.\d{1,2}\.\d{4}),?\s*"
    r"(?P<start>\d{1,2}[:.]\d{2})\s*[-–]\s*(?P<end>\d{1,2}[:.]\d{2})"
)
# "Raum N 1190, Hans-Heinrich-Meinke-Hörsaal (0101.02.190)"
_RAUM = re.compile(r"^Raum\s+(?P<room>.+?)\s*$")
# "Gruppe 1", "Gruppe A", "Standardgruppe"
_GRUPPE = re.compile(
    r"^(?P<group>Standardgruppe|Standard group|(?:Gruppe|Group)\s+\S+)\s*$", re.IGNORECASE
)
# "(Teilnehmer*innen: 292 / max. unbegrenzt)"
_TEILNEHMER = re.compile(
    r"Teilnehmer\*?innen:\s*(?:(?P<count>\d+)|max\.?\s*(?P<max>\d+))", re.IGNORECASE
)
# Kopfzeile endet auf das LV-Kürzel: "... - Lecture - VO"
_KOPF = re.compile(r"^(?P<rest>.+?)\s+-\s+(?P<kind>[A-Z]{2,3})\s*$")
# "... - UEGleiche LVs:" -> der Verweisblock hängt ohne Trenner am Kürzel.
_GLEICHE_LVS = re.compile(r"Gleiche\s+LVs:\s*$", re.IGNORECASE)
# Nur ein Weekday-Zusatz bleibt im Titel stehen, alles andere fliegt raus.
_WOCHENTAG_KLAMMER = re.compile(r"^\((Mo|Di|Mi|Do|Fr|Sa|So)\)$", re.IGNORECASE)
# Modulkennung in Klammern: (IN0015), (WI000021_E, englisch)
_MODUL = re.compile(r"\((?P<code>[A-Z]{2}\d{4,6}(?:_[A-Z])?)\b")
# Führende LV-Nummer: "0240967009Diskrete Strukturen" oder "WI000021EVEconomics I"
_LV_NUMMER = re.compile(r"^(?P<id>\d{6,}|[A-Z]{2}\d{6}[A-ZÄÖÜ]{0,2})(?=[A-ZÄÖÜ(])")

# Zeilen, die in der Kopierausgabe nur Bedienelemente sind.
_RAUSCHEN = {
    "weniger anzeigen", "mehr anzeigen", "... alle anzeigen", "alle anzeigen",
    "nächster termin", "naechster termin", "präferenz bearbeiten",
    "praeferenz bearbeiten", "niedrighoch", "niedrig", "hoch", "vortragende*r",
    "vortragender", "vortragende", "-", "anmelden", "abmelden",
}


def _is_noise(line: str) -> bool:
    return line.strip().lower().lstrip(". ") in _RAUSCHEN


def _parse_time(token: str) -> time:
    hour, minute = re.split(r"[:.]", token)
    return time(int(hour), int(minute))


def _clean_title(rest: str) -> tuple[str, str, str]:
    """Kopfzeile zerlegen in (LV-Nummer, Titel, Modulkennung)."""
    lv_id = ""
    match = _LV_NUMMER.match(rest)
    if match:
        lv_id = match.group("id")
        rest = rest[match.end():]

    module_match = _MODUL.search(rest)
    module = module_match.group("code") if module_match else ""

    def _klammer(match: re.Match) -> str:
        # "(Mo)" trägt Information (Übungsschiene), "(IN0015)" nicht.
        return match.group(0) if _WOCHENTAG_KLAMMER.match(match.group(0)) else " "

    title = re.sub(r"\([^)]*\)", _klammer, rest)
    title = re.sub(r"\s+-\s+(Lecture|Vorlesung|Übung|Exercise|Practical)\s*$", "", title,
                   flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" -–—,;:")
    return lv_id, title, module


def _merge_slots(slots: list[Slot]) -> tuple[Slot, ...]:
    """Parallel gelistete Räume zu einem Termin zusammenfassen.

    TUMonline zeigt Hörsaal und Übertragungsraum als zwei Zeilen mit
    identischer Zeit - im Kalender ist das ein Termin.
    """
    merged: dict[tuple[date, time, time], list[str]] = {}
    for slot in slots:
        key = (slot.day, slot.start, slot.end)
        rooms = merged.setdefault(key, [])
        if slot.room and slot.room not in rooms:
            rooms.append(slot.room)
    return tuple(
        Slot(day=day, start=start, end=end, room=" / ".join(rooms))
        for (day, start, end), rooms in sorted(merged.items())
    )


def parse_paste(text: str) -> list[CourseOption]:
    """Zerlegt kopierten TUMonline-Text in anmeldbare Veranstaltungen."""
    options: list[CourseOption] = []

    course: dict | None = None      # aktuelle Lehrveranstaltung (Kopfzeile)
    group: dict | None = None       # aktuelle Gruppe innerhalb der LV
    pending_lecturers = False

    def flush_group() -> None:
        nonlocal group
        if course and group and group["slots"]:
            options.append(
                CourseOption(
                    title=course["title"],
                    lv_id=course["lv_id"],
                    kind=course["kind"],
                    module=course["module"],
                    group=group["name"],
                    lecturer="; ".join(course["lecturers"]),  # Namen enthalten selbst Kommata
                    room=group["slots"][0].room if group["slots"] else "",
                    note=group["note"],
                    slots=_merge_slots(group["slots"]),
                )
            )
        group = None

    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue

        termin = _TERMIN.search(line)
        if termin and group is not None:
            pending_lecturers = False
            room = ""
            # Der Raum steht in der Folgezeile.
            for follow in lines[index + 1 : index + 3]:
                raum = _RAUM.match(follow.strip())
                if raum:
                    room = raum.group("room")
                    break
                if _TERMIN.search(follow):
                    break
            group["slots"].append(
                Slot(
                    day=datetime.strptime(termin.group("date"), "%d.%m.%Y").date(),
                    start=_parse_time(termin.group("start")),
                    end=_parse_time(termin.group("end")),
                    room=room,
                )
            )
            continue

        if _RAUM.match(line) or _is_noise(line):
            if line.lower().startswith("vortragende"):
                pending_lecturers = True
            continue

        teilnehmer = _TEILNEHMER.search(line)
        if teilnehmer and group is not None:
            group["note"] = (
                f"{teilnehmer.group('count')} Teilnehmende"
                if teilnehmer.group("count")
                else f"max. {teilnehmer.group('max')} Plätze"
            )
            continue

        gruppe = _GRUPPE.match(line)
        folgt_teilnehmerzahl = any(
            _TEILNEHMER.search(f) for f in lines[index + 1 : index + 3] if f.strip()
        )
        if course is not None and (gruppe or (folgt_teilnehmerzahl and len(line) < 60)):
            flush_group()
            name = gruppe.group("group") if gruppe else line
            group = {
                "name": "" if name.lower().replace(" ", "") in
                        ("standardgruppe", "standardgroup") else name,
                "slots": [],
                "note": "",
            }
            pending_lecturers = False
            continue

        kopf = _KOPF.match(_GLEICHE_LVS.sub("", line).strip())
        if kopf and kopf.group("kind").isupper():
            rest = kopf.group("rest")
            # Eine echte Kopfzeile klebt die LV-Nummer an den Titel. Die unter
            # "Gleiche LVs:" aufgezählten Verweise haben dort ein Leerzeichen -
            # sie sind keine eigenen Veranstaltungen.
            if rest[:1].isdigit() and not _LV_NUMMER.match(rest):
                continue
            flush_group()
            lv_id, title, module = _clean_title(rest)
            if not title:
                continue
            course = {
                "lv_id": lv_id,
                "title": title,
                "module": module,
                "kind": detect_kind(f"{kopf.group('kind')} {title}"),
                "lecturers": [],
            }
            pending_lecturers = False
            continue

        # Zeile direkt nach "Vortragende*r" -> Name; sonst meist die
        # wiederholte Titelzeile unter der Kopfzeile, die nichts hinzufügt.
        if pending_lecturers and course is not None and "," in line and len(line) < 60:
            course["lecturers"].append(line)
            continue

    flush_group()
    return options


def to_json_catalog(options: list[CourseOption]) -> list[dict]:
    """Serialisiert inkl. Einzelterminen, damit der Katalog speicherbar ist."""
    return [
        {
            "LV-Nummer": o.lv_id,
            "Titel": o.title,
            "Art": o.kind,
            "Modul": o.module,
            "ECTS": o.ects or "",
            "Gruppe": o.group,
            "Dozent": o.lecturer,
            "Link": o.url,
            "Hinweis": o.note,
            "slots": [
                {
                    "date": s.day.isoformat(),
                    "start": s.start.strftime("%H:%M"),
                    "end": s.end.strftime("%H:%M"),
                    "room": s.room,
                }
                for s in o.slots
            ],
        }
        for o in options
    ]
