"""Prüfungstermine und Anmeldefristen aus TUMonline lesen.

Klausuren stehen nicht im Lehrveranstaltungskalender: sie liegen nach der
Vorlesungszeit und haben eigene, deutlich frühere Anmeldefristen.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .catalog import CourseOption, Slot
from .paste import LV_NUMMER

MONATE = {
    "JAN": 1, "FEB": 2, "MÄR": 3, "MAR": 3, "APR": 4, "MAI": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OKT": 10, "NOV": 11, "DEZ": 12,
}

_TAG = re.compile(r"^(?P<tag>\d{1,2})$")
# Die eigene Prüfungsliste schreibt Tag, Monat und Jahr in eine Zeile:
# "07JAN 2027" statt "07" / "JAN 2027" auf der LV-Seite.
_DATUM_KOMPAKT = re.compile(
    r"^(?P<tag>\d{1,2})\s*(?P<monat>[A-ZÄÖÜ]{3})\.?\s*(?P<jahr>\d{4})$", re.IGNORECASE
)
# "MODULPRÜFUNG" leitet dort jeden Eintrag ein, danach Modulkennung und Titel.
_PRUEFUNGSKOPF = re.compile(r"^(?:MODUL)?PR(?:Ü|UE)FUNG$", re.IGNORECASE)
_MODULCODE = re.compile(r"^[A-Z]{2,3}\d{4,6}[A-Z]*$")
# Titelzeilen enden auf das Semester: "... - Bachelorkurs 2026 W"
_SEMESTER_SUFFIX = re.compile(r"\s+\d{4}\s*[WS]\s*$")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_BULLET = re.compile(r"^[*\-+]\s+")
_PRUEFER_INLINE = re.compile(r"^Prüfer\*?in:?\s*(?P<name>.+)$", re.IGNORECASE)
_MONAT_JAHR = re.compile(r"^(?P<monat>[A-ZÄÖÜ]{3})\.?\s+(?P<jahr>\d{4})$", re.IGNORECASE)
_ZEIT = re.compile(r"^(?P<von>\d{1,2}:\d{2})\s*[-–]\s*(?P<bis>\d{1,2}:\d{2})$")
_ZEITRAUM = re.compile(
    r"(?P<von>\d{2}\.\d{2}\.\d{4}),?\s*\d{2}:\d{2}\s*[-–]\s*"
    r"(?P<bis>\d{2}\.\d{2}\.\d{4}),?\s*\d{2}:\d{2}"
)
_DATUM = re.compile(r"(\d{2}\.\d{2}\.\d{4})")
_PRUEFER = re.compile(r"^Prüfer\*?in:?\s*$", re.IGNORECASE)
# Raumzeilen tragen immer die Raumkennung in Klammern - daran erkennt man sie
# zuverlässiger als an der Position, denn um sie herum steht viel Beiwerk.
_RAUM_MIT_CODE = re.compile(r"\(\s*\d{4}\.[A-Z0-9]{1,3}\.[0-9A-Za-z]+\s*\)")


def _entmarkdown(zeile: str) -> str:
    """'[Bichler, Martin](https://…)' -> 'Bichler, Martin', Listenpunkt weg."""
    ohne = _MARKDOWN_LINK.sub(r"\1", zeile or "")
    return _BULLET.sub("", ohne).strip()


def _termin(zeilen: list[str], index: int):
    """Termin ab `index` lesen - beide Schreibweisen.

    Liefert (Datum, von, bis, Index des ersten Zeilen nach dem Kopf) oder None.
    """
    if index + 1 >= len(zeilen):
        return None

    kompakt = _DATUM_KOMPAKT.match(zeilen[index])
    if kompakt:
        zeit = _ZEIT.match(zeilen[index + 1])
        treffer, weiter = kompakt, index + 2
    else:
        tag = _TAG.match(zeilen[index])
        monat = _MONAT_JAHR.match(zeilen[index + 1]) if index + 1 < len(zeilen) else None
        zeit = _ZEIT.match(zeilen[index + 2]) if index + 2 < len(zeilen) else None
        if not (tag and monat):
            return None
        treffer, weiter = None, index + 3
        if not zeit:
            return None
        monat_nr = MONATE.get(monat.group("monat").upper())
        if not monat_nr:
            return None
        return (date(int(monat.group("jahr")), monat_nr, int(tag.group("tag"))),
                datetime.strptime(zeit.group("von"), "%H:%M").time(),
                datetime.strptime(zeit.group("bis"), "%H:%M").time(),
                weiter)

    if not zeit:
        return None
    monat_nr = MONATE.get(treffer.group("monat").upper())
    if not monat_nr:
        return None
    return (date(int(treffer.group("jahr")), monat_nr, int(treffer.group("tag"))),
            datetime.strptime(zeit.group("von"), "%H:%M").time(),
            datetime.strptime(zeit.group("bis"), "%H:%M").time(),
            weiter)


def _datum(text: str) -> date | None:
    treffer = _DATUM.search(text or "")
    return datetime.strptime(treffer.group(1), "%d.%m.%Y").date() if treffer else None


def parse_exams(text: str) -> list[CourseOption]:
    """Zerlegt kopierte Prüfungsseiten in je einen Eintrag pro Termin.

    Zwei Formate: die Prüfungsliste einer Lehrveranstaltung ("Titel" /
    "Nummer" als Beschriftungen, Datum auf drei Zeilen) und die eigene
    Prüfungsübersicht ("MODULPRÜFUNG", Datum als "07JAN 2027", Markdown-Links).
    """
    zeilen = [_entmarkdown(z) for z in text.replace("\r\n", "\n").split("\n")]
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

        # Eigene Prüfungsliste: Kopfzeile, dann Modulkennung und Titel - je
        # nach Kopie auf zwei Zeilen oder in einer verklebt
        # ("WI001059EMCampus Munich: Financial Accounting").
        if _PRUEFUNGSKOPF.match(zeile):
            folgende = [z for z in zeilen[index + 1 : index + 5] if z][:2]
            kopf = folgende[0] if folgende else ""
            verklebt = LV_NUMMER.match(kopf)
            if _MODULCODE.match(kopf) and len(folgende) == 2:
                modul, roh = kopf, folgende[1]
            elif verklebt:
                modul, roh = verklebt.group("id"), kopf[verklebt.end():]
            else:
                modul = roh = ""
            if modul and roh:
                titel = _SEMESTER_SUFFIX.sub("", roh).strip(" -–—")
                ects = 0.0
            index += 1
            continue

        termin = _termin(zeilen, index)
        if termin and titel:
            tag_datum, von, bis, nach_kopf = termin

            # Der Block reicht bis zum nächsten Termin oder Eintrag.
            ende_block = len(zeilen)
            for weiter in range(nach_kopf, len(zeilen)):
                if (_termin(zeilen, weiter) or zeilen[weiter] == "Titel"
                        or _PRUEFUNGSKOPF.match(zeilen[weiter])):
                    ende_block = weiter
                    break
            block = zeilen[nach_kopf:ende_block]

            raeume = [z for z in block if _RAUM_MIT_CODE.search(z)]

            blocktext = "\n".join(block)
            zeitraum = _ZEITRAUM.search(blocktext)
            anmeldung_von = (datetime.strptime(zeitraum.group("von"), "%d.%m.%Y").date()
                             if zeitraum else None)
            anmeldung_bis = (datetime.strptime(zeitraum.group("bis"), "%d.%m.%Y").date()
                             if zeitraum else None)

            abmeldung = None
            for nr, eintrag in enumerate(block):
                if eintrag.startswith("Abmeldung bis"):
                    abmeldung = _datum(eintrag) or (
                        _datum(block[nr + 1]) if nr + 1 < len(block) else None)
                    break

            pruefer = ""
            for nr, eintrag in enumerate(block):
                inline = _PRUEFER_INLINE.match(eintrag)
                if _PRUEFER.match(eintrag) and nr + 1 < len(block):
                    pruefer = block[nr + 1]
                    break
                if inline:
                    pruefer = inline.group("name").strip()
                    break

            wiederholung = any(p.module == modul for p in pruefungen)
            anzeige = " / ".join(raeume[:3])

            pruefungen.append(
                CourseOption(
                    title=titel,
                    lv_id=modul,
                    kind="PRUEFUNG",
                    module=modul,
                    ects=ects,
                    group="Wiederholung" if wiederholung else "Haupttermin",
                    lecturer=pruefer,
                    room=anzeige,
                    rooms=tuple(raeume),
                    deadline=anmeldung_bis,
                    registration_start=anmeldung_von,
                    withdraw_until=abmeldung,
                    note=f"{len(raeume)} Räume" if len(raeume) > 1 else "",
                    slots=(Slot(day=tag_datum, start=von, end=bis, room=anzeige),),
                )
            )
            index = ende_block
            continue

        index += 1

    return pruefungen
