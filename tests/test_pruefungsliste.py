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


# --- Kennung und Titel in einer Zeile verklebt ------------------------------

VERKLEBT = """MODULPRÜFUNG
WI001059EMCampus Munich: Financial Accounting - Bachelor 2026 W
23
FEB 2027
08:00 - 09:00
0360, Theodor-Fischer-Hörsaal (0503.EG.360)
1200, Carl-von-Linde-Hörsaal (0502.01.200)
Prüfer*in: 
Ernstberger, Jürgen
Organisation[TUWIB30 ] Lehrstuhl für Financial Accounting
"""


def test_a_glued_module_code_and_title_are_separated():
    """Manche Kopien schreiben 'WI001059EMCampus Munich: …' in eine Zeile."""
    pruefung = parse_exams(VERKLEBT)[0]
    assert pruefung.module == "WI001059EM"
    assert pruefung.title == "Campus Munich: Financial Accounting - Bachelor"


def test_the_three_line_date_works_under_the_new_header_too():
    """Kopfzeile der eigenen Liste, Datum aber in der LV-Schreibweise."""
    pruefung = parse_exams(VERKLEBT)[0]
    assert pruefung.slots[0].day == date(2027, 2, 23)
    assert (pruefung.slots[0].start, pruefung.slots[0].end) == (
        time(8, 0), time(9, 0))


def test_the_examiner_is_also_found_on_the_following_line():
    assert parse_exams(VERKLEBT)[0].lecturer == "Ernstberger, Jürgen"


def test_a_header_without_a_readable_code_produces_no_entry():
    """Sonst erbt der Eintrag den Titel des vorherigen."""
    kaputt = VERKLEBT.replace(
        "WI001059EMCampus Munich: Financial Accounting - Bachelor 2026 W",
        "Irgendwas ohne Kennung")
    assert parse_exams(kaputt) == []


# --- Prüfungsart richtigstellen ---------------------------------------------

def test_the_exam_type_can_be_corrected():
    """TUMonline führt Midterms in derselben Liste wie Modulprüfungen."""
    from tumcal.cli import _umbenennen
    neu, berichte = _umbenennen(PRUEFUNGEN, ["IN2028=Midterm"])
    nach_modul = {p.module: p for p in neu}
    assert nach_modul["IN2028"].group == "Midterm"
    assert nach_modul["IN0015"].group == "Haupttermin"      # unberührt
    assert any("Midterm" in z for z in berichte)


def test_a_corrected_type_reaches_summary_and_description():
    from tumcal.cli import _pruefungstermine, _umbenennen
    neu, _ = _umbenennen(PRUEFUNGEN, ["IN2028=Midterm"])
    termine = {e.course_code: e for e in _pruefungstermine(neu)}
    assert termine["IN2028"].summary.startswith("Midterm: Business Analytics")
    assert termine["IN2028"].description.startswith("Midterm · IN2028")
    assert termine["IN0015"].summary.startswith("Klausur: Diskrete Strukturen")
    assert termine["IN0015"].description.startswith("Modulprüfung · IN0015")


def test_a_label_without_a_match_is_reported():
    from tumcal.cli import _umbenennen
    _, berichte = _umbenennen(PRUEFUNGEN, ["IN9999=Midterm"])
    assert any("keine Prüfung passt" in z for z in berichte)


def test_a_malformed_label_is_rejected():
    import pytest
    from tumcal.cli import _umbenennen
    for schrott in ("IN2028", "=Midterm", "IN2028="):
        with pytest.raises(SystemExit):
            _umbenennen(PRUEFUNGEN, [schrott])
