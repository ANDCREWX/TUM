"""Tests für die eigene Prüfungsübersicht aus TUMonline.

Anderes Format als die Prüfungsliste einer Lehrveranstaltung: "MODULPRÜFUNG"
als Kopfzeile, Datum als "07JAN 2027" in einer Zeile, Markdown-Links und
Listenpunkte drumherum.
"""

import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.exams import parse_exams  # noqa: E402

PRUEFUNGEN = parse_exams(
    (Path(__file__).parent / "fixtures" / "pruefungen-eigene.txt").read_text(
        encoding="utf-8")
)
NACH_MODUL = {p.module: p for p in PRUEFUNGEN}


def test_all_six_exams_are_recognised():
    assert len(PRUEFUNGEN) == 6
    assert sorted(NACH_MODUL) == [
        "IN0015", "IN0021", "IN2028", "IN2085", "MA0902", "WI001059EM",
    ]


def test_the_glued_date_is_read():
    """'07JAN 2027' steht in einer Zeile, nicht auf drei."""
    slot = NACH_MODUL["IN2028"].slots[0]
    assert slot.day == date(2027, 1, 7)
    assert (slot.start, slot.end) == (time(18, 30), time(20, 30))


def test_every_date_and_time():
    erwartet = {
        "IN2028": (date(2027, 1, 7), time(18, 30), time(20, 30)),
        "IN2085": (date(2027, 2, 11), time(8, 0), time(9, 30)),
        "IN0021": (date(2027, 2, 13), time(9, 0), time(10, 30)),
        "IN0015": (date(2027, 2, 15), time(17, 0), time(19, 0)),
        "MA0902": (date(2027, 2, 17), time(8, 0), time(9, 30)),
        "WI001059EM": (date(2027, 2, 23), time(8, 0), time(9, 0)),
    }
    for modul, (tag, von, bis) in erwartet.items():
        slot = NACH_MODUL[modul].slots[0]
        assert (slot.day, slot.start, slot.end) == (tag, von, bis), modul


def test_one_exam_falls_on_a_saturday():
    """Klausuren liegen auch am Wochenende - das darf nicht wegfallen."""
    assert NACH_MODUL["IN0021"].slots[0].day.weekday() == 5


def test_markdown_links_are_stripped_from_the_title():
    assert NACH_MODUL["IN2028"].title == "Business Analytics and Machine Learning"
    assert "http" not in NACH_MODUL["IN2028"].title


def test_the_semester_suffix_is_removed_but_the_rest_of_the_title_stays():
    assert NACH_MODUL["IN2085"].title == (
        "Software Engineering für betriebliche Anwendungen - Bachelorkurs")
    assert NACH_MODUL["WI001059EM"].title == (
        "Campus Munich: Financial Accounting - Bachelor")


def test_all_rooms_are_kept_not_only_the_first_three():
    assert len(NACH_MODUL["MA0902"].rooms) == 11
    assert len(NACH_MODUL["WI001059EM"].rooms) == 10
    assert len(NACH_MODUL["IN0015"].rooms) == 4
    assert len(NACH_MODUL["IN0021"].rooms) == 2
    assert NACH_MODUL["MA0902"].rooms[0] == "MW 0001, Hörsaal (5510.EG.001)"
    assert ("Hörsaal im Galileo nur Mo-Do 7-19 Uhr (8120.EG.001)"
            in NACH_MODUL["MA0902"].rooms)


def test_only_lines_with_a_room_code_count_as_rooms():
    """Um die Räume herum steht viel Beiwerk: Prüfer, Fristen, Zählerstände."""
    for pruefung in PRUEFUNGEN:
        for raum in pruefung.rooms:
            assert "(" in raum and ")" in raum
            assert not raum.startswith(("Prüfer", "Organisation", "Anmelde",
                                        "Abmeldung", "Aktuell", "Bereits"))


