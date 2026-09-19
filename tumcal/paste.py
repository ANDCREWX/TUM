"""Parser für aus TUMonline kopierte LV-Listen.

Die Terminübersicht in TUMonline lässt sich markieren und kopieren. Das
Ergebnis ist unstrukturierter Text - aber mit konkreten Einzelterminen, die
Ausfalltage, Raumwechsel und abweichende Uhrzeiten bereits enthalten. Das ist
verlässlicher als jede aus Wochentag und Rhythmus errechnete Reihe.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time

from .catalog import WEEKDAY_CODES, CourseOption, Slot
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

# Kompakte Serienangabe einer LV-Seite:
# "Montag  , 10:00 - 12:00 von 13.04.2026 bis 13.07.2026"
_SERIE = re.compile(
    r"^(?P<tag>Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag)\s*,?\s*"
    r"(?P<von>\d{1,2}:\d{2})\s*[-–]\s*(?P<bis>\d{1,2}:\d{2})\s+"
    r"von\s+(?P<start>\d{1,2}\.\d{1,2}\.\d{4})\s+bis\s+(?P<ende>\d{1,2}\.\d{1,2}\.\d{4})",
    re.IGNORECASE,
)
# "Vorlesung (VO)" / "Übung (UE)"
_ART = re.compile(r"\((?P<kind>[A-Z]{2,3})\)\s*$")

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


def _label_wert(zeilen: list[str], label: str) -> str:
    """Auf einer LV-Seite steht der Wert in der Folgezeile."""
    for index, zeile in enumerate(zeilen):
        if zeile.strip() == label and index + 1 < len(zeilen):
            return zeilen[index + 1].strip()
    return ""


def parse_lv_page(text: str) -> list[CourseOption]:
    """Einzelne LV-Seite mit kompakter Serienangabe statt Terminliste."""
    zeilen = [z.strip() for z in text.replace("\r\n", "\n").split("\n")]

    titel = _label_wert(zeilen, "Titel")
    if not titel:
        return []
    nummer = _label_wert(zeilen, "Nummer")
    art_roh = _label_wert(zeilen, "Art")
    art = _ART.search(art_roh)
    kind = art.group("kind") if art else detect_kind(f"{art_roh} {titel}")
    angeboten = _label_wert(zeilen, "Angeboten im Semester")
    sprache = _label_wert(zeilen, "Unterrichtssprache/n") or _label_wert(zeilen, "Unterrichtssprache")

    # Modulkennung steht bei diesen Seiten in der Studienplan-Verlinkung.
    modul = ""
    modul_treffer = re.search(r"\[([A-Z]{2}\d{4,6}(?:_[A-Z])?)\]", text)
    if modul_treffer:
        modul = modul_treffer.group(1)

    # "Online: Videokonferenz" steht als eigene Zeile unter der Serie.
    ort = next((z for z in zeilen if z.lower().startswith("online")), "")
    hinweise = [h for h in (angeboten, sprache) if h]
    out: list[CourseOption] = []
    for zeile in zeilen:
        serie = _SERIE.match(zeile)
        if not serie:
            continue
        out.append(
            CourseOption(
                title=titel,
                lv_id=nummer,
                kind=kind,
                module=modul,
                weekday=WEEKDAY_CODES[serie.group("tag").lower()],
                start_time=_parse_time(serie.group("von")),
                end_time=_parse_time(serie.group("bis")),
                first_date=datetime.strptime(serie.group("start"), "%d.%m.%Y").date(),
                last_date=datetime.strptime(serie.group("ende"), "%d.%m.%Y").date(),
                room=ort,
                note=" · ".join(hinweise),
            )
        )
    return out


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
                    participants=group["participants"],
                    capacity=group["capacity"],
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
            if teilnehmer.group("count"):
                group["participants"] = int(teilnehmer.group("count"))
                group["note"] = f"{group['participants']} Teilnehmende"
            else:
                group["capacity"] = int(teilnehmer.group("max"))
                group["note"] = f"max. {group['capacity']} Plätze"
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
                "participants": None,
                "capacity": None,
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
            "participants": o.participants,
            "capacity": o.capacity,
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
