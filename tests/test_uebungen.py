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
