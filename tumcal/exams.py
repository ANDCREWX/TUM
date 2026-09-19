"""Prüfungstermine und Anmeldefristen aus TUMonline lesen.

Klausuren stehen nicht im Lehrveranstaltungskalender: sie liegen nach der
Vorlesungszeit und haben eigene, deutlich frühere Anmeldefristen.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .catalog import CourseOption, Slot

MONATE = {
    "JAN": 1, "FEB": 2, "MÄR": 3, "MAR": 3, "APR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OKT": 10, "NOV": 11, "DEZ": 12,
}

_TAG = re.compile(r"^(?P<tag>\d{1,2})$")
_MONAT_JAHR = re.compile(r"^(?P<monat>[A-ZÄÖÜ]{3})\.?\s+(?P<jahr>\d{4})$", re.IGNORECASE)
_ZEIT = re.compile(r"^(?P<von>\d{1,2}:\d{2})\s*[-–]\s*(?P<bis>\d{1,2}:\d{2})$")
_ZEITRAUM = re.compile(
    r"(?P<von>\d{2}\.\d{2}\.\d{4}),?\s*\d{2}:\d{2}\s*[-–]\s*"
    r"(?P<bis>\d{2}\.\d{2}\.\d{4}),?\s*\d{2}:\d{2}"
)
_DATUM = re.compile(r"(\d{2}\.\d{2}\.\d{4})")
_PRUEFER = re.compile(r"^Prüfer\*?in:?\s*$", re.IGNORECASE)


def _datum(text: str) -> date | None:
    treffer = _DATUM.search(text or "")
    return datetime.strptime(treffer.group(1), "%d.%m.%Y").date() if treffer else None


def parse_exams(text: str) -> list[CourseOption]:
    """Zerlegt kopierte Prüfungsseiten in je einen Eintrag pro Termin."""
    zeilen = [z.strip() for z in text.replace("\r\n", "\n").split("\n")]
    pruefungen: list[CourseOption] = []

    titel = modul = ""
    ects = 0.0
    index = 0
    while index < len(zeilen):
        zeile = zeilen[index]

        if zeile == "Titel" and index + 1 < len(zeilen):
            titel = zeilen[index + 1]
            index += 2
            continue
        if zeile == "Nummer" and index + 1 < len(zeilen):
            modul = zeilen[index + 1]
            index += 2
            continue
        if zeile == "ECTS-Credits" and index + 1 < len(zeilen):
            zahl = re.search(r"\d+", zeilen[index + 1])
            ects = float(zahl.group(0)) if zahl else 0.0
            index += 2
            continue

        # Ein Termin beginnt mit Tag / Monat Jahr / Uhrzeit auf drei Zeilen.
        tag = _TAG.match(zeile)
        monat = _MONAT_JAHR.match(zeilen[index + 1]) if index + 1 < len(zeilen) else None
        zeit = _ZEIT.match(zeilen[index + 2]) if index + 2 < len(zeilen) else None
        if tag and monat and zeit and titel:
            monat_nr = MONATE.get(monat.group("monat").upper())
            if not monat_nr:
                index += 1
                continue
            tag_datum = date(int(monat.group("jahr")), monat_nr, int(tag.group("tag")))

            # Der Block reicht bis zum nächsten Termin.
            ende = len(zeilen)
            for weiter in range(index + 3, len(zeilen) - 2):
                if (_TAG.match(zeilen[weiter]) and _MONAT_JAHR.match(zeilen[weiter + 1])
                        and _ZEIT.match(zeilen[weiter + 2])):
                    ende = weiter
                    break
                if zeilen[weiter] == "Titel":
                    ende = weiter
                    break
            block = zeilen[index + 3 : ende]

            # Räume stehen vor "Prüfer*in:", Fristen dahinter.
            raeume: list[str] = []
            for eintrag in block:
                if _PRUEFER.match(eintrag) or eintrag.startswith(("Organisation", "Berechtigte")):
                    break
                if eintrag and not eintrag.startswith(("Anmelde", "Abmeldung")):
                    raeume.append(eintrag)

            blocktext = "\n".join(block)
            zeitraum = _ZEITRAUM.search(blocktext)
            anmeldung_von = (datetime.strptime(zeitraum.group("von"), "%d.%m.%Y").date()
                             if zeitraum else None)
            anmeldung_bis = (datetime.strptime(zeitraum.group("bis"), "%d.%m.%Y").date()
                             if zeitraum else None)

            abmeldung = None
            for nr, eintrag in enumerate(block):
                if eintrag.startswith("Abmeldung bis") and nr + 1 < len(block):
                    abmeldung = _datum(eintrag) or _datum(block[nr + 1])
                    break

            pruefer = ""
            for nr, eintrag in enumerate(block):
                if _PRUEFER.match(eintrag) and nr + 1 < len(block):
                    pruefer = block[nr + 1]
                    break

            von = datetime.strptime(zeit.group("von"), "%H:%M").time()
            bis = datetime.strptime(zeit.group("bis"), "%H:%M").time()
            wiederholung = any(p.module == modul for p in pruefungen)

            pruefungen.append(
                CourseOption(
                    title=titel,
                    lv_id=modul,
                    kind="PRUEFUNG",
                    module=modul,
                    ects=ects,
                    group="Wiederholung" if wiederholung else "Haupttermin",
                    lecturer=pruefer,
                    room=" / ".join(raeume[:3]),
                    deadline=anmeldung_bis,
                    registration_start=anmeldung_von,
                    withdraw_until=abmeldung,
                    note=f"{len(raeume)} Räume" if len(raeume) > 1 else "",
                    slots=(Slot(day=tag_datum, start=von, end=bis,
                                room=" / ".join(raeume[:3])),),
                )
            )
            index = ende
            continue

        index += 1

    return pruefungen