def test_the_examiner_is_read_from_the_same_line():
    """Hier steht 'Prüfer*in: Name' in einer Zeile, nicht auf zwei."""
    assert NACH_MODUL["IN2028"].lecturer == "Bichler, Martin"
    assert NACH_MODUL["MA0902"].lecturer == "Berger Steiger, Noam"
    assert NACH_MODUL["IN0021"].lecturer == "Rinderle-Ma, Stefanie"


def test_the_examiner_is_not_confused_with_the_organisers():
    assert "Frank" not in NACH_MODUL["IN2028"].lecturer
    assert "Gebele" not in NACH_MODUL["IN2085"].lecturer


def test_registration_period_and_withdrawal_deadline():
    pruefung = NACH_MODUL["IN2028"]
    assert pruefung.registration_start == date(2026, 11, 16)
    assert pruefung.deadline == date(2026, 12, 13)
    assert pruefung.withdraw_until == date(2026, 12, 31)

    assert NACH_MODUL["MA0902"].withdraw_until == date(2027, 2, 10)
    assert NACH_MODUL["IN0015"].deadline == date(2027, 1, 15)


def test_an_entry_without_deadlines_reports_none_instead_of_guessing():
    """Beim letzten Eintrag bricht die Kopie vor den Fristen ab."""
    pruefung = NACH_MODUL["WI001059EM"]
    assert pruefung.registration_start is None
    assert pruefung.deadline is None
    assert pruefung.withdraw_until is None


def test_a_heading_that_is_not_an_exam_creates_no_entry():
    """'Midterm-Prüfung' steht als Zwischenzeile in der Liste."""
    assert all(p.title != "Midterm-Prüfung" for p in PRUEFUNGEN)
    assert all(p.module for p in PRUEFUNGEN)


def test_every_exam_is_a_main_date_here():
    assert {p.group for p in PRUEFUNGEN} == {"Haupttermin"}
    assert {p.kind for p in PRUEFUNGEN} == {"PRUEFUNG"}


def test_the_old_lv_page_format_still_parses():
    """Die Fixture der LV-Seite darf vom neuen Format nicht gestört werden."""
    alt = parse_exams(
        (Path(__file__).parent / "fixtures" / "pruefungen.txt").read_text(
            encoding="utf-8"))
    assert alt
    assert all(p.slots for p in alt)


# --- Prüfungen als Kalendertermine -----------------------------------------

def test_the_calendar_event_names_the_number_of_halls_instead_of_one():
    """Welcher Saal es wird, steht erst kurz vor der Prüfung in TUMonline."""
    from tumcal.cli import _pruefungstermine
    termine = {e.course_code: e for e in _pruefungstermine(PRUEFUNGEN)}
    assert termine["MA0902"].location == "11 Hörsäle – Zuteilung siehe TUMonline"
    assert termine["IN0021"].location == "2 Hörsäle – Zuteilung siehe TUMonline"


def test_the_description_carries_every_hall_and_both_deadlines():
    from tumcal.cli import _pruefungstermine
    termine = {e.course_code: e for e in _pruefungstermine(PRUEFUNGEN)}
    text = termine["IN2028"].description
    assert "Prüfer*in: Bichler, Martin" in text
    assert "Anmeldung: 16.11.2026 – 13.12.2026" in text
    assert "Abmeldung bis: 31.12.2026" in text
    for raum in NACH_MODUL["IN2028"].rooms:
        assert raum in text


def test_the_event_summary_names_course_and_module():
    from tumcal.cli import _pruefungstermine
    termine = {e.course_code: e for e in _pruefungstermine(PRUEFUNGEN)}
    assert termine["IN0015"].summary == "Klausur: Diskrete Strukturen (IN0015)"


def test_the_exam_calendar_round_trips_through_the_parser():
    from tumcal.cli import _pruefungstermine
    from tumcal.ics import parse_vevents, render_calendar
    zurueck = parse_vevents(render_calendar(_pruefungstermine(PRUEFUNGEN)))
    assert len(zurueck) == 6
    assert all(e.get("DTSTART") and e.get("SUMMARY") for e in zurueck)
    uids = [e["UID"] for e in zurueck]
    assert len(set(uids)) == 6
