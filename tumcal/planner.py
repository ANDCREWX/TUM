"""Planungsansicht: mögliche Lehrveranstaltungen auswählen, Konflikte sehen."""

from __future__ import annotations

import hashlib
import html
import json

from .catalog import CourseOption
from .render import KIND_COLORS, WEEKDAYS, _CSS, _monday
from .semester import Semester


def options_to_json(options: list[CourseOption], semester: Semester) -> list[dict]:
    payload = []
    for option in options:
        events = option.events(semester)
        payload.append(
            {
                "key": option.key,
                "title": option.title,
                "label": option.label,
                "lvId": option.lv_id,
                "module": option.module,
                "kind": option.kind,
                "kindLabel": option.kind_label,
                "color": KIND_COLORS.get(option.kind, "--c-other"),
                "ects": option.ects,
                "moduleKey": option.module or option.title,
                "group": option.group,
                "room": option.room,
                "provisional": option.provisional,
                "online": option.online,
                "lecturer": option.lecturer,
                "url": option.url,
                "deadline": option.deadline.isoformat() if option.deadline else "",
                "note": option.note,
                # Gruppen derselben Veranstaltung schließen einander aus.
                "exclusive": option.exclusive_key,
                "slots": [
                    {
                        "date": e.day.isoformat(),
                        "week": _monday(e.day).isoformat(),
                        "start": e.start.strftime("%H:%M"),
                        "end": e.end.strftime("%H:%M"),
                        "startMin": e.start.hour * 60 + e.start.minute,
                        "endMin": e.end.hour * 60 + e.end.minute,
                    }
                    for e in events
                ],
            }
        )
    return payload


