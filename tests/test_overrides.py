"""Tests für eigene Korrekturen: Uhrzeiten überschreiben, Einträge entfernen."""

import sys
from datetime import date, time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.catalog import CourseOption, Slot, matches_selector  # noqa: E402
from tumcal.overrides import (  # noqa: E402
    apply_time_overrides,
    drop_options,
    parse_drop,
    parse_time_override,
)
from tumcal.semester import WS2627  # noqa: E402

RAUM = '101, Hörsaal 1, "Interims I" (5620.01.101)'


def _vorlesung(**kwargs) -> CourseOption:
    """Software Engineering: Do 12:00-14:00, ein Termin einmalig verschoben."""
    standard = dict(
        title="Software Engineering für betriebliche Anwendungen",
        lv_id="240947404",
        kind="VO",
        module="IN2085",
        slots=(
            Slot(date(2026, 10, 15), time(12, 0), time(14, 0), RAUM),
            Slot(date(2026, 10, 22), time(12, 0), time(14, 0), RAUM),
            Slot(date(2026, 10, 29), time(12, 0), time(14, 0), RAUM),
            Slot(date(2026, 11, 5), time(16, 0), time(18, 0), RAUM),  # Ausnahme
        ),
    )
    standard.update(kwargs)
    return CourseOption(**standard)


def _serie() -> CourseOption:
    return CourseOption(
        title="Business Analytics and Machine Learning", module="IN2028", kind="UE",
        weekday=0, start_time=time(14, 0), end_time=time(16, 0), room=RAUM,
    )


# --- Selektor ---------------------------------------------------------------

def test_selector_matches_module_number_and_title():
    option = _vorlesung()
    assert matches_selector(option, "IN2085")
    assert matches_selector(option, "240947404")
    assert matches_selector(option, "Software Engineering")
    assert matches_selector(option, "software engineering")   # Groß/klein egal
    assert not matches_selector(option, "IN0015")
    assert not matches_selector(option, "")


# --- Uhrzeit überschreiben --------------------------------------------------

def test_time_override_is_parsed_with_and_without_end():
    nur_start = parse_time_override("IN2085=12:15")
    assert nur_start.selector == "IN2085"
    assert nur_start.start == time(12, 15)
    assert nur_start.end is None

    beides = parse_time_override("IN2085=12:15-13:45")
    assert beides.start == time(12, 15)
    assert beides.end == time(13, 45)


def test_a_malformed_time_override_is_rejected():
    for schrott in ("IN2085", "=12:15", "IN2085=", "IN2085=morgens",
                    "IN2085=13:45-12:15"):
        with pytest.raises(ValueError):
            parse_time_override(schrott)


def test_only_the_start_moves_when_no_end_is_given():
    options, _ = apply_time_overrides([_vorlesung()],
                                      [parse_time_override("IN2085=12:15")])
    slots = options[0].slots
    assert (slots[0].start, slots[0].end) == (time(12, 15), time(14, 0))


def test_both_times_are_set_when_given():
    options, _ = apply_time_overrides([_vorlesung()],
                                      [parse_time_override("IN2085=12:15-13:45")])
    slots = options[0].slots
    assert (slots[0].start, slots[0].end) == (time(12, 15), time(13, 45))


def test_a_one_off_shifted_date_is_left_alone():
    """Eine Korrektur für alle Wochen darf die Ausnahme nicht mitnehmen."""
    options, report = apply_time_overrides([_vorlesung()],
                                           [parse_time_override("IN2085=12:15")])
    assert (options[0].slots[3].start, options[0].slots[3].end) == (
        time(16, 0), time(18, 0))
    assert any("abweichende Uhrzeit" in zeile for zeile in report)


def test_the_report_names_old_and_new_time():
    _, report = apply_time_overrides([_vorlesung()],
                                     [parse_time_override("IN2085=12:15")])
    assert "3 Termine auf 12:15-14:00 gesetzt" in report[0]
    assert "vorher 12:00-14:00" in report[0]


def test_a_series_without_single_dates_is_shifted_too():
    options, report = apply_time_overrides([_serie()],
                                           [parse_time_override("IN2028=14:15")])
    assert options[0].start_time == time(14, 15)
    assert options[0].end_time == time(16, 0)
    assert "Serie auf 14:15-16:00" in report[0]
    assert len(options[0].events(WS2627)) == len(_serie().events(WS2627))


def test_a_start_after_the_old_end_keeps_the_duration():
    """Sonst entstünde ein Termin, der vor seinem Beginn endet."""
    options, _ = apply_time_overrides([_serie()],
                                      [parse_time_override("IN2028=18:00")])
    assert (options[0].start_time, options[0].end_time) == (time(18, 0), time(20, 0))


def test_other_courses_are_untouched():
    andere = CourseOption(title="Analysis für Informatik", module="MA0902", kind="VO",
                          weekday=1, start_time=time(8, 30), end_time=time(10, 0))
    options, _ = apply_time_overrides([andere],
                                      [parse_time_override("IN2085=12:15")])
    assert options[0].start_time == time(8, 30)


def test_a_selector_that_matches_nothing_is_reported():
    _, report = apply_time_overrides([_vorlesung()],
                                     [parse_time_override("IN9999=12:15")])
    assert "keine Veranstaltung" in report[0]


# --- Einträge entfernen -----------------------------------------------------

def test_drop_selector_is_parsed():
    assert parse_drop("  Corporate Finance ") == "Corporate Finance"
    with pytest.raises(ValueError):
        parse_drop("   ")


def test_dropping_removes_every_matching_entry():
    cf_vo = CourseOption(title="Corporate Finance", module="WI000123", kind="VO")
    cf_ue = CourseOption(title="Corporate Finance", module="WI000123", kind="UE",
                         group="Gruppe 1")
    behalten = _vorlesung()
    options, report = drop_options([cf_vo, behalten, cf_ue], ["Corporate Finance"])
    assert [o.title for o in options] == [behalten.title]
    assert "2 Einträge entfernt" in report[0]
    assert any("Corporate Finance (Vorlesung)" in z for z in report)


def test_dropping_only_the_lecture_is_possible():
    cf_vo = CourseOption(title="Corporate Finance", module="WI000123", kind="VO")
    cf_ue = CourseOption(title="Corporate Finance", module="WI000123", kind="UE",
                         group="Gruppe 1")
    options, _ = drop_options([cf_vo, cf_ue], ["Corporate Finance (Vorlesung)"])
    assert [o.kind for o in options] == ["UE"]


def test_dropping_nothing_is_reported_instead_of_silently_passing():
    _, report = drop_options([_vorlesung()], ["Corporate Finance"])
    assert "keine Veranstaltung" in report[0]


def test_dropping_without_selectors_changes_nothing():
    optionen = [_vorlesung(), _serie()]
    options, report = drop_options(optionen, [])
    assert options == optionen
    assert report == []
