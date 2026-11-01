"""Raumcodes auswerten: Gebäude, Standort und enge Übergänge.

TUM-Räume heißen Gebäude.Geschoss.Raum ("5620.01.101"). Die Gebäudenummer
verrät den Standort - und damit, ob zwischen zwei aufeinanderfolgenden
Terminen ein Fußweg, eine U-Bahn-Fahrt oder gar nichts liegt.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, time

from .catalog import CourseOption, Slot, matches_selector
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


def _raeume(location: str) -> list[str]:
    """Parallel gelistete Räume eines Termins einzeln."""
    return [teil.strip() for teil in (location or "").split(" / ") if teil.strip()]


@dataclass(frozen=True)
class RoomWish:
    """Wunschraum für eine Veranstaltung: 'IN0015=MW 2001'."""

    selector: str   # Modul, LV-Nummer oder Teil des Titels
    pattern: str    # Raumname oder Raumcode, Teiltreffer genügt


def parse_room_wish(value: str) -> RoomWish:
    selector, _, pattern = (value or "").partition("=")
    selector, pattern = selector.strip(), pattern.strip()
    if not selector or not pattern:
        raise ValueError(
            "--room erwartet AUSWAHL=RAUM, etwa --room \"IN0015=MW 2001\". "
            f"Bekommen: {value!r}"
        )
    return RoomWish(selector=selector, pattern=pattern)


def _trifft_raum(room: str, pattern: str) -> bool:
    return pattern.casefold() in (room or "").casefold()


WOCHENTAGE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def choose_rooms(
    options: list[CourseOption], wishes: list[RoomWish]
) -> tuple[list[CourseOption], list[str]]:
    """Bei parallel gelisteten Räumen den gewünschten auswählen.

    TUMonline listet Hörsaal und Übertragungsraum als zwei Zeilen zur selben
    Zeit; der Planer fasst sie zu einem Termin zusammen. Wer weiß, in welchen
    der beiden Säle er geht, will genau den im Kalender haben - auch weil die
    Wegzeit zum nächsten Termin daran hängt.

    Es wird ausgewählt, nicht erfunden: Steht der Wunschraum an einem Termin
    nicht im Angebot, bleibt er unverändert und wird gemeldet.
    """
    if not wishes:
        return options, []

    ergebnis: list[CourseOption] = []
    berichte: list[str] = []
    # Ein Modulcode trifft die Vorlesung und alle ihre Übungsgruppen. Nur die
    # Einträge zu melden, die den Raum anbieten, hält die Ausgabe lesbar;
    # getroffen-aber-ohne-Angebot ist der Normalfall, nicht die Ausnahme.
    getroffen: Counter[RoomWish] = Counter()
    bedient: Counter[RoomWish] = Counter()
    for option in options:
        wunsch = next(
            (w for w in wishes if matches_selector(option, w.selector)), None
        )
        if wunsch is None:
            ergebnis.append(option)
            continue
        getroffen[wunsch] += 1
        neu, bericht = _waehle_raum(option, wunsch)
        ergebnis.append(neu)
        if bericht:
            bedient[wunsch] += 1
            berichte.extend(bericht)

    for wunsch in wishes:
        if not getroffen[wunsch]:
            berichte.append(
                f"--room {wunsch.selector}={wunsch.pattern}: keine Veranstaltung "
                f"im Katalog passt auf „{wunsch.selector}“."
            )
        elif not bedient[wunsch]:
            berichte.append(
                f"--room {wunsch.selector}={wunsch.pattern}: „{wunsch.pattern}“ "
                f"steht in keinem Termin der {getroffen[wunsch]} passenden "
                f"Einträge — nichts geändert."
            )
    return ergebnis, berichte


def _waehle_raum(
    option: CourseOption, wunsch: RoomWish
) -> tuple[CourseOption, list[str]]:
    angebot = [r for slot in option.slots for r in _raeume(slot.room)]
    angebot += _raeume(option.room)
    ziel = next((r for r in angebot if _trifft_raum(r, wunsch.pattern)), "")
    if not ziel:
        # Bietet dieser Eintrag den Raum nicht an, war er nicht gemeint.
        # choose_rooms meldet den Fall gesammelt, falls ihn niemand anbietet.
        return option, []

    gebaeude = building(ziel)
    gesetzt = 0
    ersatz: Counter[tuple[int, str]] = Counter()
    offen: Counter[int] = Counter()

    neue_slots: list[Slot] = []
    for slot in option.slots:
        auswahl = _raeume(slot.room)
        treffer = next((r for r in auswahl if _trifft_raum(r, wunsch.pattern)), "")
        if treffer:
            gesetzt += 1
            neue_slots.append(replace(slot, room=treffer))
            continue
        # Kein Wunschraum: ein Raum im selben Gebäude ist der nächstbeste.
        nachbar = next(
            (r for r in auswahl if gebaeude and building(r) == gebaeude), ""
        )
        if nachbar:
            ersatz[(slot.day.weekday(), nachbar)] += 1
            neue_slots.append(replace(slot, room=nachbar))
        else:
            offen[slot.day.weekday()] += 1
            neue_slots.append(slot)

    neuer_raum = option.room
    if option.slots:
        # Der Kopfeintrag nennt sonst weiter einen Raum, in dem nach der Wahl
        # kein einziger Termin mehr stattfindet.
        haeufigster = Counter(s.room for s in neue_slots if s.room).most_common(1)
        if haeufigster:
            neuer_raum = haeufigster[0][0]
    elif _raeume(option.room):
        treffer = next(
            (r for r in _raeume(option.room) if _trifft_raum(r, wunsch.pattern)), ""
        )
        if treffer:
            neuer_raum = treffer
            gesetzt += 1

    neu = replace(option, slots=tuple(neue_slots), room=neuer_raum)

    gesamt = len(option.slots) or (1 if _raeume(option.room) else 0)
    bericht = [f"{option.label}: {gesetzt} von {gesamt} Terminen auf „{ziel}“ gesetzt."]
    for (wochentag, raum), anzahl in sorted(ersatz.items(), key=lambda p: p[0]):
        bericht.append(
            f"    {anzahl}× {WOCHENTAGE[wochentag]}: dort nicht im Angebot → "
            f"{raum} (gleiches Gebäude {gebaeude})."
        )
    for wochentag, anzahl in sorted(offen.items()):
        bericht.append(
            f"    {anzahl}× {WOCHENTAGE[wochentag]}: weder Wunschraum noch "
            f"Gebäude {gebaeude} im Angebot → unverändert."
        )
    return neu, bericht


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
