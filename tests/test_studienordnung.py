"""Tests für Prüfungstermine und den Abgleich mit der Studienordnung."""

import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.catalog import CourseOption, find_conflicts  # noqa: E402
from tumcal.curriculum import check_plan, load_curriculum  # noqa: E402
from tumcal.exams import parse_exams  # noqa: E402
from tumcal.semester import WS2627  # noqa: E402

EXAMS = parse_exams((Path(__file__).parent / "fixtures" / "pruefungen.txt")
                    .read_text(encoding="utf-8"))
CURRICULUM = load_curriculum()


# --- Prüfungstermine --------------------------------------------------------

def test_all_exam_dates_are_found():
    assert len(EXAMS) == 3
    assert all(e.kind == "PRUEFUNG" for e in EXAMS)


def test_date_is_assembled_from_three_lines():
    """'15' / 'FEB 2027' / '17:00 - 19:00' stehen in TUMonline untereinander."""
    ds = next(e for e in EXAMS if e.module == "IN0015" and e.group == "Haupttermin")
    slot = ds.slots[0]
    assert slot.day == date(2027, 2, 15)
    assert (slot.start, slot.end) == (time(17), time(19))


def test_retake_is_marked_as_such():
    ds = [e for e in EXAMS if e.module == "IN0015"]
    assert [e.group for e in ds] == ["Haupttermin", "Wiederholung"]
    assert ds[1].slots[0].day == date(2027, 4, 2)


def test_registration_window_and_withdrawal():
    ds = next(e for e in EXAMS if e.module == "IN0015" and e.group == "Haupttermin")
    assert ds.registration_start == date(2026, 11, 16)
    assert ds.deadline == date(2027, 1, 15)
    assert ds.withdraw_until == date(2027, 2, 8)


def test_examiner_and_rooms():
    ds = next(e for e in EXAMS if e.module == "IN0015" and e.group == "Haupttermin")
    assert ds.lecturer == "Brandt, Felix"
    assert "MW 2001" in ds.room
    economics = next(e for e in EXAMS if e.module == "WI000021EM")
    assert economics.note == "9 Räume"
    assert economics.ects == 6.0


def test_two_exams_on_one_day_do_not_overlap():
    """15.02.2027: Economics 08:00, Diskrete Strukturen 17:00."""
    gleicher_tag = [e for e in EXAMS if e.slots[0].day == date(2027, 2, 15)]
    assert len(gleicher_tag) == 2
    assert find_conflicts(gleicher_tag, WS2627) == []


def test_exam_option_carries_no_exclusive_key_for_main_date():
    """Haupt- und Wiederholungstermin sind keine Wahlalternativen."""
    ds = [e for e in EXAMS if e.module == "IN0015"]
    assert ds[0].exclusive_key == ds[1].exclusive_key  # gleiche Gruppe im Sinne des Moduls
    assert ds[0].kind == "PRUEFUNG"


# --- Studienordnung ---------------------------------------------------------

def test_curriculum_loads_all_compulsory_modules():
    assert len(CURRICULUM) == 22
    assert sum(m.ects for m in CURRICULUM) == 150.0


def test_first_semester_has_31_credits():
    erstes = [m for m in CURRICULUM if m.semester == 1]
    assert sum(m.ects for m in erstes) == 31.0
    assert {m.code for m in erstes} == {"CIT123001", "IN0021", "IN0015", "WI001059_E"}


def test_foundation_exams_are_exactly_the_three_starred_modules():
    """FPSO Anlage 1: nur CIT123001, IN0015 und IN0021 sind Grundlagenprüfungen."""
    grundlagen = {m.code for m in CURRICULUM if m.foundation}
    assert grundlagen == {"CIT123001", "IN0015", "IN0021"}
    assert sum(m.ects for m in CURRICULUM if m.foundation) == 25.0


def test_check_plan_reports_missing_compulsory_module():
    plan = [
        CourseOption(title="Diskrete Strukturen", kind="VO", module="IN0015"),
        CourseOption(title="Einführung WI", kind="VO", module="IN0021"),
        CourseOption(title="Financial Accounting", kind="VI", module="WI001059_E"),
    ]
    ergebnis = check_plan(plan, CURRICULUM, semester=1)
    assert [m.code for m in ergebnis.missing] == ["CIT123001"]
    assert ergebnis.missing_credits == 12.0
    assert ergebnis.planned_credits == 19.0


def test_check_plan_flags_modules_outside_the_curriculum():
    plan = [CourseOption(title="Economics I", kind="VO", module="WI000021_E")]
    ergebnis = check_plan(plan, CURRICULUM, semester=1)
    assert any("WI000021_E" in eintrag for eintrag in ergebnis.unlisted)


def test_module_code_suffix_is_ignored_when_matching():
    """WI001059 und WI001059_E sind dasselbe Modul."""
    plan = [CourseOption(title="Financial Accounting", kind="VI", module="WI001059")]
    ergebnis = check_plan(plan, CURRICULUM, semester=1)
    assert "WI001059_E" in {m.code for m in ergebnis.planned}
    assert ergebnis.unlisted == []


def test_foundation_credits_in_plan_are_counted():
    plan = [
        CourseOption(title="Diskrete Strukturen", kind="VO", module="IN0015"),
        CourseOption(title="Einführung WI", kind="VO", module="IN0021"),
    ]
    ergebnis = check_plan(plan, CURRICULUM, semester=1)
    assert ergebnis.foundation_planned == 13.0   # 8 + 5, ohne CIT123001
    assert ergebnis.foundation_total == 25.0
