"""Tests für den ICS-Schreiber - inklusive Round-Trip durch den eigenen Parser."""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.ics import (  # noqa: E402
    escape_text,
    fold_line,
    parse_vevents,
    render_calendar,
)
from tumcal.model import CourseEvent  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")


def _termin(tag=20, stunde=12, minute=15, **kwargs) -> CourseEvent:
    standard = dict(
        summary="Software Engineering (Vorlesung)",
        title="Software Engineering",
        start=datetime(2026, 10, tag, stunde, minute, tzinfo=BERLIN),
        end=datetime(2026, 10, tag, stunde + 1, 45, tzinfo=BERLIN),
        location='101, Hörsaal 1, "Interims I" (5620.01.101)',
        room="5620.01.101",
        course_code="IN2085",
        kind="VO",
    )
    standard.update(kwargs)
    return CourseEvent(**standard)


# --- Bausteine --------------------------------------------------------------

def test_text_escaping_follows_rfc5545():
    assert escape_text("a,b") == r"a\,b"
    assert escape_text("a;b") == r"a\;b"
    assert escape_text("a\\b") == r"a\\b"
    assert escape_text("a\nb") == r"a\nb"
    assert escape_text("a\r\nb") == r"a\nb"
    assert escape_text("") == ""


def test_long_lines_are_folded_to_75_octets():
    zeilen = fold_line("SUMMARY:" + "x" * 200)
    assert len(zeilen[0].encode("utf-8")) == 75
    assert all(z.startswith(" ") for z in zeilen[1:])
    assert all(len(z.encode("utf-8")) <= 75 for z in zeilen)
    assert "".join([zeilen[0]] + [z[1:] for z in zeilen[1:]]) == "SUMMARY:" + "x" * 200


def test_folding_never_splits_a_multibyte_character():
    """Ein Umbruch mitten in einem UTF-8-Zeichen macht die Datei kaputt."""
    zeilen = fold_line("SUMMARY:" + "ä" * 100)
    for zeile in zeilen:
        zeile.encode("utf-8").decode("utf-8")      # würde sonst scheitern
        assert len(zeile.encode("utf-8")) <= 75
    assert "".join([zeilen[0]] + [z[1:] for z in zeilen[1:]]).endswith("ä" * 100)


def test_short_lines_are_left_alone():
    assert fold_line("VERSION:2.0") == ["VERSION:2.0"]


# --- Kalender ---------------------------------------------------------------

def test_the_calendar_has_the_required_envelope():
    text = render_calendar([_termin()], name="TUM-Stundenplan")
    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.endswith("END:VCALENDAR\r\n")
    assert "VERSION:2.0" in text
    assert "PRODID:-//tumcal//Stundenplan//DE" in text
    assert "X-WR-CALNAME:TUM-Stundenplan" in text


def test_every_line_ends_with_crlf():
    text = render_calendar([_termin()])
    assert "\n" not in text.replace("\r\n", "")


def test_winter_time_is_converted_with_the_right_offset():
    """MEZ = UTC+1: 12:15 Berlin ist 11:15 UTC."""
    winter = _termin(start=datetime(2026, 11, 10, 12, 15, tzinfo=BERLIN),
                     end=datetime(2026, 11, 10, 13, 45, tzinfo=BERLIN))
    text = render_calendar([winter])
    assert "DTSTART:20261110T111500Z" in text
    assert "DTEND:20261110T124500Z" in text


def test_summer_time_is_converted_with_the_right_offset():
    """MESZ = UTC+2. Der 20.10.2026 liegt noch davor - die Umstellung ist am 25.10."""
    text = render_calendar([_termin()])
    assert "DTSTART:20261020T101500Z" in text
    assert "DTEND:20261020T114500Z" in text

    sommer = _termin(start=datetime(2027, 6, 15, 12, 15, tzinfo=BERLIN),
                     end=datetime(2027, 6, 15, 13, 45, tzinfo=BERLIN))
    assert "DTSTART:20270615T101500Z" in render_calendar([sommer])


