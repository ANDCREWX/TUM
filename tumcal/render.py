"""Erzeugt eine eigenständige HTML-Seite mit Wochen- und Listenansicht."""

from __future__ import annotations

import html
import json
from datetime import date, timedelta

from .model import CourseEvent

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

# Feste Farbzuordnung je Veranstaltungsart, damit die Wochenansicht lesbar bleibt.
KIND_COLORS = {
    "VO": "--c-lecture",
    "VI": "--c-lecture",
    "VU": "--c-lecture",
    "UE": "--c-exercise",
    "TT": "--c-exercise",
    "SE": "--c-seminar",
    "PS": "--c-seminar",
    "PR": "--c-lab",
    "PT": "--c-lab",
    "PRUEFUNG": "--c-exam",
}


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def events_to_json(events: list[CourseEvent]) -> list[dict]:
    return [
        {
            "title": e.title,
            "code": e.course_code,
            "kind": e.kind,
            "kindLabel": e.kind_label,
            "color": KIND_COLORS.get(e.kind, "--c-other"),
            "date": e.day.isoformat(),
            "week": _monday(e.day).isoformat(),
            "start": e.start.strftime("%H:%M"),
            "end": e.end.strftime("%H:%M"),
            "startMin": e.start.hour * 60 + e.start.minute,
            "endMin": max(e.end.hour * 60 + e.end.minute, e.start.hour * 60 + e.start.minute + 30),
            "allDay": e.all_day,
            "room": e.room,
            "location": e.location,
            "cancelled": e.cancelled,
        }
        for e in events
    ]


def summarize(events: list[CourseEvent]) -> list[dict]:
    """Aggregiert pro Lehrveranstaltung für die Übersichtsliste."""
    courses: dict[tuple[str, str], dict] = {}
    for event in events:
        key = (event.title.lower(), event.kind)
        entry = courses.setdefault(
            key,
            {
                "title": event.title,
                "code": event.course_code,
                "kind": event.kind,
                "kindLabel": event.kind_label,
                "color": KIND_COLORS.get(event.kind, "--c-other"),
                "count": 0,
                "first": event.day.isoformat(),
                "last": event.day.isoformat(),
                "rooms": set(),
            },
        )
        entry["count"] += 1
        entry["first"] = min(entry["first"], event.day.isoformat())
        entry["last"] = max(entry["last"], event.day.isoformat())
        if event.room:
            entry["rooms"].add(event.room)
        if not entry["code"] and event.course_code:
            entry["code"] = event.course_code

    result = []
    for entry in courses.values():
        entry["rooms"] = sorted(entry["rooms"])
        result.append(entry)
    return sorted(result, key=lambda c: (c["kind"], c["title"]))


def render_html(events: list[CourseEvent], title: str = "Mein TUM-Stundenplan") -> str:
    payload = {
        "events": events_to_json(events),
        "courses": summarize(events),
        "weekdays": WEEKDAYS,
        "generated": date.today().isoformat(),
    }
    data = json.dumps(payload, ensure_ascii=False)
    safe_title = html.escape(title)
    return (
        _TEMPLATE.replace("__CSS__", _CSS)
        .replace("__TITLE__", safe_title)
        .replace("__DATA__", data)
    )


