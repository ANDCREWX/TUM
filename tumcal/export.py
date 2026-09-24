"""Parser für den TUMonline-Terminexport (CSV).

Das ist die verlässlichste Quelle: TUMonline liefert je Termin eine Zeile mit
Datum, Uhrzeit, LV-Nummer, Art, Gruppe und Raum. Die Zeilen werden hier zu
Lehrveranstaltungen zusammengefasst.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from .catalog import CourseOption, Slot
from .model import detect_kind

# Spalten des Exports "Termine exportieren" bzw. des Kollisionsberichts.
SPALTEN = {"DATUM", "VON", "BIS", "TITEL"}
KOLLISION_SPALTEN = {"Kollisionskennung", "Datum", "von", "bis", "Name"}


def _decode(pfad: str | Path) -> str:
    roh = Path(pfad).read_bytes()
    for kodierung in ("utf-8-sig", "cp1252", "iso-8859-1"):
        try:
            return roh.decode(kodierung)
        except UnicodeDecodeError:
            continue
    return roh.decode("iso-8859-1", errors="replace")


def _zeilen(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text), delimiter=";", quotechar='"'))


def looks_like_export(text: str) -> bool:
    kopf = text.lstrip().splitlines()[0] if text.strip() else ""
    felder = {f.strip().strip('"') for f in kopf.split(";")}
    return SPALTEN.issubset(felder) or KOLLISION_SPALTEN.issubset(felder)


def _zeit(wert: str):
    wert = (wert or "").strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(wert, fmt).time()
        except ValueError:
            continue
    return None


def _datum(wert: str):
    wert = (wert or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(wert, fmt).date()
        except ValueError:
            continue
    return None


def parse_export(text: str) -> list[CourseOption]:
    """Terminzeilen zu Lehrveranstaltungen bündeln."""
    gebuendelt: dict[tuple, dict] = {}

    for zeile in _zeilen(text):
        tag = _datum(zeile.get("DATUM", ""))
        von = _zeit(zeile.get("VON", ""))
        bis = _zeit(zeile.get("BIS", ""))
        titel = (zeile.get("TITEL") or "").strip()
        if not (tag and von and bis and titel):
            continue

        art = (zeile.get("LV_ART") or "").strip()
        gruppe = (zeile.get("LV_GRUPPE") or "").strip()
        if gruppe.lower() in ("standardgruppe", "standard group"):
            gruppe = ""

        schluessel = ((zeile.get("LV_NUMMER") or "").strip(), titel, art, gruppe)
        eintrag = gebuendelt.setdefault(
            schluessel,
            {
                "lv_id": schluessel[0],
                "titel": titel,
                "art": art,
                "gruppe": gruppe,
                "slots": [],
                "dozent": (zeile.get("VORTRAGENDER_KONTAKTPERSON") or "").strip(),
            },
        )
        eintrag["slots"].append(
            Slot(day=tag, start=von, end=bis, room=(zeile.get("ORT") or "").strip())
        )

    out: list[CourseOption] = []
    for eintrag in gebuendelt.values():
        titel, modul = _titel_und_modul(eintrag["titel"])
        out.append(
            CourseOption(
                title=titel,
                lv_id=eintrag["lv_id"],
                kind=detect_kind(f"{eintrag['art']} {eintrag['titel']}"),
                module=modul,
                group=eintrag["gruppe"],
                lecturer=eintrag["dozent"],
                room=eintrag["slots"][0].room if eintrag["slots"] else "",
                slots=_merge_rooms(eintrag["slots"]),
            )
        )
    return sorted(out, key=lambda o: (o.title, o.kind, o.group))


def _merge_rooms(slots: list[Slot]) -> tuple[Slot, ...]:
    """Hörsaal und Übertragungsraum stehen als zwei Zeilen - ein Termin."""
    zusammen: dict[tuple, list[str]] = {}
    for slot in slots:
        raeume = zusammen.setdefault((slot.day, slot.start, slot.end), [])
        if slot.room and slot.room not in raeume:
            raeume.append(slot.room)
    return tuple(
        Slot(day=tag, start=von, end=bis, room=" / ".join(raeume))
        for (tag, von, bis), raeume in sorted(zusammen.items())
    )


def _titel_und_modul(roh: str) -> tuple[str, str]:
    """'Netzsicherheit (IN2101)' -> ('Netzsicherheit', 'IN2101')."""
    import re

    modul = ""
    treffer = re.search(r"[(\[]([A-Z]{2,3}\d{4,6}(?:_[A-Z0-9])?)", roh)
    if treffer:
        modul = treffer.group(1)
    titel = re.sub(r"\s*[(\[][^)\]]*[)\]]\s*", " ", roh)
    return re.sub(r"\s+", " ", titel).strip(" -–—,;:"), modul


def parse_collisions(text: str) -> list[tuple[str, str, str, str, str]]:
    """Kollisionsexport: (Kennung, Datum, von, bis, Name) je Zeile."""
    out = []
    for zeile in _zeilen(text):
        if not (zeile.get("Datum") and zeile.get("Name")):
            continue
        out.append((
            (zeile.get("Kollisionskennung") or "").strip(),
            (zeile.get("Datum") or "").strip(),
            (zeile.get("von") or "").strip(),
            (zeile.get("bis") or "").strip(),
            (zeile.get("Name") or "").strip(),
        ))
    return out


def load_export(pfad: str | Path) -> list[CourseOption]:
    return parse_export(_decode(pfad))
