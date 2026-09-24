"""Tests für Semesterlogik, Katalog-Import, Konflikte und Planungsansicht."""

import json
import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.catalog import (  # noqa: E402
    RHYTHM_BIWEEKLY,
    RHYTHM_SINGLE,
    RHYTHM_WEEKLY,
    CatalogError,
    TEMPLATE_CSV,
    find_conflicts,
    load_catalog,
    load_catalog_csv,
    load_catalog_json,
    parse_date_value,
    parse_ects,
    parse_rhythm,
    parse_time,
    parse_weekday,
)
from tumcal.planner import render_planner  # noqa: E402
from tumcal.semester import WS2627, get_semester  # noqa: E402

CATALOG = Path(__file__).parent / "fixtures" / "angebot.csv"
OPTIONS = load_catalog(CATALOG)
BY_KEY = {o.key: o for o in OPTIONS}


# --- Semester ---------------------------------------------------------------

def test_lecture_period_excludes_breaks_and_holidays():
    assert WS2627.is_lecture_day(date(2026, 10, 12)) is True
    assert WS2627.is_lecture_day(date(2026, 12, 28)) is False   # Weihnachtsferien
    assert WS2627.is_lecture_day(date(2026, 11, 1)) is False    # Allerheiligen
    assert WS2627.is_lecture_day(date(2027, 2, 8)) is False     # nach Vorlesungsende


def test_lecture_days_start_on_requested_weekday():
    mondays = WS2627.lecture_days(0)
    assert all(d.weekday() == 0 for d in mondays)
    assert mondays[0] == date(2026, 10, 12)
    assert not any(date(2026, 12, 24) <= d <= date(2027, 1, 6) for d in mondays)


def test_unknown_semester_is_rejected():
    try:
        get_semester("ws9999")
    except SystemExit as exc:
        assert "Unbekanntes Semester" in str(exc)
    else:
        raise AssertionError("SystemExit erwartet")


# --- Feld-Parser ------------------------------------------------------------

def test_parse_weekday_variants():
    assert parse_weekday("Mo") == 0
    assert parse_weekday("dienstag") == 1
    assert parse_weekday("Do.") == 3
    assert parse_weekday("5") == 4
    assert parse_weekday("") is None
    assert parse_weekday("Blockveranstaltung") is None


def test_parse_time_and_date_and_ects():
    assert parse_time("10:00") == time(10, 0)
    assert parse_time("8.30 Uhr") == time(8, 30)
    assert parse_time("14") == time(14, 0)
    assert parse_time("n.V.") is None
    assert parse_date_value("01.10.2026") == date(2026, 10, 1)
    assert parse_date_value("2026-10-01") == date(2026, 10, 1)
    assert parse_date_value("irgendwann") is None
    assert parse_ects("6 ECTS") == 6.0
    assert parse_ects("2,5") == 2.5
    assert parse_ects("") == 0.0


def test_parse_rhythm():
    assert parse_rhythm("wöchentlich") == RHYTHM_WEEKLY
    assert parse_rhythm("14-tägig") == RHYTHM_BIWEEKLY
    assert parse_rhythm("Blockveranstaltung") == RHYTHM_SINGLE
    assert parse_rhythm("") == RHYTHM_WEEKLY


# --- Katalog ----------------------------------------------------------------

def test_catalog_is_loaded_with_all_rows():
    assert len(OPTIONS) == 9
    vorlesung = BY_KEY["in0001-vo"]
    assert vorlesung.kind == "VO"
    assert vorlesung.ects == 6.0
    assert vorlesung.room.startswith("5602")
    assert vorlesung.deadline == date(2026, 10, 1)


def test_weekly_option_expands_over_lecture_period():
    termine = BY_KEY["in0001-vo"].occurrences(WS2627)
    assert len(termine) == 15
    assert termine[0] == date(2026, 10, 12)
    assert all(t.weekday() == 0 for t in termine)


def test_biweekly_option_halves_the_dates():
    gruppe_a = BY_KEY["wi000123-ue-gruppe-a"]
    assert gruppe_a.rhythm == RHYTHM_BIWEEKLY
    weekly = WS2627.lecture_days(4)
    assert len(gruppe_a.occurrences(WS2627)) == len(weekly[::2])


def test_first_date_clips_the_series():
    praktikum = BY_KEY["in0002-pr"]
    assert praktikum.first_date == date(2026, 10, 9)
    assert min(praktikum.occurrences(WS2627)) >= date(2026, 10, 9)


def test_events_carry_times_and_room():
    event = BY_KEY["ma0901-vo"].events(WS2627)[0]
    assert (event.start.hour, event.start.minute) == (8, 30)
    assert event.room == "MW 0001"
    assert event.kind_label == "Vorlesung"


def test_option_without_times_yields_no_events():
    from tumcal.catalog import CourseOption

    leer = CourseOption(title="Blockseminar", kind="SE")
    assert leer.slots_known is False
    assert leer.events(WS2627) == []


def test_group_label_is_not_duplicated():
    assert BY_KEY["in0001-ue-gruppe-01"].label.endswith("· Gruppe 01")
    assert "Gruppe Gruppe" not in BY_KEY["in0001-ue-gruppe-01"].label


def test_template_is_parseable():
    assert len(load_catalog_csv(TEMPLATE_CSV)) == 3


def test_json_catalog_is_supported():
    options = load_catalog_json(
        '[{"Titel":"Statistik","Art":"VO","Tag":"Mi","Von":"09:00","Bis":"10:30"}]'
    )
    assert options[0].weekday == 2
    assert options[0].end_time == time(10, 30)


