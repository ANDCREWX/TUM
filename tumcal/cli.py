"""Kommandozeile: python -m tumcal <befehl>"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path

from .fetch import ENV_VAR, FetchError, fetch_ics, read_ics, resolve_url, save_url
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
    except FetchError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Dateifehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
