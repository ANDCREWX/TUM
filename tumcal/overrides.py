"""Eigene Korrekturen am Angebot: Uhrzeiten überschreiben, Einträge entfernen.

TUMonline ist nicht immer das, was wirklich passiert. Eine Vorlesung, die als
12:00 eingetragen ist, beginnt in der Praxis um 12:15 (cum tempore), und ein
Modul, das man doch nicht hört, soll aus dem Kalender verschwinden statt ihn
zu verstopfen. Beides sind Angaben über die eigene Realität, die in keinem
Export stehen - deshalb hier und nicht im Parser.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta

from .catalog import CourseOption, Slot, matches_selector, parse_time


@dataclass(frozen=True)
class TimeOverride:
    """Neue Uhrzeit für eine Veranstaltung: 'IN2085=12:15' oder '…=12:15-13:45'."""

    selector: str
    start: time
    end: time | None = None


def parse_time_override(value: str) -> TimeOverride:
    selector, _, zeiten = (value or "").partition("=")
    selector, zeiten = selector.strip(), zeiten.strip()
    if not selector or not zeiten:
        raise ValueError(
            "--time erwartet AUSWAHL=VON oder AUSWAHL=VON-BIS, etwa "
            f"--time \"IN2085=12:15\". Bekommen: {value!r}"
        )
    stuecke = [s for s in zeiten.replace("–", "-").split("-") if s.strip()]
    start = parse_time(stuecke[0])
    ende = parse_time(stuecke[1]) if len(stuecke) > 1 else None
    if start is None or (len(stuecke) > 1 and ende is None):
        raise ValueError(f"Uhrzeit nicht lesbar: {zeiten!r} (erwartet etwa 12:15-13:45)")
    if ende is not None and ende <= start:
        raise ValueError(f"Ende liegt nicht nach dem Beginn: {zeiten!r}")
    return TimeOverride(selector=selector, start=start, end=ende)


def parse_drop(value: str) -> str:
    selector = (value or "").strip()
    if not selector:
        raise ValueError("--drop erwartet eine Auswahl, etwa --drop \"Corporate Finance\"")
    return selector


def _verschoben(alt_start: time, alt_ende: time, neu: TimeOverride) -> tuple[time, time]:
    """Neue Uhrzeit eines Termins. Ohne Endangabe bleibt das Ende stehen."""
    if neu.end is not None:
        return neu.start, neu.end
    if alt_ende > neu.start:
        return neu.start, alt_ende
    # Der neue Beginn liegt hinter dem alten Ende: Dauer mitnehmen, sonst
    # entstünde ein Termin mit negativer Länge.
    dauer = datetime.combine(_TAG, alt_ende) - datetime.combine(_TAG, alt_start)
    ende = (datetime.combine(_TAG, neu.start) + dauer).time()
    return neu.start, ende


_TAG = datetime(2000, 1, 1).date()


def apply_time_overrides(
    options: list[CourseOption], overrides: list[TimeOverride]
) -> tuple[list[CourseOption], list[str]]:
    """Uhrzeiten der regelmäßigen Termine überschreiben.

    Geändert werden nur die Termine, die zur üblichen Uhrzeit der
    Veranstaltung liegen. Einmalig verschobene Termine bleiben, wie
    TUMonline sie meldet - sonst macht eine Korrektur für alle Wochen
    stillschweigend auch die Ausnahmen kaputt.
    """
    if not overrides:
        return options, []

    ergebnis: list[CourseOption] = []
    berichte: list[str] = []
    getroffen: Counter[TimeOverride] = Counter()
    for option in options:
        neu = next((o for o in overrides if matches_selector(option, o.selector)), None)
        if neu is None:
            ergebnis.append(option)
            continue
        getroffen[neu] += 1
        geaendert, bericht = _setze_zeit(option, neu)
        ergebnis.append(geaendert)
        berichte.extend(bericht)

    for neu in overrides:
        if not getroffen[neu]:
            berichte.append(
                f"--time {neu.selector}=…: keine Veranstaltung im Katalog passt "
                f"auf „{neu.selector}“."
            )
    return ergebnis, berichte


def _setze_zeit(
    option: CourseOption, neu: TimeOverride
) -> tuple[CourseOption, list[str]]:
    if not option.slots:
        if option.start_time is None or option.end_time is None:
            return option, [
                f"{option.label}: hat keine Uhrzeit, nichts zu überschreiben."
            ]
        von, bis = _verschoben(option.start_time, option.end_time, neu)
        bericht = [
            f"{option.label}: Serie auf {von:%H:%M}-{bis:%H:%M} gesetzt "
            f"(vorher {option.start_time:%H:%M}-{option.end_time:%H:%M})."
        ]
        return replace(option, start_time=von, end_time=bis), bericht

    ueblich = option.typical_start
    neue_slots: list[Slot] = []
    gesetzt = 0
    stehen_gelassen: Counter[time] = Counter()
    vorher = ""
    for slot in option.slots:
        if slot.start == ueblich:
            von, bis = _verschoben(slot.start, slot.end, neu)
            vorher = vorher or f"{slot.start:%H:%M}-{slot.end:%H:%M}"
            neue_slots.append(replace(slot, start=von, end=bis))
            gesetzt += 1
        else:
            stehen_gelassen[slot.start] += 1
            neue_slots.append(slot)

    erster = next((s for s in neue_slots if s.start == neu.start), None)
    bericht = [
        f"{option.label}: {gesetzt} Termine auf "
        f"{erster.start:%H:%M}-{erster.end:%H:%M} gesetzt (vorher {vorher})."
        if erster else f"{option.label}: nichts geändert."
    ]
    for abweichend, anzahl in sorted(stehen_gelassen.items()):
        bericht.append(
            f"    {anzahl}× {abweichend:%H:%M}: abweichende Uhrzeit, "
            f"unverändert gelassen."
        )
    return replace(option, slots=tuple(neue_slots)), bericht


def drop_options(
    options: list[CourseOption], selectors: list[str]
) -> tuple[list[CourseOption], list[str]]:
    """Einträge aus dem Angebot nehmen."""
    if not selectors:
        return options, []

    behalten: list[CourseOption] = []
    entfernt: dict[str, list[str]] = {s: [] for s in selectors}
    for option in options:
        treffer = next((s for s in selectors if matches_selector(option, s)), None)
        if treffer is None:
            behalten.append(option)
        else:
            entfernt[treffer].append(option.label)

    berichte: list[str] = []
    for selector, labels in entfernt.items():
        if not labels:
            berichte.append(
                f"--drop {selector}: keine Veranstaltung im Katalog passt "
                f"auf „{selector}“."
            )
            continue
        wort = "Eintrag" if len(labels) == 1 else "Einträge"
        berichte.append(f"--drop {selector}: {len(labels)} {wort} entfernt.")
        for label in labels:
            berichte.append(f"    · {label}")
    return behalten, berichte
