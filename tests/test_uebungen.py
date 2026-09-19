"""Tests für Übungsgruppen: englische Labels, Gruppencodes, Querverweise, Kombinationen."""

import sys
from datetime import date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tumcal.catalog import CourseOption, Slot, combinations, find_conflicts  # noqa: E402
from tumcal.paste import parse_paste  # noqa: E402
from tumcal.semester import WS2627  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "tumonline-uebungen.txt"
OPTIONS = parse_paste(FIXTURE.read_text(encoding="utf-8"))


# --- Parser -----------------------------------------------------------------

def test_english_group_labels_are_recognised():
    economics = [o for o in OPTIONS if o.title == "Economics I"]
    assert sorted(o.group for o in economics) == ["Group 1", "Group 5"]


def test_group_codes_without_label_are_recognised():
    """Übungsgruppen heißen in TUMonline oft nur '01-08xx-03.09.014'."""
    ds = [o for o in OPTIONS if o.title.startswith("Übungen")]
    assert sorted(o.group for o in ds) == ["01-08xx-03.09.014", "01-14xx-00.08.053"]


def test_cross_references_do_not_become_courses():
    """Die unter 'Gleiche LVs:' aufgezählten Schienen sind bloße Verweise."""
    titel = {o.title for o in OPTIONS}
    assert "Übungen zu Diskrete Strukturen - 2 (Di)" not in titel
    assert "Übungen zu Diskrete Strukturen - 3 (Mi)" not in titel
    assert len(OPTIONS) == 4


def test_header_glued_to_gleiche_lvs_is_still_parsed():
    ds = next(o for o in OPTIONS if o.title.startswith("Übungen"))
    assert ds.kind == "UE"
    assert ds.module == "IN0015"
    assert ds.lv_id == "2409670901"


def test_weekday_hint_stays_in_title_but_module_code_goes():
    ds = next(o for o in OPTIONS if o.title.startswith("Übungen"))
    assert ds.title == "Übungen zu Diskrete Strukturen - 1 (Mo)"
    assert "IN0015" not in ds.title


def test_lv_number_with_umlaut_suffix():
    economics = next(o for o in OPTIONS if o.title == "Economics I")
    assert economics.lv_id == "WI000021EÜ"


def test_capacity_only_groups_get_a_note():
    ds = next(o for o in OPTIONS if o.group == "01-14xx-00.08.053")
    assert ds.note == "max. 20 Plätze"
    economics = next(o for o in OPTIONS if o.group == "Group 5")
    assert economics.note == "26 Teilnehmende"


def test_group_without_dates_is_dropped():
    """'Termine -' bedeutet: noch nichts angesetzt."""
    assert all(o.group != "03.10xx-03.11.018" for o in OPTIONS)


# --- Ausschlussgruppen ------------------------------------------------------

def test_groups_of_one_course_share_an_exclusive_key():
    economics = [o for o in OPTIONS if o.title == "Economics I"]
    assert economics[0].exclusive_key == economics[1].exclusive_key == "WI000021_E|UE"


def test_different_courses_do_not_exclude_each_other():
    economics = next(o for o in OPTIONS if o.title == "Economics I")
    ds = next(o for o in OPTIONS if o.title.startswith("Übungen"))
    assert economics.exclusive_key != ds.exclusive_key


def test_single_group_course_has_no_exclusive_key():
    solo = CourseOption(title="Vorlesung ohne Gruppen", kind="VO")
    assert solo.exclusive_key == ""


# --- Kombinationen ----------------------------------------------------------

def _opt(title, key, weekday, start, end, group):
    tag = date(2026, 10, 12 + weekday)
    return CourseOption(
        title=title, kind="UE", module=key, group=group,
        slots=(Slot(day=tag, start=start, end=end),),
    )


def test_combinations_pick_one_group_per_block():
    a1 = _opt("A", "MA", 0, time(8), time(10), "G1")
    a2 = _opt("A", "MA", 0, time(14), time(16), "G2")
    b1 = _opt("B", "MB", 0, time(9), time(11), "G1")
    found, total = combinations([a1, a2, b1], WS2627)
    assert total == 2                       # 2 Gruppen in A, 1 in B
    assert len(found) == 1                  # a1 überschneidet sich mit b1
    assert found[0].groups[0].group == "G2"


def test_combinations_keep_fixed_courses_in_every_result():
    vorlesung = CourseOption(
        title="Vorlesung", kind="VO",
        slots=(Slot(day=date(2026, 10, 13), start=time(8), end=time(10)),),
    )
    a1 = _opt("A", "MA", 0, time(8), time(10), "G1")
    a2 = _opt("A", "MA", 0, time(10), time(12), "G2")
    found, total = combinations([vorlesung, a1, a2], WS2627)
    assert total == 2 and len(found) == 2
    assert all(vorlesung in combo.options for combo in found)


def test_combinations_rank_compact_weeks_first():
    montag = _opt("A", "MA", 0, time(8), time(10), "Mo")
    dienstag = _opt("A", "MA", 1, time(8), time(10), "Di")
    anker = CourseOption(
        title="Anker", kind="VO",
        slots=(Slot(day=date(2026, 10, 12), start=time(12), end=time(14)),),
    )
    found, _ = combinations([anker, montag, dienstag], WS2627)
    # Montag teilt sich den Tag mit dem Anker -> ein Tag statt zwei.
    assert found[0].groups[0].group == "Mo"
    assert found[0].days == 1


