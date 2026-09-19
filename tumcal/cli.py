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
    CourseOption,
    TEMPLATE_CSV,
    find_conflicts,
    load_catalog,
)
from .fetch import ENV_VAR, FetchError, fetch_ics, read_ics, resolve_url, save_url
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
    keys = set(data.get("keys") or data if isinstance(data, list) else data.get("keys", []))
    chosen = [o for o in options if o.key in keys]
    unknown = keys - {o.key for o in options}
    if unknown:
        print(
            f"Warnung: {len(unknown)} Einträge aus der Auswahl fehlen im Katalog "
            f"({', '.join(sorted(unknown)[:3])}…)",
            file=sys.stderr,
        )
    return chosen


def cmd_plan(args) -> int:
    options = load_catalog(args.catalog)
    semester = get_semester(args.semester)
    out = Path(args.out)
    out.write_text(render_planner(options, semester, args.title), encoding="utf-8")

    without_times = [o for o in options if not o.slots_known]
    print(f"{len(options)} Einträge aus {args.catalog} → {out.resolve()}")
    if without_times:
        print(f"Hinweis: {len(without_times)} Einträge ohne Zeitangabe werden nicht angezeigt.")
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
    options = _read_selection(args.select, load_catalog(args.catalog))
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


def cmd_anmelden(args) -> int:
    """Öffnet die TUMonline-Seiten der Auswahl - der Klick bleibt bei dir."""
    options = _read_selection(args.select, load_catalog(args.catalog))
    if not options:
        print("Keine Auswahl gefunden.", file=sys.stderr)
        return 2

    with_url = [o for o in options if o.url]
    print(f"{len(options)} Veranstaltungen ausgewählt, {len(with_url)} mit Anmeldelink.\n")
    print("Die Anmeldung selbst bestätigst du in TUMonline - dieses Skript klickt nichts an.")
    print("Seit WS 20/21 gilt kein 'First come, first served': die Reihenfolge ist egal.\n")

    for index, option in enumerate(options, 1):
        frist = f" · Frist {option.deadline:%d.%m.%Y}" if option.deadline else ""
        print(f"[{index}/{len(options)}] {option.label}{frist}")
        if not option.url:
            print("      kein Link hinterlegt - in TUMonline suchen nach: "
                  f"{option.lv_id or option.title}")
            continue
        print(f"      {option.url}")
        if args.open:
            input("      [Enter] öffnet die Seite, [Strg+C] bricht ab ")
            webbrowser.open(option.url)
    if not args.open:
        print("\nMit --open werden die Seiten nacheinander im Browser geöffnet.")
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
    plan.add_argument("--catalog", required=True, help="CSV/JSON mit dem LV-Angebot")
    plan.add_argument("--semester", default="ws2627", choices=sorted(SEMESTERS))
    plan.add_argument("--out", default="planung.html")
    plan.add_argument("--title", default="LV-Planung")
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
    conflicts.add_argument("--catalog", required=True)
    conflicts.add_argument("--select", help="auswahl.json aus dem Planer")
    conflicts.add_argument("--semester", default="ws2627", choices=sorted(SEMESTERS))
    conflicts.set_defaults(func=cmd_conflicts)

    anmelden = sub.add_parser(
        "anmelden", help="Anmeldelinks der Auswahl auflisten bzw. nacheinander öffnen"
    )
    anmelden.add_argument("--catalog", required=True)
    anmelden.add_argument("--select", help="auswahl.json aus dem Planer")
    anmelden.add_argument("--open", action="store_true", help="Seiten im Browser öffnen")
    anmelden.set_defaults(func=cmd_anmelden)

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
    except (FetchError, CatalogError) as exc:
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
