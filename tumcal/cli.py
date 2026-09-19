"""Kommandozeile: python -m tumcal <befehl>"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

from .catalog import (
    CatalogError,
    out_of_semester,
    project_to_semester,
    CourseOption,
    NoOptionLeft,
    combinations,
    CourseOption,
    TEMPLATE_CSV,
    find_conflicts,
    load_catalog,
)
from .fetch import ENV_VAR, FetchError, fetch_ics, read_ics, resolve_url, save_url
from .curriculum import check_plan, load_curriculum
from .exams import parse_exams
from .module import apply_ects, ects_total, missing_lectures, parse_modules
from .planner import render_planner
from .semester import SEMESTERS, get_semester
from .model import TYPE_LABELS, filter_events, load_events
from .render import render_html

LEHRE_KINDS = ["VO", "VI", "VU", "UE", "TT", "SE", "PS", "PR", "PT"]


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"Ungültiges Datum '{value}', erwartet YYYY-MM-DD.") from exc


def _load(args) -> list:
    if args.file:
        text = read_ics(args.file)
    else:
        url = resolve_url(args.url)
        text = fetch_ics(url)
        if args.save_ics:
            Path(args.save_ics).write_text(text, encoding="utf-8")
    events = load_events(text)

    kinds = None
    if args.only_lehre:
        kinds = LEHRE_KINDS
    elif args.kinds:
        kinds = [k.strip().upper() for k in args.kinds.split(",") if k.strip()]

    return filter_events(
        events,
        kinds=kinds,
        start=_parse_date(args.start),
        end=_parse_date(args.end),
        include_cancelled=not args.hide_cancelled,
    )


def cmd_build(args) -> int:
    events = _load(args)
    out = Path(args.out)
    out.write_text(render_html(events, args.title), encoding="utf-8")
    print(f"{len(events)} Termine → {out.resolve()}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def cmd_list(args) -> int:
    events = _load(args)
    if not events:
        print("Keine Termine gefunden.")
        return 0

    current_day: date | None = None
    for event in events:
        if event.day != current_day:
            current_day = event.day
            weekday = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][event.day.weekday()]
            print(f"\n{weekday} {event.day.strftime('%d.%m.%Y')}")
        marker = " [ABGESAGT]" if event.cancelled else ""
        room = f"  {event.room}" if event.room else ""
        zeit = "ganztägig   " if event.all_day else f"{event.start:%H:%M}–{event.end:%H:%M}"
        print(f"  {zeit}  {event.kind_label:<12} {event.title}{room}{marker}")
    print(f"\n{len(events)} Termine insgesamt.")
    return 0


def cmd_courses(args) -> int:
    events = _load(args)
    seen: dict[tuple[str, str], int] = {}
    for event in events:
        seen[(event.kind_label, event.title)] = seen.get((event.kind_label, event.title), 0) + 1
    for (kind, title), count in sorted(seen.items()):
        print(f"{kind:<12} {title}  ({count} Termine)")
    print(f"\n{len(seen)} Lehrveranstaltungen.")
    return 0


def _read_selection(path: str | None, options: list[CourseOption]) -> list[CourseOption]:
    """Auswahl aus der im Planer exportierten auswahl.json lesen."""
    if not path:
        return options
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    roh = data if isinstance(data, list) else data.get("keys", [])
    # Die Reihenfolge ist die Präferenz - sie darf nicht verloren gehen.
    nach_key = {o.key: o for o in options}
    chosen = [nach_key[k] for k in roh if k in nach_key]
    unknown = {k for k in roh if k not in nach_key}
    if unknown:
        print(
            f"Warnung: {len(unknown)} Einträge aus der Auswahl fehlen im Katalog "
            f"({', '.join(sorted(unknown)[:3])}…)",
            file=sys.stderr,
        )
    return chosen


def _load_catalogs(pfade) -> list[CourseOption]:
    """Mehrere Katalogdateien zusammenführen (Angebot + offene Posten)."""
    if isinstance(pfade, (str, Path)):
        pfade = [pfade]
    options: list[CourseOption] = []
    for pfad in pfade:
        options.extend(load_catalog(pfad))
    return options


def _semesterpruefung(options, semester, project: bool = False):
    """Einträge aus einem anderen Semester melden, auf Wunsch übernehmen."""
    fremd = out_of_semester(options, semester)
    if not fremd:
        return options
    wort = "Eintrag liegt" if len(fremd) == 1 else "Einträge liegen"
    print(f"ACHTUNG: {len(fremd)} {wort} außerhalb der Vorlesungszeit "
          f"({semester.label}):")
    for option, zeitraum in fremd:
        hinweis = f" — {option.note}" if option.note else ""
        print(f"  {option.label}: {zeitraum}{hinweis}")
    if not project:
        print("  Sie erscheinen in keinem Termin dieses Semesters. "
              "Mit --project als vorläufigen Zeitslot übernehmen.\n")
        return options

    print("  → als vorläufiger Zeitslot in dieses Semester übernommen "
          "(Wochentag und Uhrzeit, gestrichelt dargestellt).\n")
    return project_to_semester(options, semester)


def _mit_modulen(options: list[CourseOption], pfad: str | None) -> list[CourseOption]:
    """ECTS aus den Modulbeschreibungen ergänzen und Lücken melden."""
    if not pfad:
        return options
    module = parse_modules(Path(pfad).read_text(encoding="utf-8", errors="replace"))
    if not module:
        print(f"Warnung: in {pfad} keine Modulbeschreibung erkannt.", file=sys.stderr)
        return options

    fehlend = missing_lectures(options, module)
    if fehlend:
        print("FEHLENDE LEHRVERANSTALTUNGEN (laut Modulbeschreibung):")
        for modul, name, kind in fehlend:
            print(f"  {modul.code}: {name} [{kind}]")
        print("  → nicht im Katalog, taucht daher in keiner Planung auf.\n")
    return apply_ects(options, module)


def cmd_modules(args) -> int:
    module = parse_modules(Path(args.input).read_text(encoding="utf-8", errors="replace"))
    if not module:
        print("Keine Modulbeschreibung erkannt.", file=sys.stderr)
        return 2

    for modul in module:
        print(f"{modul.code:<12} {modul.name}")
        print(f"{'':12} {modul.ects:g} ECTS · {modul.language or '?'} · "
              f"{modul.presence_hours}h Präsenz / {modul.total_hours}h gesamt · {modul.responsible}")
        for name, kind in modul.expected:
            print(f"{'':12} LV  [{kind}] {name}")
        for pruefung in modul.exams:
            print(f"{'':12} Prüfung  {pruefung}")
        print()
    print(f"{len(module)} Module, {sum(m.ects for m in module):g} ECTS, "
          f"{sum(m.presence_hours for m in module)} Präsenzstunden.")

    if args.catalog:
        fehlend = missing_lectures(_load_catalogs(args.catalog), module)
        print()
        if fehlend:
            print("Im Katalog fehlen:")
            for modul, name, kind in fehlend:
                print(f"  {modul.code}: {name} [{kind}]")
            return 1
        print("Alle Lehrveranstaltungen der Module sind im Katalog vorhanden.")
    return 0


def cmd_plan(args) -> int:
    options = _mit_modulen(_load_catalogs(args.catalog), args.modules)
    semester = get_semester(args.semester)
    options = _semesterpruefung(options, semester, args.project)
    vorauswahl = [o.key for o in _read_selection(args.select, options)] if args.select else []
    out = Path(args.out)
    out.write_text(
        render_planner(options, semester, args.title, preselected=vorauswahl), encoding="utf-8"
    )

    without_times = [o for o in options if not o.slots_known]
    quellen = ", ".join(Path(p).name for p in args.catalog)
    print(f"{len(options)} Einträge aus {quellen} → {out.resolve()}")
    if without_times:
        print(f"{len(without_times)} davon ohne Termine — im Kalender unter "
              f"„Noch ohne Termine“ gelistet:")
        for option in without_times:
            print(f"  · {option.label}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def cmd_convert(args) -> int:
    """Aus TUMonline kopierten Text in einen speicherbaren Katalog überführen."""
    from .paste import to_json_catalog

    options = load_catalog(args.input)
    out = Path(args.out)
    out.write_text(
        json.dumps(to_json_catalog(options), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    termine = sum(len(o.slots) or len(o.occurrences(get_semester(args.semester))) for o in options)
    print(f"{len(options)} Veranstaltungen, {termine} Termine → {out.resolve()}")
    for option in options:
        print(f"  {option.kind_label:<12} {option.label}  ({len(option.slots)} Termine)")
    return 0


def cmd_template(args) -> int:
    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"{out} existiert bereits - mit --force überschreiben.", file=sys.stderr)
        return 2
    out.write_text(TEMPLATE_CSV, encoding="utf-8")
    print(f"Vorlage geschrieben: {out.resolve()}")
    print("Spalten ausfüllen (aus TUMonline) und dann: python3 -m tumcal plan --catalog " + str(out))
    return 0


def cmd_conflicts(args) -> int:
    options = _read_selection(args.select, _load_catalogs(args.catalog))
    conflicts = find_conflicts(options, get_semester(args.semester))
    if not conflicts:
        print(f"Keine Überschneidungen bei {len(options)} Veranstaltungen.")
        return 0
    seen = set()
    for conflict in conflicts:
        pair = tuple(sorted((conflict.first.key, conflict.second.key)))
        if pair in seen:
            continue
        seen.add(pair)
        print(conflict.describe())
    paare = "Paar" if len(seen) == 1 else "Paare"
    print(f"\n{len(seen)} kollidierendes {paare}, {len(conflicts)} betroffene Termine."
          if len(seen) == 1
          else f"\n{len(seen)} kollidierende {paare}, {len(conflicts)} betroffene Termine.")
    return 1


WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _woche(option, semester) -> str:
    events = option.events(semester)
    if not events:
        return "keine Termine"
    first = events[0]
    tage = sorted({WOCHENTAGE[e.day.weekday()] for e in events})
    return f"{'/'.join(tage)} {first.start:%H:%M}-{first.end:%H:%M}"


def _parse_uhrzeit(value: str | None):
    if not value:
        return None
    from datetime import datetime as _dt

    for fmt in ("%H:%M", "%H"):
        try:
            return _dt.strptime(value, fmt).time()
        except ValueError:
            continue
    raise SystemExit(f"Ungültige Uhrzeit '{value}', erwartet HH:MM.")


def cmd_combos(args) -> int:
    """Konfliktfreie Kombinationen aus allen Gruppenalternativen."""
    options = _mit_modulen(_load_catalogs(args.catalog), args.modules)
    semester = get_semester(args.semester)
    options = _semesterpruefung(options, semester, args.project)
    not_before = _parse_uhrzeit(args.not_before)

    if not_before:
        # Fest stehende Veranstaltungen sind nicht wählbar - wer zu früh
        # liegt, bleibt trotzdem im Plan. Das muss gesagt werden.
        starr = [
            o for o in options
            if not o.exclusive_key and o.earliest_start and o.earliest_start < not_before
        ]
        entfallen = [
            o for o in options
            if o.exclusive_key and o.typical_start and o.typical_start < not_before
        ]
        print(f"Filter: nichts vor {not_before:%H:%M} — {len(entfallen)} Gruppen entfallen.")
        if starr:
            print("ACHTUNG, nicht wählbar und trotzdem früher:")
            for option in starr:
                fruehe = [e for e in option.events(semester) if e.start.time() < not_before]
                zeiten = sorted({f"{WOCHENTAGE[e.start.weekday()]} {e.start:%H:%M}"
                                 for e in fruehe})
                print(f"  {option.label}: {', '.join(zeiten)} "
                      f"({len(fruehe)} Termine) — daran führt kein Weg vorbei")
        print()

    found, total = combinations(
        options, semester, limit=args.limit,
        not_before=not_before, prefer_small=args.prefer_small,
    )

    bloecke: dict[str, int] = {}
    for option in options:
        if option.exclusive_key:
            bloecke[option.exclusive_key] = bloecke.get(option.exclusive_key, 0) + 1
    for key, anzahl in sorted(bloecke.items()):
        print(f"Wahlblock {key.split('|')[0]} ({key.split('|')[1]}): {anzahl} Gruppen")
    print(f"\n{total} mögliche Kombinationen, davon {len(found)} konfliktfrei.\n")

    if not found:
        print("Keine konfliktfreie Kombination gefunden.")
        return 1

    # Kombinationen, die sich nur im Seminarraum unterscheiden, zusammenfassen.
    nach_form: dict[tuple, list] = {}
    for combo in found:
        nach_form.setdefault(combo.shape(semester), []).append(combo)
    # Dieselbe Rangfolge wie die Suche - sonst wirft die Anzeige die
    # Größensortierung wieder weg.
    if args.prefer_small:
        schluessel = lambda g: (g[0].campus_days, g[0].days, g[0].total_size, g[0].gap_minutes)
    else:
        schluessel = lambda g: (g[0].campus_days, g[0].days, g[0].gap_minutes)
    formen = sorted(nach_form.values(), key=schluessel)
    print(f"{len(formen)} davon zeitlich verschieden (der Rest unterscheidet sich nur im Raum).\n")

    for index, gruppe in enumerate(formen[: args.top], 1):
        combo = min(gruppe, key=lambda c: c.total_size) if args.prefer_small else gruppe[0]
        leerlauf = f"{combo.gap_minutes // 60}h{combo.gap_minutes % 60:02d}"
        varianten = f", {len(gruppe)} Raumvarianten" if len(gruppe) > 1 else ""
        punkte = ects_total(combo.options)
        groesse = (f", {combo.total_size} Personen gesamt" if combo.total_size else "")
        groesse += f", {punkte:g} ECTS" if punkte else ""
        praesenz = (f"{combo.campus_days} Präsenztage"
                    + (f" (+{combo.days - combo.campus_days} online)"
                       if combo.days > combo.campus_days else ""))
        print(f"[{index}] {praesenz}, {leerlauf} Leerlauf pro Woche{groesse}{varianten}")
        if not_before:
            for option, slot in combo.exceptions(not_before)[:2]:
                print(f"      Ausnahme: {option.label[:40]} am "
                      f"{slot.day:%d.%m.%Y} schon um {slot.start:%H:%M}")
        for option in combo.groups:
            raeume = sorted({c_o.group for c in gruppe for c_o in c.groups
                             if c_o.exclusive_key == option.exclusive_key})
            alternativen = f"  (+{len(raeume) - 1} weitere)" if len(raeume) > 1 else ""
            groesse = f" [{option.size}]" if option.size else ""
            print(f"      {option.title[:42]:<42} {_woche(option, semester):<18}"
                  f" {option.group}{groesse}{alternativen}")
        print()
    if len(formen) > args.top:
        print(f"… und {len(formen) - args.top} weitere Zeitvarianten. Mit --top mehr anzeigen.")
    return 0


def cmd_anmelden(args) -> int:
    """Öffnet die TUMonline-Seiten der Auswahl - der Klick bleibt bei dir."""
    options = _read_selection(args.select, _load_catalogs(args.catalog))
    if not options:
        print("Keine Auswahl gefunden.", file=sys.stderr)
        return 2

    with_url = [o for o in options if o.url]
    print(f"{len(options)} Veranstaltungen ausgewählt, {len(with_url)} mit Anmeldelink.\n")
    print("Die Anmeldung selbst bestätigst du in TUMonline - dieses Skript klickt nichts an.")
    print("Angemeldet wird am Verfahren, nicht an der einzelnen Gruppe: mehrere")
    print("Gruppen anmelden und je Gruppe die Präferenz setzen (hoch = Wunsch).")
    print("Der Zeitpunkt ist egal, verteilt wird per Losverfahren nach Fristende.\n")

    # Gruppen derselben LV sind Alternativen: sie werden gemeinsam angemeldet,
    # die Reihenfolge der Auswahl ist die Präferenz.
    bloecke: dict[str, list] = {}
    reihenfolge: list[str] = []
    for option in options:
        schluessel = option.exclusive_key or option.key
        if schluessel not in bloecke:
            bloecke[schluessel] = []
            reihenfolge.append(schluessel)
        bloecke[schluessel].append(option)

    for index, schluessel in enumerate(reihenfolge, 1):
        gruppe = bloecke[schluessel]
        kopf = gruppe[0]
        frist = f" · Frist {kopf.deadline:%d.%m.%Y}" if kopf.deadline else ""
        print(f"[{index}/{len(reihenfolge)}] {kopf.title} ({kopf.kind_label}){frist}")
        if len(gruppe) > 1 or kopf.group:
            for rang, option in enumerate(gruppe, 1):
                print(f"      Präferenz {rang}: {option.group or '–'}"
                      f"  {_woche(option, get_semester('ws2627'))}")
        if not kopf.url:
            print("      kein Link hinterlegt - in TUMonline suchen nach: "
                  f"{kopf.lv_id or kopf.title}")
            continue
        print(f"      {kopf.url}")
        if args.open:
            input("      [Enter] öffnet die Seite, [Strg+C] bricht ab ")
            webbrowser.open(kopf.url)
    if not args.open:
        print("\nMit --open werden die Seiten nacheinander im Browser geöffnet.")
    return 0


def cmd_curriculum(args) -> int:
    """Plan gegen die Pflichtmodule der Studienordnung halten."""
    curriculum = load_curriculum(args.curriculum)
    options = _load_catalogs(args.catalog)
    ergebnis = check_plan(options, curriculum, semester=args.semester)

    print(f"{args.semester}. Fachsemester laut Studienordnung: "
          f"{ergebnis.planned_credits + ergebnis.missing_credits:g} Credits\n")

    if ergebnis.planned:
        print("Im Plan:")
        for modul in ergebnis.planned:
            mark = " [Grundlagenprüfung]" if modul.foundation else ""
            print(f"  ✓ {modul.code:<12} {modul.name[:44]:<44} {modul.ects:>4.0f} CR{mark}")
    if ergebnis.missing:
        print("\nFEHLT im Plan:")
        for modul in ergebnis.missing:
            mark = " [Grundlagenprüfung]" if modul.foundation else ""
            print(f"  ✗ {modul.code:<12} {modul.name[:44]:<44} {modul.ects:>4.0f} CR{mark}")
    if ergebnis.elective:
        print("\nIm Plan als Wahlmodul der Ordnung:")
        for eintrag in ergebnis.elective:
            print(f"  ○ {eintrag}")
    if ergebnis.unlisted:
        print("\nIm Plan, in dieser Modulliste nicht genannt:")
        for eintrag in ergebnis.unlisted:
            print(f"  ? {eintrag}")
        print("  Die Wahlkataloge werden laut FPSO fortlaufend vom Prüfungsausschuss")
        print("  aktualisiert und stehen nicht abschließend in der Satzung. Ein hier")
        print("  fehlendes Modul kann als Wahlmodul anerkannt sein — verbindlich ist")
        print("  der Studienplan in TUMonline, nicht diese Liste.")

    print(f"\nGrundlagenprüfungen (§ 38 Abs. 2): {ergebnis.foundation_planned:g} von "
          f"{ergebnis.foundation_total:g} Credits im Plan.")
    print("  Mindestens 12 Credits davon bis Ende des 2. Fachsemesters.")
    if ergebnis.foundation_planned < 12:
        print("  ACHTUNG: der Plan deckt die Hürde nicht ab.")
    return 1 if ergebnis.missing else 0


def cmd_exams(args) -> int:
    """Prüfungstermine und Anmeldefristen auflisten."""
    pruefungen = parse_exams(Path(args.input).read_text(encoding="utf-8", errors="replace"))
    if not pruefungen:
        print("Keine Prüfungstermine erkannt.", file=sys.stderr)
        return 2

    for pruefung in sorted(pruefungen, key=lambda p: p.slots[0].day):
        slot = pruefung.slots[0]
        tag = WOCHENTAGE[slot.day.weekday()]
        print(f"{tag} {slot.day:%d.%m.%Y}  {slot.start:%H:%M}-{slot.end:%H:%M}  "
              f"{pruefung.title[:44]:<44} ({pruefung.group})")
        if pruefung.registration_start and pruefung.deadline:
            print(f"{'':12}Anmeldung {pruefung.registration_start:%d.%m.%Y} – "
                  f"{pruefung.deadline:%d.%m.%Y}"
                  + (f", Abmeldung bis {pruefung.withdraw_until:%d.%m.%Y}"
                     if pruefung.withdraw_until else ""))

    # Zwei Klausuren am selben Tag sind planungsrelevant.
    nach_tag: dict = {}
    for pruefung in pruefungen:
        nach_tag.setdefault(pruefung.slots[0].day, []).append(pruefung)
    doppelt = {tag: ps for tag, ps in nach_tag.items() if len(ps) > 1}
    if doppelt:
        print()
        for tag, ps in sorted(doppelt.items()):
            print(f"Mehrere Prüfungen am {tag:%d.%m.%Y}: "
                  + ", ".join(f"{p.title[:28]} {p.slots[0].start:%H:%M}" for p in ps))

    if args.conflicts:
        ueberschneidung = find_conflicts(pruefungen, get_semester(args.semester))
        print()
        print(f"{len(ueberschneidung)} echte Zeitüberschneidungen."
              if ueberschneidung else "Keine Zeitüberschneidung zwischen den Prüfungen.")
        for conflict in ueberschneidung[:5]:
            print("  " + conflict.describe())
    return 0


def cmd_config(args) -> int:
    path = save_url(args.url)
    print(f"iCal-URL gespeichert in {path} (nur für dich lesbar).")
    return 0


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", help="TUMonline iCal-Token-URL")
    parser.add_argument("--file", help="Lokale .ics-Datei statt Download")
    parser.add_argument("--save-ics", help="Heruntergeladenes ICS zusätzlich hier ablegen")
    parser.add_argument("--start", help="Nur Termine ab diesem Datum (YYYY-MM-DD)")
    parser.add_argument("--end", help="Nur Termine bis zu diesem Datum (YYYY-MM-DD)")
    parser.add_argument(
        "--kinds",
        help="Nur diese Arten, kommagetrennt: " + ",".join(TYPE_LABELS),
    )
    parser.add_argument(
        "--only-lehre",
        action="store_true",
        help="Nur Lehrveranstaltungen (Vorlesungen, Übungen, Seminare, Praktika)",
    )
    parser.add_argument("--hide-cancelled", action="store_true", help="Abgesagte ausblenden")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tumcal",
        description="TUMonline-Termine holen, aufräumen und als Kalender anzeigen.",
        epilog=f"Die iCal-URL kann auch über die Umgebungsvariable {ENV_VAR} kommen.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="HTML-Kalender erzeugen")
    _add_source_args(build)
    build.add_argument("--out", default="kalender.html", help="Zieldatei (Standard: kalender.html)")
    build.add_argument("--title", default="Mein TUM-Stundenplan", help="Überschrift der Seite")
    build.add_argument("--open", action="store_true", help="Danach im Browser öffnen")
    build.set_defaults(func=cmd_build)

    listing = sub.add_parser("list", help="Termine im Terminal auflisten")
    _add_source_args(listing)
    listing.set_defaults(func=cmd_list)

    courses = sub.add_parser("courses", help="Belegte Lehrveranstaltungen zusammenfassen")
    _add_source_args(courses)
    courses.set_defaults(func=cmd_courses)

    plan = sub.add_parser("plan", help="Mögliche LVs als Planungskalender anzeigen")
    plan.add_argument("--catalog", required=True, action="append",
                      help="LV-Angebot; mehrfach angebbar (z. B. Angebot + offene Posten)")
    plan.add_argument("--semester", default="ws2627", choices=sorted(SEMESTERS))
    plan.add_argument("--out", default="planung.html")
    plan.add_argument("--title", default="LV-Planung")
    plan.add_argument("--select", help="auswahl.json: diese Einträge vorauswählen")
    plan.add_argument("--modules", help="Modulbeschreibungen: ECTS ergänzen, Lücken melden")
    plan.add_argument("--project", action="store_true",
                      help="Termine aus anderen Semestern als vorläufigen Zeitslot übernehmen")
    plan.add_argument("--open", action="store_true", help="Danach im Browser öffnen")
    plan.set_defaults(func=cmd_plan)

    convert = sub.add_parser(
        "convert", help="Aus TUMonline kopierten Text in einen Katalog (JSON) umwandeln"
    )
    convert.add_argument("--input", required=True, help="Textdatei mit der TUMonline-Kopie")
    convert.add_argument("--out", default="lv-angebot.json")
    convert.add_argument("--semester", default="ws2627", choices=sorted(SEMESTERS))
    convert.set_defaults(func=cmd_convert)

    template = sub.add_parser("template", help="Leere Katalog-Vorlage schreiben")
    template.add_argument("--out", default="lv-angebot.csv")
    template.add_argument("--force", action="store_true")
    template.set_defaults(func=cmd_template)

    conflicts = sub.add_parser("conflicts", help="Überschneidungen der Auswahl prüfen")
    conflicts.add_argument("--catalog", required=True, action="append")
    conflicts.add_argument("--select", help="auswahl.json aus dem Planer")
    conflicts.add_argument("--semester", default="ws2627", choices=sorted(SEMESTERS))
    conflicts.set_defaults(func=cmd_conflicts)

    combos = sub.add_parser(
        "combos", help="Konfliktfreie Kombinationen der Gruppenalternativen suchen"
    )
    combos.add_argument("--catalog", required=True, action="append")
    combos.add_argument("--semester", default="ws2627", choices=sorted(SEMESTERS))
    combos.add_argument("--top", type=int, default=5, help="Wie viele anzeigen (Standard: 5)")
    combos.add_argument("--limit", type=int, default=20000, help="Obergrenze geprüfter Kombinationen")
    combos.add_argument("--modules", help="Modulbeschreibungen: ECTS ergänzen, Lücken melden")
    combos.add_argument("--project", action="store_true",
                        help="Termine aus anderen Semestern als vorläufigen Zeitslot übernehmen")
    combos.add_argument("--not-before", help="Keine wählbare Gruppe vor dieser Uhrzeit (HH:MM)")
    combos.add_argument("--prefer-small", action="store_true",
                        help="Kleine Gruppen vor geringem Leerlauf einsortieren")
    combos.set_defaults(func=cmd_combos)

    anmelden = sub.add_parser(
        "anmelden", help="Anmeldelinks der Auswahl auflisten bzw. nacheinander öffnen"
    )
    anmelden.add_argument("--catalog", required=True, action="append")
    anmelden.add_argument("--select", help="auswahl.json aus dem Planer")
    anmelden.add_argument("--open", action="store_true", help="Seiten im Browser öffnen")
    anmelden.set_defaults(func=cmd_anmelden)

    modules = sub.add_parser(
        "modules", help="Modulbeschreibungen auswerten und mit dem Katalog abgleichen"
    )
    modules.add_argument("--input", required=True, help="Kopierte Modulbeschreibungen")
    modules.add_argument("--catalog", action="append",
                         help="Katalog gegenprüfen: welche LV fehlt? (mehrfach angebbar)")
    modules.set_defaults(func=cmd_modules)

    curriculum = sub.add_parser(
        "curriculum", help="Plan gegen die Pflichtmodule der Studienordnung prüfen"
    )
    curriculum.add_argument("--catalog", required=True, action="append")
    curriculum.add_argument("--semester", type=int, default=1, help="Fachsemester (Standard: 1)")
    curriculum.add_argument("--curriculum", help="Eigene Modulliste (CSV); Standard: WI B.Sc.")
    curriculum.set_defaults(func=cmd_curriculum)

    exams = sub.add_parser("exams", help="Prüfungstermine und Anmeldefristen auswerten")
    exams.add_argument("--input", required=True, help="Kopierte Prüfungsseiten")
    exams.add_argument("--semester", default="ws2627", choices=sorted(SEMESTERS))
    exams.add_argument("--conflicts", action="store_true", help="Zeitüberschneidungen prüfen")
    exams.set_defaults(func=cmd_exams)

    config = sub.add_parser("config", help="iCal-URL dauerhaft speichern")
    config.add_argument("--url", required=True, help="TUMonline iCal-Token-URL")
    config.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        # Ausgabe nach `| head` o. Ä. - kein Fehlerfall.
        return 0
    except (FetchError, CatalogError, NoOptionLeft) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"Dateifehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