_CSS = r"""
  :root {
    --bg: #f6f7f9; --surface: #ffffff; --border: #dfe3e8;
    --text: #15181d; --muted: #666e79;
    --c-lecture: #2f6fd0; --c-exercise: #1f9268; --c-seminar: #8a5cd0;
    --c-lab: #c2701c; --c-exam: #c8384a; --c-other: #5a6472;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #14171c; --surface: #1c2027; --border: #2c323b;
      --text: #eceff3; --muted: #9aa3ae;
      --c-lecture: #5d9bf0; --c-exercise: #3fba8c; --c-seminar: #ab86e8;
      --c-lab: #e0964a; --c-exam: #e8677a; --c-other: #8b95a3;
    }
  }
  :root[data-theme="dark"] {
    --bg: #14171c; --surface: #1c2027; --border: #2c323b;
    --text: #eceff3; --muted: #9aa3ae;
    --c-lecture: #5d9bf0; --c-exercise: #3fba8c; --c-seminar: #ab86e8;
    --c-lab: #e0964a; --c-exam: #e8677a; --c-other: #8b95a3;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 24px 16px 64px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 20px; }
  .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 16px; }
  button, select {
    font: inherit; color: var(--text); background: var(--surface);
    border: 1px solid var(--border); border-radius: 8px; padding: 7px 12px; cursor: pointer;
  }
  button:hover { border-color: var(--muted); }
  button[aria-pressed="true"] { background: var(--text); color: var(--bg); border-color: var(--text); }
  .weeklabel { font-weight: 600; margin: 0 6px; min-width: 190px; }
  .grid {
    display: grid; grid-template-columns: 56px repeat(6, 1fr);
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; overflow: hidden;
  }
  .head { padding: 10px 6px; text-align: center; font-size: 13px; font-weight: 600;
          border-bottom: 1px solid var(--border); }
  .head small { display: block; font-weight: 400; color: var(--muted); }
  .head.today { color: var(--c-lecture); }
  .col { position: relative; border-left: 1px solid var(--border); }
  .hours { position: relative; }
  .hour { height: 44px; border-top: 1px solid var(--border); font-size: 11px;
          color: var(--muted); padding: 2px 6px; text-align: right; }
  .slot { position: relative; }
  .slot .line { height: 44px; border-top: 1px solid var(--border); }
  .ev {
    position: absolute; left: 3px; right: 3px; border-radius: 7px; padding: 4px 6px;
    color: #fff; font-size: 11.5px; overflow: hidden; line-height: 1.25;
  }
  .ev b { display: block; font-weight: 600; font-size: 12px;
          overflow: hidden; text-overflow: ellipsis; }
  .ev span { opacity: .9; display: block; }
  .ev.cancelled { opacity: .5; text-decoration: line-through; }
  .list { margin-top: 24px; }
  table { width: 100%; border-collapse: collapse; background: var(--surface);
          border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border); font-size: 14px; }
  th { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }
  tr:last-child td { border-bottom: none; }
  .tag { display: inline-block; padding: 1px 8px; border-radius: 999px;
         color: #fff; font-size: 11px; font-weight: 600; }
  .empty { padding: 32px; text-align: center; color: var(--muted); }
  @media (max-width: 720px) {
    .grid { grid-template-columns: 44px repeat(6, minmax(92px, 1fr)); overflow-x: auto; }
    .wrap { padding: 16px; }
  }
"""

_TEMPLATE = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
__CSS__</style>
</head>
<body>
<div class="wrap">
  <h1>__TITLE__</h1>
  <div class="sub" id="sub"></div>

  <div class="bar">
    <button id="prev">&larr; Woche</button>
    <span class="weeklabel" id="weeklabel"></span>
    <button id="next">Woche &rarr;</button>
    <button id="today">Heute</button>
    <select id="filter">
      <option value="all">Alle Termine</option>
      <option value="VO">Nur Vorlesungen</option>
      <option value="UE">Nur Übungen</option>
      <option value="lehre">Nur Lehrveranstaltungen</option>
      <option value="PRUEFUNG">Nur Prüfungen</option>
    </select>
  </div>

  <div id="calendar"></div>

  <div class="list">
    <h2 style="font-size:17px;margin:0 0 10px">Meine Lehrveranstaltungen</h2>
    <table>
      <thead><tr><th>Art</th><th>Veranstaltung</th><th>Modul</th><th>Termine</th><th>Zeitraum</th><th>Ort</th></tr></thead>
      <tbody id="courses"></tbody>
    </table>
  </div>
</div>

<script>
const DATA = __DATA__;
const DAY_START = 8 * 60, DAY_END = 22 * 60, PX_PER_MIN = 44 / 60;
const LEHRE = ["VO", "VI", "VU", "UE", "TT", "SE", "PS", "PR", "PT"];

const fmt = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("de-DE",
  { day: "2-digit", month: "2-digit", year: "numeric" });
const mondayOf = (d) => {
  const copy = new Date(d.getTime());
  copy.setDate(copy.getDate() - ((copy.getDay() + 6) % 7));
  copy.setHours(0, 0, 0, 0);
  return copy;
};
const isoOf = (d) => {
  const pad = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
};

// Startwoche: die laufende Woche, sonst die erste Woche mit Terminen.
const weeks = [...new Set(DATA.events.map((e) => e.week))].sort();
let current = mondayOf(new Date());
if (weeks.length && !weeks.includes(isoOf(current))) {
  const upcoming = weeks.find((w) => w >= isoOf(current));
  current = new Date((upcoming || weeks[weeks.length - 1]) + "T00:00:00");
}

const matches = (ev, mode) =>
  mode === "all" ? true : mode === "lehre" ? LEHRE.includes(ev.kind) : ev.kind === mode;