def test_missing_title_column_is_reported():
    try:
        load_catalog_csv("Spalte;Andere\n1;2\n")
    except CatalogError as exc:
        assert "Titelspalte" in str(exc)
    else:
        raise AssertionError("CatalogError erwartet")


# --- Konflikte --------------------------------------------------------------

def test_conflicts_detect_overlapping_selection():
    auswahl = [BY_KEY["in0001-vo"], BY_KEY["wi000123-vo"]]  # Mo 10-12 vs. Mo 11-13
    conflicts = find_conflicts(auswahl, WS2627)
    assert conflicts
    assert conflicts[0].start == time(11, 0)
    assert conflicts[0].end == time(12, 0)
    assert "↔" in conflicts[0].describe()


def test_no_conflict_for_disjoint_selection():
    auswahl = [BY_KEY["in0001-vo"], BY_KEY["in0001-ue-gruppe-01"]]  # Mo vs. Mi
    assert find_conflicts(auswahl, WS2627) == []


def test_touching_slots_are_not_a_conflict():
    from tumcal.catalog import CourseOption

    a = CourseOption(title="A", kind="VO", weekday=0, start_time=time(8), end_time=time(10))
    b = CourseOption(title="B", kind="VO", weekday=0, start_time=time(10), end_time=time(12))
    assert find_conflicts([a, b], WS2627) == []


# --- Planungsansicht --------------------------------------------------------

def _payload(html: str) -> dict:
    return json.loads(html.split("const DATA = ", 1)[1].split(";\n", 1)[0])


def test_planner_embeds_options_and_slots():
    data = _payload(render_planner(OPTIONS, WS2627))
    assert len(data["options"]) == 9
    assert data["semester"]["start"] == "2026-10-12"
    vorlesung = next(o for o in data["options"] if o["key"] == "in0001-vo")
    assert len(vorlesung["slots"]) == 15
    assert vorlesung["slots"][0]["startMin"] == 600


def test_planner_marks_exclusive_groups():
    data = _payload(render_planner(OPTIONS, WS2627))
    gruppen = [o for o in data["options"] if o["key"].startswith("in0001-ue")]
    assert len(gruppen) == 2
    assert gruppen[0]["exclusive"] == gruppen[1]["exclusive"] != ""
    assert next(o for o in data["options"] if o["key"] == "in0001-vo")["exclusive"] == ""


def test_planner_loads_no_external_resources():
    html = render_planner(OPTIONS, WS2627)
    assert "<script src" not in html
    assert "stylesheet" not in html


# --- Einträge ohne Termine --------------------------------------------------

def test_options_without_dates_are_listed_as_open_items():
    """Bekannt, aber noch nicht terminiert: darf nicht unsichtbar sein."""
    from tumcal.catalog import CourseOption

    offen = CourseOption(title="Logik", kind="VO", ects=5.0,
                         note="Termine noch nicht veröffentlicht")
    data = _payload(render_planner(OPTIONS + [offen], WS2627))
    assert len(data["openItems"]) == 1
    assert data["openItems"][0]["title"] == "Logik"
    assert data["openItems"][0]["ects"] == 5.0
    # und taucht nicht als regulärer Termin auf
    assert all(o["key"] != offen.key or not o["slots"] for o in data["options"])


def test_open_items_do_not_form_choice_blocks():
    """Ohne Termine lässt sich nichts kombinieren - der Eintrag bleibt trotzdem."""
    from tumcal.catalog import CourseOption, combinations

    offen = CourseOption(title="Logik", kind="UE", module="LOG", group="G1")
    fest = CourseOption(title="Vorlesung", kind="VO",
                        weekday=0, start_time=time(10), end_time=time(12))
    found, total = combinations([offen, fest], WS2627)
    assert total == 1
    assert offen in found[0].options


# --- Gespeicherte Auswahl je Plan trennen -----------------------------------

def _plan_id(html: str) -> str:
    return _payload(html)["planId"]


def test_plan_id_changes_with_the_preselection():
    """Sonst überschreibt die gespeicherte Auswahl eines früheren Kalenders
    die Vorauswahl eines neuen."""
    ohne = _plan_id(render_planner(OPTIONS, WS2627, "Plan"))
    mit = _plan_id(render_planner(OPTIONS, WS2627, "Plan", preselected=[OPTIONS[0].key]))
    andere = _plan_id(render_planner(OPTIONS, WS2627, "Plan", preselected=[OPTIONS[1].key]))
    assert len({ohne, mit, andere}) == 3


def test_plan_id_is_stable_for_identical_input():
    a = _plan_id(render_planner(OPTIONS, WS2627, "Plan", preselected=[OPTIONS[0].key]))
    b = _plan_id(render_planner(OPTIONS, WS2627, "Plan", preselected=[OPTIONS[0].key]))
    assert a == b


def test_plan_id_changes_with_the_offer():
    voll = _plan_id(render_planner(OPTIONS, WS2627, "Plan"))
    gekuerzt = _plan_id(render_planner(OPTIONS[:-1], WS2627, "Plan"))
    assert voll != gekuerzt


def test_storage_key_is_derived_from_the_plan_id():
    html = render_planner(OPTIONS, WS2627, "Plan", preselected=[OPTIONS[0].key])
    assert 'const STORE = "tumcal.auswahl." + (DATA.planId' in html


def test_reset_button_restores_the_delivered_selection():
    html = render_planner(OPTIONS, WS2627, "Plan", preselected=[OPTIONS[0].key])
    assert 'id="reset"' in html
    assert 'selected = new Set(DATA.preselected || []);' in html
    assert "localStorage.removeItem(STORE)" in html
