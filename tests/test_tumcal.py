"""Tests für Parser, Aufbereitung und Rendering."""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.ics import parse_duration, parse_vevents, unescape, unfold  # noqa: E402
from tumcal.model import (  # noqa: E402
    clean_title,
    detect_kind,
    extract_course_code,
    extract_room,
    filter_events,
    load_events,
)
from tumcal.render import render_html, summarize  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "beispiel.ics"
ICS_TEXT = FIXTURE.read_text(encoding="utf-8")
EVENTS = load_events(ICS_TEXT)


def test_unfold_joins_continuation_lines():
    assert unfold("SUMMARY:Teil A\r\n  Teil B") == ["SUMMARY:Teil A Teil B"]


def test_unescape_handles_ics_escapes():
    assert unescape(r"Praktikum\, Gruppe\n3") == "Praktikum, Gruppe\n3"


def test_parse_duration():
    assert parse_duration("PT1H30M") == timedelta(hours=1, minutes=30)
    assert parse_duration("P1DT2H") == timedelta(days=1, hours=2)


def test_all_vevents_are_parsed():
    # 8 VEVENTs in der Fixture, VTIMEZONE wird übersprungen.
    assert len(parse_vevents(ICS_TEXT)) == 8


def test_duplicates_are_removed():
    assert len(EVENTS) == 7
    einfuehrung = [e for e in EVENTS if e.day == date(2026, 10, 19)]
    assert len(einfuehrung) == 1


def test_kind_detection():
    assert detect_kind("IN0001 VO Einführung") == "VO"
    assert detect_kind("IN0001 UE Zentralübung") == "UE"
    assert detect_kind("Klausur Einführung in die Informatik 1") == "PRUEFUNG"
    assert detect_kind("Erstsemester-Einführung") == "SONSTIGES"


def test_kind_detection_prefers_exam_over_code_letters():
    assert detect_kind("Wiederholungsklausur VO Statistik") == "PRUEFUNG"


def test_course_code_and_title_cleanup():
    assert extract_course_code("IN0001 VO Einführung") == "IN0001"
    assert clean_title("IN0001 VO Einführung in die Informatik 1", "IN0001", "VO") == (
        "Einführung in die Informatik 1"
    )


def test_room_extraction():
    assert extract_room("5602.EG.001 (MI HS 1)") == "MI HS 1"
    assert extract_room("Online") == "Online"


def test_duration_fallback_sets_end():
    klausur = next(e for e in EVENTS if e.kind == "PRUEFUNG")
    assert klausur.duration_minutes == 90


def test_all_day_event_spans_full_day():
    ganztag = next(e for e in EVENTS if "Erstsemester" in e.title)
    assert ganztag.duration_minutes == 24 * 60


def test_folded_summary_is_reassembled():
    praktikum = next(e for e in EVENTS if e.kind == "PR")
    assert "Gruppe 3" in praktikum.summary
    assert praktikum.room == "MI Rechnerhalle"


def test_cancelled_detection():
    abgesagt = [e for e in EVENTS if e.cancelled]
    assert len(abgesagt) == 1
    assert abgesagt[0].course_code == "MA0901"


def test_events_are_sorted_by_start():
    assert EVENTS == sorted(EVENTS, key=lambda e: (e.start, e.title))


def test_filter_by_kind_and_range():
    uebungen = filter_events(EVENTS, kinds=["UE"])
    assert len(uebungen) == 2
    assert all(e.kind == "UE" for e in uebungen)

    wintersemester = filter_events(EVENTS, start=date(2026, 10, 1), end=date(2026, 10, 31))
    assert all(e.day.month == 10 for e in wintersemester)
    assert not any(e.kind == "PRUEFUNG" for e in wintersemester)

    assert len(filter_events(EVENTS, include_cancelled=False)) == len(EVENTS) - 1


def test_summarize_groups_per_course():
    courses = summarize(EVENTS)
    titles = {c["title"] for c in courses}
    assert "Einführung in die Informatik 1" in titles
    praktikum = next(c for c in courses if c["kind"] == "PR")
    assert praktikum["rooms"] == ["MI Rechnerhalle"]


def test_render_html_is_self_contained_and_embeds_data():
    html = render_html(EVENTS, "Testkalender")
    assert html.startswith("<!DOCTYPE html>")
    assert "Testkalender" in html
    # Keine externen Ressourcen - die Datei muss offline funktionieren.
    assert "http://" not in html and "https://" not in html
    payload = html.split("const DATA = ", 1)[1].split(";\n", 1)[0]
    data = json.loads(payload)
    assert len(data["events"]) == len(EVENTS)
    assert data["events"][0]["week"] == "2026-10-12"


def test_render_escapes_title():
    assert "<script>alert" not in render_html(EVENTS, "<script>alert(1)</script>")


def test_all_day_flag():
    ganztag = next(e for e in EVENTS if "Erstsemester" in e.title)
    assert ganztag.all_day is True
    vorlesung = next(e for e in EVENTS if e.kind == "VO" and not e.cancelled)
    assert vorlesung.all_day is False
    assert json.loads(
        render_html(EVENTS).split("const DATA = ", 1)[1].split(";\n", 1)[0]
    )["events"][0]["allDay"] is True
