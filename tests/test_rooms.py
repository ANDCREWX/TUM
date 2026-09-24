"""Tests für Raumcodes, Standorte und enge Übergänge."""

import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.catalog import CourseOption, Slot  # noqa: E402
from tumcal.rooms import building, campus, transits  # noqa: E402
from tumcal.semester import WS2627  # noqa: E402

GARCHING_MW = 'MW 0001, Hörsaal (5510.EG.001)'
GARCHING_MI = '00.04.011, MI Hörsaal 2 (5604.EG.011)'
GALILEO = 'Audimax im Galileo nur Mo-Di 7-19 Uhr (8120.01.101)'
STAMM_AUDIMAX = '0980, Audimax (0509.EG.980)'


def test_building_is_extracted_from_the_room_code():
    assert building(GARCHING_MW) == "5510"
    assert building(STAMM_AUDIMAX) == "0509"
    assert building("Online: Videokonferenz") == ""


def test_campus_mapping():
    assert campus("5510") == "Garching"
    assert campus("5604") == "Garching"
    assert campus("8120") == "Garching"        # Galileo, Walther-von-Dyck-Str.
    assert campus("0509") == "Stammgelände"    # Arcisstraße
    assert campus("9999") == ""                # nicht geraten


def _lv(titel, tag, von, bis, raum):
    return CourseOption(title=titel, kind="VO", room=raum,
                        slots=(Slot(day=tag, start=von, end=bis, room=raum),))


def test_back_to_back_in_the_same_building_is_fine():
    tag = date(2026, 10, 19)
    a = _lv("A", tag, time(8), time(10), GARCHING_MW)
    b = _lv("B", tag, time(10), time(12), GARCHING_MW)
    t = transits([a, b], WS2627)[0]
    assert t.gap == 0
    assert t.verdict == "gleicher Raum"
    assert t.tight is False


def test_zero_gap_between_buildings_is_tight():
    tag = date(2026, 10, 19)
    a = _lv("A", tag, time(8), time(10), GARCHING_MW)
    b = _lv("B", tag, time(10), time(12), GARCHING_MI)
    t = transits([a, b], WS2627)[0]
    assert t.verdict == "anderes Gebäude"
    assert t.needed == 10
    assert t.tight is True


def test_cross_campus_transition_is_flagged_hardest():
    """Garching → Innenstadt ist eine U-Bahn-Fahrt, kein Fußweg."""
    tag = date(2026, 10, 23)
    a = _lv("Rechnerarchitektur", tag, time(13), time(15), 'MW 1801 (5508.02.801)')
    b = _lv("Financial Accounting", tag, time(15), time(18, 15), STAMM_AUDIMAX)
    t = transits([a, b], WS2627)[0]
    assert t.campuses == ("Garching", "Stammgelände")
    assert t.verdict == "anderer Standort"
    assert t.needed == 40
    assert t.tight is True


def test_fifteen_minutes_between_buildings_on_one_campus_is_enough():
    tag = date(2026, 10, 20)
    a = _lv("A", tag, time(10), time(12), GALILEO)
    b = _lv("B", tag, time(12, 15), time(13, 45), 'Interims I (5620.01.101)')
    t = transits([a, b], WS2627)[0]
    assert t.gap == 15 and t.needed == 10
    assert t.tight is False


def test_long_gaps_are_not_reported():
    tag = date(2026, 10, 19)
    a = _lv("A", tag, time(8), time(10), GARCHING_MW)
    b = _lv("B", tag, time(14), time(16), STAMM_AUDIMAX)
    assert transits([a, b], WS2627, max_gap=30) == []


def test_parallel_rooms_use_the_first_one():
    tag = date(2026, 10, 19)
    a = _lv("A", tag, time(8), time(10), f"{GARCHING_MW} / {GALILEO}")
    b = _lv("B", tag, time(10), time(12), GARCHING_MW)
    t = transits([a, b], WS2627)[0]
    assert t.first_room == GARCHING_MW


def test_unknown_room_is_not_guessed():
    tag = date(2026, 10, 19)
    a = _lv("A", tag, time(8), time(10), "Online: Videokonferenz")
    b = _lv("B", tag, time(10), time(12), GARCHING_MW)
    t = transits([a, b], WS2627)[0]
    assert t.verdict == "unbekannt"
    assert t.tight is False
