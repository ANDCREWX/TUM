"""Raumcodes auswerten: Gebäude, Standort und enge Übergänge.

TUM-Räume heißen Gebäude.Geschoss.Raum ("5620.01.101"). Die Gebäudenummer
verrät den Standort - und damit, ob zwischen zwei aufeinanderfolgenden
Terminen ein Fußweg, eine U-Bahn-Fahrt oder gar nichts liegt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time

from .catalog import CourseOption
from .semester import Semester

_RAUMCODE = re.compile(r"\b(\d{4})\.[A-Z0-9]{1,3}\.[0-9A-Za-z]+")

# Standorte nach Gebäudenummer. Geprüft an nav.tum.de für die hier
# vorkommenden Gebäude; unbekannte Nummern bleiben ausdrücklich unbekannt,
# statt geraten zu werden.
STANDORTE: dict[str, str] = {
    "0": "Stammgelände",     # Arcisstraße, München Innenstadt
    "5": "Garching",         # Forschungszentrum Garching
    "81": "Garching",        # Galileo, Walther-von-Dyck-Str. 10
}

# Grobe Wegzeit zwischen Standorten in Minuten (Schätzung, U6 plus Fußwege).
WEGZEIT_STANDORT = 40
# Fußweg zwischen Gebäuden desselben Standorts.
WEGZEIT_GEBAEUDE = 10


@dataclass
class Transit:
    """Ein Übergang zwischen zwei aufeinanderfolgenden Terminen."""

    weekday: int
    day: date
    gap: int                       # Minuten zwischen Ende und nächstem Beginn
    first: CourseOption
    second: CourseOption
    first_room: str
    second_room: str

    @property
    def buildings(self) -> tuple[str, str]:
        return building(self.first_room), building(self.second_room)

    @property
    def campuses(self) -> tuple[str, str]:
        a, b = self.buildings
        return campus(a), campus(b)

    @property
    def verdict(self) -> str:
        a, b = self.buildings
        if not a or not b:
            return "unbekannt"
        if self.first_room == self.second_room:
            return "gleicher Raum"
        if a == b:
            return "gleiches Gebäude"
        ca, cb = self.campuses
        if ca and cb and ca != cb:
            return "anderer Standort"
        return "anderes Gebäude"

    @property
    def needed(self) -> int:
        """Grob benötigte Wegzeit in Minuten."""
        urteil = self.verdict
        if urteil == "gleicher Raum":
            return 0
        if urteil == "gleiches Gebäude":
            return 5
        if urteil == "anderer Standort":
            return WEGZEIT_STANDORT
        if urteil == "anderes Gebäude":
            return WEGZEIT_GEBAEUDE
        return 0

    @property
    def tight(self) -> bool:
        return self.gap < self.needed


def building(room: str) -> str:
    """'101, Hörsaal 1 (5620.01.101)' -> '5620'."""
    treffer = _RAUMCODE.search(room or "")
    return treffer.group(1) if treffer else ""


def campus(building_no: str) -> str:
    if not building_no:
        return ""
    for laenge in (2, 1):
        if building_no[:laenge] in STANDORTE:
            return STANDORTE[building_no[:laenge]]
    return ""


def _erster_raum(location: str) -> str:
    """Parallel gelistete Räume: der erste ist der Hauptraum."""
    return (location or "").split(" / ")[0].strip()


def transits(
    options: list[CourseOption], semester: Semester, max_gap: int = 30
) -> list[Transit]:
    """Aufeinanderfolgende Termine mit knapper Pause, je Wochentag einmal."""
    nach_tag: dict[date, list] = {}
    for option in options:
        for event in option.events(semester):
            nach_tag.setdefault(event.day, []).append(
                (event.start.time(), event.end.time(), option, _erster_raum(event.location))
            )

    gesehen: set[tuple] = set()
    out: list[Transit] = []
    for tag in sorted(nach_tag):
        eintraege = sorted(nach_tag[tag], key=lambda e: (e[0], e[1]))
        for (_, ende, opt_a, raum_a), (start, _, opt_b, raum_b) in zip(eintraege, eintraege[1:]):
            luecke = (start.hour * 60 + start.minute) - (ende.hour * 60 + ende.minute)
            if luecke < 0 or luecke > max_gap:
                continue
            schluessel = (tag.weekday(), opt_a.key, opt_b.key, ende, start)
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            out.append(
                Transit(weekday=tag.weekday(), day=tag, gap=luecke,
                        first=opt_a, second=opt_b, first_room=raum_a, second_room=raum_b)
            )
    return out