def render_planner(
    options: list[CourseOption],
    semester: Semester,
    title: str = "LV-Planung",
    preselected: list[str] | None = None,
) -> str:
    # Einträge ohne Termine dürfen nicht unsichtbar verschwinden: gerade sie
    # sind die offenen Posten, an die man sich erinnern muss.
    offen = [o for o in options if not o.slots_known]
    vorauswahl = list(preselected or [])
    # Ein fester Speicherschlüssel ließ die Auswahl eines früheren Kalenders
    # die Vorauswahl eines neuen überschreiben. Der Schlüssel hängt deshalb
    # an Titel, Angebot und Vorauswahl.
    kennung = hashlib.sha1(
        json.dumps([title, sorted(o.key for o in options), vorauswahl],
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]

    payload = {
        "planId": kennung,
        "preselected": vorauswahl,
        "openItems": [
            {
                "title": o.title,
                "kindLabel": o.kind_label,
                "color": KIND_COLORS.get(o.kind, "--c-other"),
                "module": o.module,
                "ects": o.ects,
                "note": o.note,
            }
            for o in offen
        ],
        "options": options_to_json(options, semester),
        "weekdays": WEEKDAYS,
        "semester": {
            "label": semester.label,
            "start": semester.lecture_start.isoformat(),
            "end": semester.lecture_end.isoformat(),
            "note": semester.note,
        },
    }
    return (
        _PLANNER.replace("__CSS__", _CSS + _EXTRA_CSS)
        .replace("__TITLE__", html.escape(title))
        .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    )


_EXTRA_CSS = r"""
  .layout { display: grid; grid-template-columns: 1fr 340px; gap: 20px; align-items: start; }
  @media (max-width: 960px) { .layout { grid-template-columns: 1fr; } }
  .panel { background: var(--surface); border: 1px solid var(--border);
           border-radius: 12px; padding: 14px; }
  .panel h2 { font-size: 15px; margin: 0 0 10px; }
  /* Bei vielen Übungsgruppen darf die Liste den Kalender nicht wegschieben. */
  #options { max-height: 62vh; overflow-y: auto; }
  @media (max-width: 960px) { #options { max-height: none; } }
  .opt { display: flex; gap: 9px; padding: 7px 0; border-bottom: 1px solid var(--border);
         align-items: flex-start; font-size: 13.5px; cursor: pointer; }
  .opt:last-child { border-bottom: none; }
  .opt input { margin-top: 3px; accent-color: var(--c-lecture); flex: none; }
  .opt .meta { color: var(--muted); font-size: 12px; }
  .group-title { font-weight: 600; font-size: 13px; margin: 14px 0 2px; }
  .group-title:first-child { margin-top: 0; }
  .hint { color: var(--muted); font-size: 11.5px; margin-bottom: 4px; }
  .rank { font-size: 11px; color: var(--muted); border: 1px solid var(--border);
          border-radius: 999px; padding: 0 6px; }
  .ev.ghost { opacity: .34; border: 1px dashed rgba(255,255,255,.75); }
  /* Vorläufig: Zeitslot übernommen, für dieses Semester unbestätigt. */
  .ev.provisional { border: 2px dashed rgba(255,255,255,.9); }
  .ev.provisional b::after { content: " ?"; opacity: .8; }
  .ev.conflict { outline: 2px solid var(--c-exam); outline-offset: -2px; }
  .stat { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; font-size: 13px; }
  .stat b { font-size: 18px; display: block; }
  .warn { background: color-mix(in srgb, var(--c-exam) 14%, transparent);
          border: 1px solid var(--c-exam); border-radius: 8px;
          padding: 9px 11px; font-size: 12.5px; margin-bottom: 10px; }
  .warn ul { margin: 6px 0 0; padding-left: 18px; }
  ol.checklist { padding-left: 20px; font-size: 13.5px; }
  ol.checklist li { margin-bottom: 8px; }
  ol.checklist a { color: var(--c-lecture); }
"""

_PLANNER = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__</style>
</head>
<body>
<div class="wrap">
  <h1>__TITLE__</h1>
  <div class="sub" id="sub"></div>

  <div class="bar">
    <button id="prev">&larr; Woche</button>
    <span class="weeklabel" id="weeklabel"></span>
    <button id="next">Woche &rarr;</button>
    <select id="view">
      <option value="selected">Nur Auswahl</option>
      <option value="all">Auswahl + Angebot</option>
    </select>
    <button id="saveSel">Auswahl speichern (JSON)</button>
    <button id="saveIcs">Als .ics exportieren</button>
    <button id="reset" title="Zurück zur mitgelieferten Auswahl">Auswahl zurücksetzen</button>
  </div>

  <div class="layout">
    <div>
      <div id="calendar"></div>
      <div class="panel" id="openPanel" style="margin-top:18px; display:none">
        <h2>Noch ohne Termine</h2>
        <div class="hint">Bekannt, aber noch nicht terminiert — im Kalender
          deshalb nicht zu sehen.</div>
        <ul id="openList" style="font-size:13.5px; padding-left:20px"></ul>
      </div>

      <div class="panel" style="margin-top:18px">
        <h2>Anmelde-Checkliste</h2>
        <div class="hint">In TUMonline zum Verfahren anmelden und je Gruppe die
          Präferenz setzen (hoch = Wunschgruppe). Der Anmeldezeitpunkt ist egal —
          verteilt wird per Losverfahren nach Fristende.</div>
        <ol class="checklist" id="checklist"></ol>
      </div>
    </div>

    <div class="panel">
      <h2>Angebot</h2>
      <div class="stat">
        <div><b id="nSel">0</b>gewählt</div>
        <div><b id="nEcts">0</b>ECTS</div>
        <div><b id="nConf">0</b>Konflikte</div>
      </div>
      <div id="warnings"></div>
      <div id="options"></div>
    </div>
  </div>
</div>

<script>
const DATA = __DATA__;
const DAY_START = 8 * 60, DAY_END = 22 * 60, PX_PER_MIN = 44 / 60;
const STORE = "tumcal.auswahl." + (DATA.planId || "default");

const pad = (n) => String(n).padStart(2, "0");
const isoOf = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
const fmt = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("de-DE",
  { day: "2-digit", month: "2-digit", year: "numeric" });
const mondayOf = (d) => {
  const c = new Date(d.getTime());
  c.setDate(c.getDate() - ((c.getDay() + 6) % 7));
  c.setHours(0, 0, 0, 0);
  return c;
};

let selected = new Set(DATA.preselected || []);
try {
  // Nur eine eigene Auswahl zu genau diesem Plan schlägt die Vorauswahl.
  const stored = localStorage.getItem(STORE);
  if (stored) selected = new Set(JSON.parse(stored));
} catch (e) { /* Privates Fenster o. Ä. - Auswahl bleibt dann flüchtig. */ }

const persist = () => {
  try { localStorage.setItem(STORE, JSON.stringify([...selected])); } catch (e) {}
};

// Erste Woche mit Terminen als Startpunkt.
const allWeeks = [...new Set(DATA.options.flatMap((o) => o.slots.map((s) => s.week)))].sort();
let current = mondayOf(new Date());
if (allWeeks.length && !allWeeks.includes(isoOf(current))) {
  current = new Date((allWeeks.find((w) => w >= isoOf(current)) || allWeeks[0]) + "T00:00:00");
}

const chosen = () => DATA.options.filter((o) => selected.has(o.key));
const byKey = {};
DATA.options.forEach((o) => { byKey[o.key] = o; });

// TUMonline verteilt nach Verfahren: mehrere Gruppen einer LV anmelden ist
// erwünscht, die Präferenz steuert nur das Losverfahren. Die Reihenfolge der
// Auswahl ist die Präferenz.
function prefRank(o) {
  if (!o.exclusive) return 0;
  const gleicherBlock = [...selected].filter(
    (k) => byKey[k] && byKey[k].exclusive === o.exclusive);
  return gleicherBlock.indexOf(o.key);
}

function conflicts() {
  // Nur Erstpräferenzen können gleichzeitig zugeteilt werden; Alternativen
  // derselben LV schließen einander aus und kollidieren daher nicht.
  const slots = [];
  chosen().filter((o) => prefRank(o) <= 0)
    .forEach((o) => o.slots.forEach((s) => slots.push({ o, s })));
  slots.sort((a, b) => a.s.date.localeCompare(b.s.date) || a.s.startMin - b.s.startMin);
  const out = [];
  for (let i = 0; i < slots.length; i++) {
    for (let j = i + 1; j < slots.length; j++) {
      if (slots[j].s.date !== slots[i].s.date) break;
      if (slots[j].s.startMin >= slots[i].s.endMin) continue;
      if (slots[j].o.key === slots[i].o.key) continue;
      out.push({ date: slots[i].s.date, a: slots[i], b: slots[j] });
    }
  }
  return out;
}

function renderOptions() {
  const groups = {};
  DATA.options.forEach((o) => { (groups[o.title] = groups[o.title] || []).push(o); });
  document.getElementById("options").innerHTML = Object.entries(groups).map(([titel, opts]) => {
    const mehrfach = opts.filter((o) => o.exclusive).length > 1;
    return "<div class='group-title'>" + titel + "</div>" +
      (mehrfach ? "<div class='hint'>Mehrere Gruppen – ruhig mehrere anhaken. " +
        "Die Reihenfolge deiner Auswahl ist die Präferenz (1 = hoch).</div>" : "") +
      opts.map((o) => {
        const zeiten = o.slots.length
          ? DATA.weekdays[new Date(o.slots[0].date + "T00:00:00").getDay() === 0 ? 6
              : new Date(o.slots[0].date + "T00:00:00").getDay() - 1].slice(0, 2) +
            " " + o.slots[0].start + "–" + o.slots[0].end + " · " + o.slots.length + " Termine"
          : "keine Termine hinterlegt";
        const rang = selected.has(o.key) && o.exclusive ? prefRank(o) + 1 : 0;
        return "<label class='opt'><input type='checkbox' data-key='" + o.key + "'" +
          (selected.has(o.key) ? " checked" : "") + "><span><span class='tag' style='background:var(" +
          o.color + ")'>" + o.kindLabel + "</span> " + (o.group || "") +
          (rang ? " <span class='rank'>Präferenz " + rang + "</span>" : "") +
          "<div class='meta'>" + zeiten + (o.room ? " · " + o.room : "") +
          (o.ects ? " · " + o.ects + " ECTS" : "") + "</div></span></label>";
      }).join("");
  }).join("");

  document.querySelectorAll(".opt input").forEach((box) => {
    box.onchange = () => {
      const key = box.dataset.key;
      if (box.checked) selected.add(key); else selected.delete(key);
      persist();
      update();
    };
  });
}

function renderCalendar() {
  const mode = document.getElementById("view").value;
  const weekIso = isoOf(current);
  const conf = conflicts();
  const conflictKeys = new Set(conf.flatMap((c) => [c.a.o.key + c.a.s.date + c.a.s.start,
                                                    c.b.o.key + c.b.s.date + c.b.s.start]));

  const visible = [];
  DATA.options.forEach((o) => {
    const isSel = selected.has(o.key);
    if (!isSel && mode !== "all") return;
    o.slots.filter((s) => s.week === weekIso)
      .forEach((s) => visible.push({ o, s, ghost: !isSel }));
  });

  document.getElementById("weeklabel").textContent =
    fmt(weekIso) + " – " + fmt(isoOf(new Date(current.getTime() + 5 * 864e5)));

  let out = '<div class="grid"><div class="head"></div>';
  for (let d = 0; d < 6; d++) {
    const dayIso = isoOf(new Date(current.getTime() + d * 864e5));
    out += '<div class="head">' + DATA.weekdays[d] + "<small>" + fmt(dayIso).slice(0, 6) + "</small></div>";
  }
  out += '<div class="hours">';
  for (let m = DAY_START; m < DAY_END; m += 60) out += '<div class="hour">' + (m / 60) + ":00</div>";
  out += "</div>";

  for (let d = 0; d < 6; d++) {
    const dayIso = isoOf(new Date(current.getTime() + d * 864e5));
    const items = visible.filter((v) => v.s.date === dayIso)
      .sort((a, b) => a.s.startMin - b.s.startMin);
    // Überlappende Blöcke nebeneinander verteilen.
    const cols = [];
    items.forEach((v) => {
      let idx = cols.findIndex((c) => c[c.length - 1].s.endMin <= v.s.startMin);
      if (idx === -1) { cols.push([v]); idx = cols.length - 1; } else cols[idx].push(v);
      v._col = idx;
    });
    items.forEach((v) => { v._cols = cols.length; });

    out += '<div class="col"><div class="slot">';
    for (let m = DAY_START; m < DAY_END; m += 60) out += '<div class="line"></div>';
    items.forEach((v) => {
      const top = (Math.max(v.s.startMin, DAY_START) - DAY_START) * PX_PER_MIN;
      const h = Math.max((v.s.endMin - Math.max(v.s.startMin, DAY_START)) * PX_PER_MIN, 22);
      const w = 100 / v._cols;
      const bad = conflictKeys.has(v.o.key + v.s.date + v.s.start);
      out += '<div class="ev' + (v.ghost ? " ghost" : "") + (bad ? " conflict" : "") +
        (v.o.provisional ? " provisional" : "") +
        '" style="top:' + top + "px;height:" + h + "px;left:calc(" + (v._col * w) +
        "% + 3px);width:calc(" + w + '% - 6px);background:var(' + v.o.color + ')" title="' +
        (v.o.label + " " + v.s.start + "–" + v.s.end + (v.o.room ? " " + v.o.room : "") +
         (v.o.provisional ? " — vorläufig, Zeitslot aus einem anderen Semester" : ""))
          .replace(/"/g, "&quot;") + '"><b>' + v.o.title + "</b><span>" +
        v.s.start + "–" + v.s.end + "</span>" + (v.o.group ? "<span>" + v.o.group + "</span>" : "") +
        "</div>";
    });
    out += "</div></div>";
  }
  out += "</div>";
  if (!visible.length) out += '<div class="empty">In dieser Woche ist nichts eingeplant.</div>';
  document.getElementById("calendar").innerHTML = out;
}

function renderSummary() {
  const sel = chosen();
  const conf = conflicts();
  const seen = new Set();
  // Eine wöchentliche Kollision ist ein Konflikt, nicht fünfzehn.
  const uniqueConf = conf.filter((c) => {
    const k = [c.a.o.key, c.b.o.key].sort().join("|");
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });

  document.getElementById("nSel").textContent = sel.length;
  // ECTS gehören zum Modul: Vorlesung und Übung zählen zusammen einmal.
  const proModul = {};
  sel.forEach((o) => { if (o.ects) proModul[o.moduleKey] = o.ects; });
  document.getElementById("nEcts").textContent =
    Object.values(proModul).reduce((a, b) => a + b, 0).toString().replace(".", ",");
  document.getElementById("nConf").textContent = uniqueConf.length;

  let warn = "";
  if (uniqueConf.length) {
    warn += "<div class='warn'><b>Terminkonflikte</b><ul>" + uniqueConf.slice(0, 6).map((c) =>
      "<li>" + fmt(c.date) + ", " + c.b.s.start + ": " + c.a.o.label + " ↔ " + c.b.o.label +
      "</li>").join("") + "</ul>" +
      (uniqueConf.length > 6 ? "<div>… und " + (uniqueConf.length - 6) + " weitere</div>" : "") +
      "</div>";
  }
  document.getElementById("warnings").innerHTML = warn;

  const bloecke = {};
  sel.forEach((o) => {
    const schluessel = o.exclusive || o.key;
    (bloecke[schluessel] = bloecke[schluessel] || []).push(o);
  });
  const eintraege = Object.values(bloecke).map((gruppe) => {
    gruppe.sort((a, b) => prefRank(a) - prefRank(b));
    const kopf = gruppe[0];
    const name = kopf.url
      ? "<a href='" + kopf.url + "' target='_blank' rel='noopener'>" + kopf.title + "</a>"
      : kopf.title;
    if (gruppe.length === 1 && !kopf.group) {
      return "<li>" + name + " <span class='meta'>(" + kopf.kindLabel + ")</span>" +
        (kopf.lvId ? " <span class='meta'>· " + kopf.lvId + "</span>" : "") + "</li>";
    }
    return "<li>" + name + " <span class='meta'>(" + kopf.kindLabel + ")</span><div class='meta'>" +
      gruppe.map((o, i) => "Präferenz " + (i + 1) + ": " + (o.group || "–")).join(" · ") +
      "</div></li>";
  });
  document.getElementById("checklist").innerHTML =
    eintraege.join("") || "<li class='meta'>Noch nichts ausgewählt.</li>";
}

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type: type }));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.getElementById("saveSel").onclick = () =>
  download("auswahl.json", JSON.stringify({ keys: [...selected] }, null, 2), "application/json");

