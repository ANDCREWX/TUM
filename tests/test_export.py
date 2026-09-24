"""Tests für den TUMonline-Terminexport (CSV)."""

import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.catalog import find_conflicts, load_catalog  # noqa: E402
from tumcal.export import _decode, load_export, looks_like_export, parse_export  # noqa: E402
from tumcal.semester import WS2627  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "export.csv"
OPTIONS = load_export(FIXTURE)
BY_TITLE = {o.title: o for o in OPTIONS}


def test_windows_encoding_is_decoded():
    """TUMonline liefert cp1252, nicht UTF-8."""
    text = _decode(FIXTURE)
    assert "Hörsaal" in text
    assert "Automaten und formale Sprachen" in text


def test_export_format_is_recognised():
    assert looks_like_export(_decode(FIXTURE)) is True
    assert looks_like_export("Titel;Art\nMathe;VO") is False
    assert load_catalog(FIXTURE)          # Erkennung greift auch über load_catalog


def test_rows_are_grouped_into_courses():
    assert len(OPTIONS) == 4
    assert set(BY_TITLE) == {
        "Diskrete Strukturen", "Automaten und formale Sprachen",
        "Netzsicherheit", "Der Staat als Hacker",
    }


def test_module_code_from_round_and_square_brackets():
    assert BY_TITLE["Diskrete Strukturen"].module == "IN0015"
    assert BY_TITLE["Der Staat als Hacker"].module == "SOT82533"


def test_parallel_rooms_collapse_into_one_slot():
    """Hörsaal und Übertragungsraum sind ein Termin, nicht zwei."""
    ds = BY_TITLE["Diskrete Strukturen"]
    assert len(ds.slots) == 8            # 4 Di + 4 Do, nicht 12
    dienstag = [s for s in ds.slots if s.day.weekday() == 1]
    assert "Hörsaal 1" in dienstag[0].room and "MW 2001" in dienstag[0].room


def test_two_weekly_patterns_are_both_reported():
    ds = BY_TITLE["Diskrete Strukturen"]
    muster = ds.weekly_patterns(min_count=2)
    assert len(muster) == 2
    assert {(m[0], m[1]) for m in muster} == {(1, time(14, 15)), (3, time(10, 15))}


def test_earliest_regular_start_uses_the_earliest_track():
    """Automaten läuft Mi 08:00 und Di 10:30 - maßgeblich ist 08:00."""
    automaten = BY_TITLE["Automaten und formale Sprachen"]
    assert automaten.earliest_regular_start == time(8)
    assert automaten.typical_start in (time(8), time(10, 30))


def test_collision_against_core_module_is_found():
    ds = BY_TITLE["Diskrete Strukturen"]
    netz = BY_TITLE["Netzsicherheit"]           # Di 14:00-16:00 vs. Di 14:15-15:45
    assert find_conflicts([ds, netz], WS2627)


def test_non_colliding_module_stays():
    ds = BY_TITLE["Diskrete Strukturen"]
    seminar = BY_TITLE["Der Staat als Hacker"]  # Mi 16:00-18:00
    assert find_conflicts([ds, seminar], WS2627) == []


def test_lecturer_and_group_are_read():
    ds = BY_TITLE["Diskrete Strukturen"]
    assert ds.group == ""                       # "Standardgruppe" ist keine Gruppe
    assert ds.lv_id == "0240967009"


def test_empty_input_yields_nothing():
    assert parse_export('"DATUM";"VON";"BIS";"TITEL"\r\n') == []


# --- Größte überschneidungsfreie Auswahl ------------------------------------

def test_max_compatible_drops_candidates_colliding_with_the_core():
    from tumcal.catalog import max_compatible

    kern = [BY_TITLE["Diskrete Strukturen"]]
    kandidaten = [BY_TITLE["Netzsicherheit"], BY_TITLE["Der Staat als Hacker"]]
    verworfen, loesungen = max_compatible(kandidaten, WS2627, fixed=kern)
    assert [o.title for o in verworfen] == ["Netzsicherheit"]
    assert [o.title for o in loesungen[0]] == ["Der Staat als Hacker"]


def test_max_compatible_finds_the_largest_set():
    from tumcal.catalog import max_compatible

    _, loesungen = max_compatible(list(OPTIONS), WS2627)
    # Diskrete Strukturen (Di 14:15) und Netzsicherheit (Di 14:00) kollidieren,
    # Automaten und "Der Staat als Hacker" passen zu beidem.
    assert len(loesungen[0]) == 3
    for lsg in loesungen:
        titel = {o.title for o in lsg}
        assert not {"Diskrete Strukturen", "Netzsicherheit"} <= titel


def test_groups_of_one_course_never_appear_together():
    """Zwei Gruppen derselben LV sind Alternativen, nicht zwei Module."""
    from tumcal.catalog import CourseOption, Slot, max_compatible

    gruppe_a = CourseOption(title="Übung", kind="UE", module="IN2003", group="G1",
                            slots=(Slot(day=date(2026, 10, 19), start=time(8), end=time(10)),))
    gruppe_b = CourseOption(title="Übung", kind="UE", module="IN2003", group="G2",
                            slots=(Slot(day=date(2026, 10, 20), start=time(8), end=time(10)),))
    _, loesungen = max_compatible([gruppe_a, gruppe_b], WS2627)
    assert len(loesungen[0]) == 1            # trotz freier Termine nur eine
    assert len(loesungen) == 2               # beide Gruppen sind gleichwertig


def test_options_without_dates_are_ignored():
    from tumcal.catalog import CourseOption, max_compatible

    offen = CourseOption(title="Logik", kind="VO")
    _, loesungen = max_compatible([offen, BY_TITLE["Der Staat als Hacker"]], WS2627)
    assert [o.title for o in loesungen[0]] == ["Der Staat als Hacker"]