def test_combination_shape_ignores_room_differences():
    raum_a = _opt("A", "MA", 0, time(8), time(10), "01-08xx-raumA")
    raum_b = _opt("A", "MA", 0, time(8), time(10), "01-08xx-raumB")
    found, _ = combinations([raum_a, raum_b], WS2627)
    assert len(found) == 2
    assert found[0].shape(WS2627) == found[1].shape(WS2627)


def test_conflict_free_combination_really_has_no_conflicts():
    found, _ = combinations(OPTIONS, WS2627)
    assert found
    for combo in found:
        assert find_conflicts(combo.options, WS2627) == []


# --- Zeitfilter und Größenpräferenz -----------------------------------------

def test_typical_start_ignores_a_single_shifted_date():
    """Ein Ausreißertermin darf die Gruppe nicht aus der Auswahl kippen."""
    option = CourseOption(
        title="A", kind="UE", module="MA", group="G1",
        slots=(
            Slot(day=date(2026, 10, 12), start=time(15), end=time(16, 30)),
            Slot(day=date(2026, 10, 19), start=time(15), end=time(16, 30)),
            Slot(day=date(2026, 10, 26), start=time(9, 45), end=time(11, 15)),
        ),
    )
    assert option.typical_start == time(15)
    assert option.earliest_start == time(9, 45)
    assert len(option.early_slots(time(11))) == 1


def test_not_before_filters_by_typical_start():
    frueh = _opt("A", "MA", 0, time(8), time(10), "frueh")
    spaet = _opt("A", "MA", 0, time(14), time(16), "spaet")
    found, total = combinations([frueh, spaet], WS2627, not_before=time(11))
    assert total == 1
    assert [c.groups[0].group for c in found] == ["spaet"]


def test_empty_block_raises_instead_of_dropping_the_course():
    """Sonst verschwindet eine Pflichtveranstaltung stillschweigend."""
    from tumcal.catalog import NoOptionLeft

    nur_frueh = _opt("A", "MA", 0, time(8), time(10), "G1")
    try:
        combinations([nur_frueh], WS2627, not_before=time(11))
    except NoOptionLeft as exc:
        assert "MA" in str(exc)
    else:
        raise AssertionError("NoOptionLeft erwartet")


def test_exceptions_report_only_chosen_groups():
    """Fest stehende Veranstaltungen werden zentral gemeldet, nicht je Kombination."""
    starr = CourseOption(
        title="Vorlesung", kind="VO",
        slots=(Slot(day=date(2026, 10, 15), start=time(10, 15), end=time(11, 45)),),
    )
    gruppe = CourseOption(
        title="Übung", kind="UE", module="MA", group="G1",
        slots=(
            Slot(day=date(2026, 10, 13), start=time(15), end=time(16)),
            Slot(day=date(2026, 10, 20), start=time(9), end=time(10)),
        ),
    )
    found, _ = combinations([starr, gruppe], WS2627, not_before=time(11))
    ausnahmen = found[0].exceptions(time(11))
    assert len(ausnahmen) == 1
    assert ausnahmen[0][0].group == "G1"


def test_prefer_small_orders_by_group_size():
    klein = CourseOption(title="A", kind="UE", module="MA", group="klein", participants=10,
                         slots=(Slot(day=date(2026, 10, 12), start=time(14), end=time(16)),))
    gross = CourseOption(title="A", kind="UE", module="MA", group="gross", participants=200,
                         slots=(Slot(day=date(2026, 10, 12), start=time(14), end=time(16)),))
    found, _ = combinations([klein, gross], WS2627, prefer_small=True)
    assert [c.groups[0].group for c in found] == ["klein", "gross"]
    assert found[0].total_size == 10


def test_size_prefers_reported_count_over_capacity():
    gemeldet = CourseOption(title="A", kind="UE", participants=33, capacity=100)
    nur_kontingent = CourseOption(title="B", kind="UE", capacity=20)
    assert gemeldet.size == 33
    assert nur_kontingent.size == 20
    assert CourseOption(title="C", kind="UE").size is None


# --- Präferenzen statt Einzelwahl -------------------------------------------

def test_selection_order_is_preserved_as_preference(tmp_path):
    """TUMonline verteilt per Los: die Reihenfolge der Auswahl ist die Präferenz."""
    import json

    from tumcal.cli import _read_selection

    optionen = [o for o in OPTIONS if o.title == "Economics I"]
    assert len(optionen) == 2
    umgekehrt = [optionen[1].key, optionen[0].key]
    pfad = tmp_path / "auswahl.json"
    pfad.write_text(json.dumps({"keys": umgekehrt}), encoding="utf-8")

    gewaehlt = _read_selection(str(pfad), OPTIONS)
    assert [o.key for o in gewaehlt] == umgekehrt


def test_several_groups_of_one_course_share_a_block():
    """Sie sind Alternativen im selben Verfahren, keine konkurrierenden Termine."""
    economics = [o for o in OPTIONS if o.title == "Economics I"]
    assert len({o.exclusive_key for o in economics}) == 1
