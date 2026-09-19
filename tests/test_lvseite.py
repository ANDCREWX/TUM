"""Tests für einzelne LV-Seiten und die Semesterprüfung."""

import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.catalog import load_catalog, looks_like_paste, out_of_semester  # noqa: E402
from tumcal.paste import parse_lv_page  # noqa: E402
from tumcal.semester import SS27, WS2627  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "lv-seite.txt"
TEXT = FIXTURE.read_text(encoding="utf-8")
OPTIONS = parse_lv_page(TEXT)


def test_lv_page_is_recognised_without_termin_lines():
    """Diese Seite listet keine Einzeltermine, nur eine Serie."""
    assert "Termin  " not in TEXT
    assert looks_like_paste(TEXT) is True
    assert load_catalog(FIXTURE)


def test_series_line_becomes_a_weekday_rule():
    """'Montag , 10:00 - 12:00 von 13.04.2026 bis 13.07.2026'."""
    assert len(OPTIONS) == 1
    option = OPTIONS[0]
    assert option.weekday == 0
    assert option.start_time == time(10)
    assert option.end_time == time(12)
    assert option.first_date == date(2026, 4, 13)
    assert option.last_date == date(2026, 7, 13)


def test_kind_comes_from_the_art_field():
    assert OPTIONS[0].kind == "VO"


def test_module_code_is_taken_from_the_curriculum_link():
    assert OPTIONS[0].module == "ED0141"
    assert OPTIONS[0].lv_id == "0000001183"


def test_offered_semester_and_language_are_kept_as_note():
    assert "Sommersemester 2026" in OPTIONS[0].note
    assert "Englisch" in OPTIONS[0].note


def test_series_from_another_semester_yields_no_dates():
    assert OPTIONS[0].occurrences(WS2627) == []
    assert OPTIONS[0].occurrences(SS27) == []


def test_out_of_semester_flags_the_entry():
    """Ohne Warnung verschwände der Eintrag unbemerkt aus dem Kalender."""
    fremd = out_of_semester(OPTIONS, WS2627)
    assert len(fremd) == 1
    option, zeitraum = fremd[0]
    assert option.module == "ED0141"
    assert zeitraum == "13.04.2026–13.07.2026"


def test_entries_inside_the_semester_are_not_flagged():
    from tumcal.catalog import CourseOption, Slot

    drin = CourseOption(
        title="Passt", kind="VO",
        slots=(Slot(day=date(2026, 10, 19), start=time(10), end=time(12)),),
    )
    assert out_of_semester([drin], WS2627) == []


def test_plain_weekday_rule_is_never_flagged():
    """Ohne Datumsgrenzen gilt eine Wochentagsregel im gewählten Semester."""
    from tumcal.catalog import CourseOption

    regel = CourseOption(title="Regel", kind="VO", weekday=1,
                         start_time=time(10), end_time=time(12))
    assert out_of_semester([regel], WS2627) == []


def test_option_without_dates_is_not_flagged():
    from tumcal.catalog import CourseOption

    offen = CourseOption(title="Logik", kind="VO")
    assert out_of_semester([offen], WS2627) == []