document.getElementById("saveIcs").onclick = () => {
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//tumcal//Planung//DE"];
  chosen().forEach((o) => o.slots.forEach((s) => {
    const stamp = (d, t) => d.replace(/-/g, "") + "T" + t.replace(":", "") + "00";
    lines.push("BEGIN:VEVENT",
      "UID:" + o.key + "-" + s.date + "@tumcal",
      "DTSTART;TZID=Europe/Berlin:" + stamp(s.date, s.start),
      "DTEND;TZID=Europe/Berlin:" + stamp(s.date, s.end),
      "SUMMARY:" + o.label.replace(/[,;]/g, "\\$&"),
      "LOCATION:" + (o.room || "").replace(/[,;]/g, "\\$&"),
      "END:VEVENT");
  }));
  lines.push("END:VCALENDAR");
  download("planung.ics", lines.join("\r\n"), "text/calendar");
};

document.getElementById("reset").onclick = () => {
  selected = new Set(DATA.preselected || []);
  try { localStorage.removeItem(STORE); } catch (e) {}
  renderOptions();
  update();
};

document.getElementById("prev").onclick = () => { current.setDate(current.getDate() - 7); renderCalendar(); };
document.getElementById("next").onclick = () => { current.setDate(current.getDate() + 7); renderCalendar(); };
document.getElementById("view").onchange = renderCalendar;

function update() { renderCalendar(); renderSummary(); }

const offen = DATA.openItems || [];
if (offen.length) {
  document.getElementById("openPanel").style.display = "";
  document.getElementById("openList").innerHTML = offen.map((o) =>
    "<li><span class='tag' style='background:var(" + o.color + ")'>" + o.kindLabel +
    "</span> " + o.title + (o.module ? " <span class='meta'>· " + o.module + "</span>" : "") +
    (o.ects ? " <span class='meta'>· " + o.ects + " ECTS</span>" : "") +
    (o.note ? "<div class='meta'>" + o.note + "</div>" : "") + "</li>").join("");
}

document.getElementById("sub").textContent = DATA.semester.label + " · Vorlesungszeit " +
  fmt(DATA.semester.start) + " – " + fmt(DATA.semester.end) + " · " +
  DATA.options.length + " Einträge im Angebot" +
  (offen.length ? " · " + offen.length + " noch ohne Termine" : "");
renderOptions();
update();
</script>
</body>
</html>
"""