function layout(dayEvents) {
  // Überlappende Termine nebeneinander legen.
  const sorted = [...dayEvents].sort((a, b) => a.startMin - b.startMin);
  const columns = [];
  sorted.forEach((ev) => {
    let slot = columns.findIndex((col) => col[col.length - 1].endMin <= ev.startMin);
    if (slot === -1) { columns.push([ev]); slot = columns.length - 1; }
    else columns[slot].push(ev);
    ev._col = slot;
  });
  sorted.forEach((ev) => { ev._cols = columns.length; });
  return sorted;
}

function render() {
  const mode = document.getElementById("filter").value;
  const weekIso = isoOf(current);
  const visible = DATA.events.filter((e) => e.week === weekIso && matches(e, mode));
  const todayIso = isoOf(new Date());

  document.getElementById("weeklabel").textContent =
    fmt(weekIso) + " – " + fmt(isoOf(new Date(current.getTime() + 5 * 864e5)));

  let html = '<div class="grid"><div class="head"></div>';
  for (let d = 0; d < 6; d++) {
    const dayIso = isoOf(new Date(current.getTime() + d * 864e5));
    html += '<div class="head' + (dayIso === todayIso ? ' today' : '') + '">' +
      DATA.weekdays[d] + "<small>" + fmt(dayIso).slice(0, 6) + "</small></div>";
  }

  html += '<div class="hours">';
  for (let m = DAY_START; m < DAY_END; m += 60) html += '<div class="hour">' + (m / 60) + ":00</div>";
  html += "</div>";

  for (let d = 0; d < 6; d++) {
    const dayIso = isoOf(new Date(current.getTime() + d * 864e5));
    html += '<div class="col"><div class="slot">';
    for (let m = DAY_START; m < DAY_END; m += 60) html += '<div class="line"></div>';
    layout(visible.filter((e) => e.date === dayIso)).forEach((ev) => {
      const top = ev.allDay ? 0
        : (Math.max(ev.startMin, DAY_START) - DAY_START) * PX_PER_MIN;
      const height = ev.allDay ? 32
        : Math.max((ev.endMin - Math.max(ev.startMin, DAY_START)) * PX_PER_MIN, 22);
      const width = 100 / ev._cols;
      html += '<div class="ev' + (ev.cancelled ? " cancelled" : "") + '" style="top:' + top +
        "px;height:" + height + "px;left:calc(" + (ev._col * width) + "% + 3px);width:calc(" +
        width + '% - 6px);background:var(' + ev.color + ')" title="' +
        (ev.title + " (" + ev.kindLabel + ") " +
         (ev.allDay ? "ganztägig" : ev.start + "–" + ev.end) + " " + ev.location)
          .replace(/"/g, "&quot;") + '">' +
        "<b>" + ev.title + "</b><span>" +
        (ev.allDay ? "ganztägig" : ev.start + "–" + ev.end) + "</span>" +
        (ev.room ? "<span>" + ev.room + "</span>" : "") + "</div>";
    });
    html += "</div></div>";
  }
  html += "</div>";
  if (!visible.length) html += '<div class="empty">Keine Termine in dieser Woche.</div>';
  document.getElementById("calendar").innerHTML = html;
}

function renderCourses() {
  document.getElementById("courses").innerHTML = DATA.courses.map((c) =>
    "<tr><td><span class='tag' style='background:var(" + c.color + ")'>" + c.kindLabel +
    "</span></td><td>" + c.title + "</td><td>" + (c.code || "–") + "</td><td>" + c.count +
    "</td><td>" + fmt(c.first) + " – " + fmt(c.last) + "</td><td>" +
    (c.rooms.join(", ") || "–") + "</td></tr>").join("") ||
    "<tr><td colspan='6' class='empty'>Keine Lehrveranstaltungen gefunden.</td></tr>";
}

document.getElementById("prev").onclick = () => { current.setDate(current.getDate() - 7); render(); };
document.getElementById("next").onclick = () => { current.setDate(current.getDate() + 7); render(); };
document.getElementById("today").onclick = () => { current = mondayOf(new Date()); render(); };
document.getElementById("filter").onchange = render;

document.getElementById("sub").textContent =
  DATA.events.length + " Termine · " + DATA.courses.length +
  " Veranstaltungen · erzeugt am " + fmt(DATA.generated);
renderCourses();
render();
</script>
</body>
</html>
"""