def test_a_naive_datetime_is_read_as_local_time():
    naiv = _termin(start=datetime(2026, 11, 10, 12, 15),
                   end=datetime(2026, 11, 10, 13, 45))
    assert "DTSTART:20261110T111500Z" in render_calendar([naiv])


def test_location_and_description_are_optional():
    text = render_calendar([_termin(location="", description="")])
    assert "LOCATION:" not in text
    assert "DESCRIPTION:" not in text


def test_a_cancelled_date_is_marked_instead_of_dropped():
    text = render_calendar([_termin(cancelled=True)])
    assert "STATUS:CANCELLED" in text


def test_events_are_sorted_by_start():
    text = render_calendar([_termin(tag=27), _termin(tag=20)])
    assert text.index("20261020") < text.index("20261027")


# --- UIDs -------------------------------------------------------------------

def test_the_uid_is_stable_when_only_the_time_changes():
    """Sonst legt eine Zeitkorrektur beim Reimport einen zweiten Termin an."""
    vorher = render_calendar([_termin(stunde=12, minute=0)])
    nachher = render_calendar([_termin(stunde=12, minute=15)])
    uid = lambda text: [z for z in text.splitlines() if z.startswith("UID:")]
    assert uid(vorher) == uid(nachher) == ["UID:in2085-vo-20261020@tumcal"]


def test_lecture_and_exercise_of_one_module_do_not_share_a_uid():
    """Beide tragen denselben Modulcode - die Art muss mit hinein."""
    vorlesung = _termin(stunde=10, kind="VO")
    uebung = _termin(stunde=14, kind="UE", summary="Übung")
    uids = [z for z in render_calendar([vorlesung, uebung]).splitlines()
            if z.startswith("UID:")]
    assert uids == ["UID:in2085-vo-20261020@tumcal", "UID:in2085-ue-20261020@tumcal"]


def test_two_dates_of_one_course_on_one_day_get_different_uids():
    text = render_calendar([_termin(stunde=10), _termin(stunde=14)])
    uids = [z for z in text.splitlines() if z.startswith("UID:")]
    assert uids == ["UID:in2085-vo-20261020@tumcal",
                    "UID:in2085-vo-20261020-1@tumcal"]


def test_an_event_without_a_course_code_falls_back_to_the_summary():
    text = render_calendar([_termin(course_code="", summary="Lerngruppe Analysis")])
    assert "UID:lerngruppe-analysis-vo-20261020@tumcal" in text


# --- Round-Trip -------------------------------------------------------------

def test_what_we_write_our_own_parser_reads_back():
    termine = [
        _termin(tag=20),
        _termin(tag=22, summary="Übung; mit Komma, und \\ Backslash",
                location="00.13.054, Seminarraum (5613.EG.054)"),
        _termin(tag=27, cancelled=True),
    ]
    zurueck = parse_vevents(render_calendar(termine, name="Probe"))
    assert len(zurueck) == 3

    # Zeiten kommen als UTC zurück und müssen dieselben Momente sein.
    for original, gelesen in zip(sorted(termine, key=lambda e: e.start), zurueck):
        assert gelesen["DTSTART"] == original.start
        assert gelesen["DTEND"] == original.end

    # Maskierung übersteht den Weg hin und zurück.
    mittlerer = zurueck[1]
    assert mittlerer["SUMMARY"] == "Übung; mit Komma, und \\ Backslash"
    assert mittlerer["LOCATION"] == "00.13.054, Seminarraum (5613.EG.054)"
    assert zurueck[2]["STATUS"] == "CANCELLED"


def test_a_folded_long_summary_survives_the_round_trip():
    lang = ("Übungen zu Software Engineering für betriebliche Anwendungen " * 3).strip()
    zurueck = parse_vevents(render_calendar([_termin(summary=lang)]))
    assert zurueck[0]["SUMMARY"] == lang


def test_an_empty_calendar_is_still_valid():
    text = render_calendar([])
    assert parse_vevents(text) == []
    assert text.startswith("BEGIN:VCALENDAR")
