"""Tests für Modulbeschreibungen: ECTS, Pflicht-LVs, Lückenprüfung."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.catalog import CourseOption, load_catalog  # noqa: E402
from tumcal.model import detect_kind  # noqa: E402
from tumcal.module import (  # noqa: E402
    apply_ects,
    ects_total,
    missing_lectures,
    parse_modules,
)

MODULE = parse_modules((Path(__file__).parent / "fixtures" / "module.txt")
                       .read_text(encoding="utf-8"))
BY_CODE = {m.code: m for m in MODULE}


def test_all_modules_are_parsed():
    assert len(MODULE) == 4
    assert set(BY_CODE) == {"WI000021_E", "IN0015", "IN0021", "WI001059_E"}


def test_module_fields():
    ds = BY_CODE["IN0015"]
    assert ds.name == "Diskrete Strukturen"
    assert ds.ects == 8.0
    assert ds.language == "Deutsch"
    assert ds.level == "Bachelor"
    assert ds.presence_hours == 90
    assert ds.total_hours == 240
    assert ds.responsible.startswith("Esparza")


def test_ects_strips_the_trailing_disclaimer():
    """'6 Credits können je nach SPO-Version variieren' -> 6."""
    assert BY_CODE["WI000021_E"].ects == 6.0
    assert BY_CODE["IN0021"].ects == 5.0
    assert sum(m.ects for m in MODULE) == 25.0


def test_lectures_are_listed_without_semester_markers():
    wi = BY_CODE["IN0021"]
    assert wi.lectures == (
        "Einführung in die Wirtschaftsinformatik (IN0021)",
        "Tutorübungen zu Einführung in die Wirtschaftsinformatik (IN0021)",
    )
    assert all(z not in wi.lectures for z in ("1.", "-", "SEMESTER"))


def test_exams_are_separated_from_lectures():
    fa = BY_CODE["WI001059_E"]
    assert fa.lectures == ("Financial Accounting (Bachelor)",)
    assert fa.exams == ("Financial Accounting (Prüfung auf englisch)",)


def test_expected_kinds_are_inferred_from_names():
    kinds = dict(BY_CODE["WI000021_E"].expected)
    assert kinds["Economics I - Lecture"] == "VO"
    assert kinds["Economics I Exercise - English"] == "UE"
    # Ein Name ohne Hinweis ist die Hauptveranstaltung.
    assert dict(BY_CODE["IN0015"].expected)["Diskrete Strukturen (IN0015)"] == "VO"


def test_english_terms_are_recognised():
    assert detect_kind("Economics I Exercise - English") == "UE"
    assert detect_kind("Advanced Topics - Lecture") == "VO"


# --- Abgleich mit dem Katalog -----------------------------------------------

CATALOG = load_catalog(Path(__file__).parent / "fixtures" / "angebot.csv")


def test_missing_lecture_is_reported():
    """Der Katalog kennt zu IN0021 nur die Vorlesung, nicht die Tutorübung."""
    options = [
        CourseOption(title="Einführung in die Wirtschaftsinformatik", kind="VO", module="IN0021"),
    ]
    fehlend = missing_lectures(options, [BY_CODE["IN0021"]])
    assert len(fehlend) == 1
    assert fehlend[0][2] == "UE"
    assert "Tutorübungen" in fehlend[0][1]


def test_nothing_missing_when_both_kinds_are_present():
    options = [
        CourseOption(title="Einführung", kind="VO", module="IN0021"),
        CourseOption(title="Tutorübung", kind="UE", module="IN0021", group="G1"),
    ]
    assert missing_lectures(options, [BY_CODE["IN0021"]]) == []


def test_integrated_exercise_covers_the_lecture_requirement():
    """Financial Accounting ist eine VI - Übung steckt in der Vorlesung."""
    options = [CourseOption(title="Financial Accounting", kind="VI", module="WI001059_E")]
    assert missing_lectures(options, [BY_CODE["WI001059_E"]]) == []


# --- ECTS -------------------------------------------------------------------

def test_ects_are_attached_to_every_entry_of_the_module():
    options = [
        CourseOption(title="Einführung", kind="VO", module="IN0021"),
        CourseOption(title="Tutorübung", kind="UE", module="IN0021", group="G1"),
    ]
    mit = apply_ects(options, MODULE)
    assert [o.ects for o in mit] == [5.0, 5.0]


def test_ects_total_counts_each_module_once():
    """Vorlesung und Übung desselben Moduls dürfen nicht doppelt zählen."""
    options = apply_ects([
        CourseOption(title="Einführung", kind="VO", module="IN0021"),
        CourseOption(title="Tutorübung", kind="UE", module="IN0021", group="G1"),
        CourseOption(title="Diskrete Strukturen", kind="VO", module="IN0015"),
    ], MODULE)
    assert ects_total(options) == 13.0


def test_ects_are_independent_of_the_chosen_group():
    gruppe1 = apply_ects([CourseOption(title="Economics I", kind="VO",
                                       module="WI000021_E", group="Gruppe 1")], MODULE)
    gruppe2 = apply_ects([CourseOption(title="Economics I", kind="VO",
                                       module="WI000021_E", group="Gruppe 2")], MODULE)
    assert ects_total(gruppe1) == ects_total(gruppe2) == 6.0


def test_unknown_module_keeps_its_ects_untouched():
    fremd = CourseOption(title="Irgendwas", kind="VO", module="XX9999", ects=3.0)
    assert apply_ects([fremd], MODULE)[0].ects == 3.0
