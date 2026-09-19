"""Tests für den Parser der aus TUMonline kopierten LV-Listen."""

import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.catalog import find_conflicts, load_catalog, looks_like_paste  # noqa: E402
from tumcal.paste import parse_paste, to_json_catalog  # noqa: E402
from tumcal.semester import WS2627  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "tumonline-paste.txt"
TEXT = FIXTURE.read_text(encoding="utf-8")
OPTIONS = parse_paste(TEXT)
BY_KEY = {o.key: o for o in OPTIONS}


def test_paste_is_detected_as_such():
    assert looks_like_paste(TEXT) is True
    assert looks_like_paste("Titel;Art\nMathe;VO\n") is False


def test_all_courses_and_groups_are_found():
    assert len(OPTIONS) == 5
    titles = [o.title for o in OPTIONS]
    assert titles.count("Economics I") == 2          # zwei Gruppen
    assert "Diskrete Strukturen" in titles
    assert "Einführung in die Wirtschaftsinformatik" in titles
    assert "Financial Accounting" in titles


def test_header_yields_id_module_and_kind():
    ds = next(o for o in OPTIONS if o.title == "Diskrete Strukturen")
    assert ds.lv_id == "0240967009"
    assert ds.module == "IN0015"
    assert ds.kind == "VO"

    fa = next(o for o in OPTIONS if o.title == "Financial Accounting")
    assert fa.kind == "VI"
    assert fa.module == "WI001059_E"


def test_title_is_stripped_of_code_and_language_suffix():
    economics = [o for o in OPTIONS if o.title == "Economics I"]
    assert economics, "Titel darf weder '(englisch)' noch '- Lecture' enthalten"
    assert all("englisch" not in o.title and "Lecture" not in o.title for o in OPTIONS)


def test_groups_are_kept_apart():
    gruppen = sorted(o.group for o in OPTIONS if o.title == "Economics I")
    assert gruppen == ["Gruppe 1", "Gruppe 2"]
    assert all(o.group == "" for o in OPTIONS if o.title == "Diskrete Strukturen")


def test_parallel_rooms_are_merged_into_one_slot():
    """TUMonline listet Hörsaal und Übertragungsraum getrennt - ein Termin."""
    ds = next(o for o in OPTIONS if o.title == "Diskrete Strukturen")
    assert len(ds.slots) == 2                       # 4 Zeilen, 2 echte Termine
    first = ds.slots[0]
    assert first.day == date(2026, 10, 13)
    assert "Interims I" in first.room and "MW 2001" in first.room


def test_times_and_dates_are_exact():
    wi = next(o for o in OPTIONS if o.title.startswith("Einführung"))
    assert wi.slots[0].day == date(2026, 10, 13)
    assert wi.slots[0].start == time(12, 15)
    assert wi.slots[0].end == time(13, 45)


def test_irregular_single_date_is_preserved():
    """Gruppe 2 weicht am 02.12. auf Zeit und Raum der Gruppe 1 aus."""
    gruppe2 = next(o for o in OPTIONS if o.group == "Gruppe 2")
    abweichend = [s for s in gruppe2.slots if s.day == date(2026, 12, 2)]
    assert len(abweichend) == 1
    assert abweichend[0].start == time(9, 45)
    assert "Meinke" in abweichend[0].room


def test_lecturers_are_collected_without_ambiguity():
    ds = next(o for o in OPTIONS if o.title == "Diskrete Strukturen")
    assert "Becker, Patrick" in ds.lecturer
    assert ds.lecturer.count(";") >= 1              # Namen enthalten selbst Kommata
    economics = next(o for o in OPTIONS if o.group == "Gruppe 1")
    assert economics.lecturer == ""                 # "-" ist kein Name


def test_participant_count_is_kept_as_note():
    ds = next(o for o in OPTIONS if o.title == "Diskrete Strukturen")
    assert ds.note == "163 Teilnehmende"


def test_ui_noise_does_not_become_a_course():
    for option in OPTIONS:
        assert "weniger anzeigen" not in option.title.lower()
        assert "nächster termin" not in option.title.lower()
        assert "präferenz" not in option.title.lower()


def test_explicit_slots_win_over_weekday_expansion():
    ds = next(o for o in OPTIONS if o.title == "Diskrete Strukturen")
    assert ds.weekday is None                       # keine Regel hinterlegt
    assert len(ds.events(WS2627)) == len(ds.slots)  # trotzdem Termine


def test_json_roundtrip_keeps_slots(tmp_path):
    import json

    path = tmp_path / "angebot.json"
    path.write_text(json.dumps(to_json_catalog(OPTIONS), ensure_ascii=False), encoding="utf-8")
    again = load_catalog(path)
    assert len(again) == len(OPTIONS)
    assert sum(len(o.slots) for o in again) == sum(len(o.slots) for o in OPTIONS)
    ds = next(o for o in again if o.title == "Diskrete Strukturen")
    assert "Interims I" in ds.slots[0].room


def test_the_two_economics_groups_collide_only_on_the_shifted_date():
    gruppe1 = next(o for o in OPTIONS if o.group == "Gruppe 1")
    gruppe2 = next(o for o in OPTIONS if o.group == "Gruppe 2")
    conflicts = find_conflicts([gruppe1, gruppe2], WS2627)
    assert [c.day for c in conflicts] == [date(2026, 12, 2)]


def test_either_economics_group_fits_the_rest_of_the_schedule():
    andere = [o for o in OPTIONS if o.title != "Economics I"]
    for gruppe in (o for o in OPTIONS if o.title == "Economics I"):
        assert find_conflicts(andere + [gruppe], WS2627) == []
