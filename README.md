# tumcal — TUMonline-Stundenplan als Kalender

Holt die persönlichen Termine aus TUMonline (Vorlesungen, Übungen, Seminare,
Praktika, Prüfungen), räumt sie auf und zeigt sie als Wochenkalender im Browser.

- **Keine externen Abhängigkeiten** — reines Python 3.9+ aus der Standardbibliothek.
- **Kein Passwort nötig** — Zugriff über den persönlichen iCal-Token-Link von TUMonline.
- **Offline nutzbar** — die erzeugte HTML-Datei lädt nichts nach.

## Was ich von dir brauche

**Nicht dein TUM-Passwort.** TUMonline läuft über den TUM-Login (Shibboleth,
inkl. Zwei-Faktor); ein Skript kann sich dort nicht sinnvoll einloggen, und dein
Passwort gehört auch nicht in ein Tool. TUMonline bietet stattdessen genau für
diesen Zweck einen **persönlichen iCal-Link mit Token** an — eine lange URL, die
deinen Kalender im iCalendar-Format ausliefert.

So kommst du dran:

1. In [TUMonline](https://campus.tum.de/tumonline/) einloggen.
2. Auf der Visitenkarte / im Menü **„Terminkalender"** („Personal Calendar") öffnen.
3. Oben **„Veröffentlichen"** bzw. **„Publish"** wählen (alternativ **„Export"**
   → iCal). TUMonline erzeugt daraufhin eine Abo-URL mit Token.
4. Diese URL kopieren.

Wichtig: Im Kalender müssen die gewünschten Kategorien eingeblendet sein
(Lehrveranstaltungen, Prüfungen), sonst fehlen sie im Export. Und: Termine
erscheinen erst, wenn du in der **Lehrveranstaltungsanmeldung** für die Kurse
bzw. Übungsgruppen angemeldet und fix zugeteilt bist — die reine Studienplan-
Ansicht (`myCurriculumSemesterPlan`) enthält Module, aber noch keine Termine.

Der Token ist ein Geheimnis: Wer den Link hat, sieht deinen Kalender. Er steht
deshalb in keiner eingecheckten Datei — `.gitignore` schließt `*.ics`,
`kalender.html` und `config.json` aus.

## Teil 1: Eigener Stundenplan (`build`)

```bash
# Link einmalig speichern (~/.config/tumcal/config.json, chmod 600)
python3 -m tumcal config --url "https://campus.tum.de/tumonline/...token..."

# Kalender bauen und öffnen
python3 -m tumcal build --open

# Nur Lehrveranstaltungen, nur Wintersemester
python3 -m tumcal build --only-lehre --start 2026-10-19 --end 2027-02-13 --out ws2627.html

# Termine im Terminal
python3 -m tumcal list --only-lehre
python3 -m tumcal courses
```

Alternativ ohne gespeicherten Link:

```bash
python3 -m tumcal build --url "https://campus.tum.de/tumonline/...token..."
export TUM_ICAL_URL="https://campus.tum.de/tumonline/...token..."   # oder per Umgebungsvariable
python3 -m tumcal build --file export.ics                            # oder aus lokaler Datei
```

### Optionen

| Option | Bedeutung |
| --- | --- |
| `--url` / `--file` | Quelle: Token-URL oder lokale `.ics`-Datei |
| `--save-ics PFAD` | Heruntergeladenes ICS zusätzlich sichern |
| `--only-lehre` | Nur VO, VI, VU, UE, TT, SE, PS, PR, PT |
| `--kinds VO,UE` | Nur bestimmte Arten |
| `--start` / `--end` | Zeitraum eingrenzen (`YYYY-MM-DD`) |
| `--hide-cancelled` | Abgesagte Termine ausblenden |
| `--out` / `--title` / `--open` | Zieldatei, Überschrift, Browser öffnen |

## Was aufgeräumt wird

- **Duplikate** entfernt (TUMonline liefert Termine teils doppelt).
- **Art erkannt** aus Kürzel (`VO`, `UE`, `PR` …) oder Text („Zentralübung",
  „Klausur") und farblich unterschieden.
- **Titel bereinigt**: `IN0001 VO Einführung in die Informatik 1` →
  *Einführung in die Informatik 1* + Modulnummer `IN0001` separat.
- **Raum lesbar**: `5602.EG.001 (MI HS 1)` → *MI HS 1*.
- **Abgesagte Termine** markiert statt still weggelassen.
- Ganztagstermine, gefaltete Zeilen und `DURATION`-statt-`DTEND` korrekt behandelt.

## Teil 2: Anmeldung planen (`plan`)

Solange du noch für nichts angemeldet bist, ist der persönliche Kalender leer.
Für diesen Fall gibt es die **Planungsansicht**: das mögliche LV-Angebot als
Wochenkalender, zum Anklicken, mit Überschneidungsprüfung.

### Variante A: CSV-Export aus TUMonline (am verlässlichsten)

TUMonline kann den persönlichen Terminkalender als CSV exportieren — je Termin
eine Zeile mit Datum, Uhrzeit, LV-Nummer, Art, Gruppe und Raum. Das ist die
beste Quelle, weil nichts abgetippt wird:

```bash
python3 -m tumcal plan --catalog personal_export.csv --open
python3 -m tumcal screen --catalog personal_export.csv \
    --core IN0015 --core IN0021 --not-before 10:00
```

Die Datei kommt in cp1252 statt UTF-8 — das wird erkannt. Zeilen werden zu
Lehrveranstaltungen gebündelt, parallel gelistete Räume zu einem Termin
zusammengefasst.

Mit `--maximize` sucht `screen` zusätzlich die **größte überschneidungsfreie
Auswahl** aus dem Rest — ein Maximum Independent Set auf dem Kollisionsgraphen,
exakt statt heuristisch. Gruppen derselben Lehrveranstaltung schließen einander
dabei aus: Sie sind Alternativen, keine zwei Module. Gleich große Lösungen
werden nach Kompaktheit sortiert.

`screen` hält die übrigen Module gegen gesetzte Hauptmodule: Was kollidiert,
was zu früh beginnt und was übrig bleibt. Maßgeblich für „nichts vor X Uhr"
ist dabei der **früheste regelmäßige** Termin, nicht der häufigste: Eine LV mit
Vorlesung Mi 08:00 und Übung Di 10:30 beginnt vor 10 Uhr, auch wenn die
meisten Termine später liegen. Einzelne Ausreißer (weniger als drei
Wiederholungen) gelten dagegen nicht als eigene Schiene.

### Variante B: aus TUMonline kopieren

In TUMonline die LV-Liste mit aufgeklappten Terminen markieren, kopieren, in
eine Textdatei speichern — fertig. Der Parser versteht das Rohformat inklusive
Bedienelementen („weniger anzeigen", „Präferenz bearbeiten"):

```bash
python3 -m tumcal plan --catalog paste.txt --open          # direkt planen
python3 -m tumcal plan --catalog paste.txt --select auswahl.json   # mit Vorauswahl
python3 -m tumcal plan --catalog paste.txt --catalog offen.csv     # mehrere Quellen
python3 -m tumcal convert --input paste.txt --out lv.json  # oder speichern
```

Erkannt werden LV-Nummer, Modulkennung, Art, Gruppen, Dozierende,
Teilnehmerzahl und alle Einzeltermine mit Raum. Parallel gelistete Räume
(Hörsaal + Übertragungsraum) werden zu einem Termin zusammengefasst.
Gruppen heißen dabei mal `Gruppe 1`, mal `Group 2`, mal `01-08xx-03.09.014` —
alle drei Formen werden erkannt. Die unter „Gleiche LVs:" aufgezählten
Querverweise auf Parallelschienen werden ignoriert, sie sind keine eigenen
Veranstaltungen.

`--catalog` ist mehrfach angebbar, etwa um das Angebot mit einer Liste noch
offener Posten zu verbinden. Einträge **ohne Termine** verschwinden dabei
nicht: Sie erscheinen im Kalender unter „Noch ohne Termine" und zählen bei
ECTS und Studienordnungs-Abgleich mit. So bleibt ein Modul sichtbar, dessen
Termine TUMonline noch nicht veröffentlicht hat.

Einzelne LV-Seiten ohne Terminliste werden ebenfalls verstanden: Dort steht
statt vieler Termine eine kompakte Serie („Montag, 10:00 - 12:00 von 13.04.2026
bis 13.07.2026"), aus der Wochentag, Uhrzeit und Zeitraum gelesen werden.

**Semesterprüfung:** Liegen die Termine eines Eintrags außerhalb der
Vorlesungszeit des gewählten Semesters, wird das gemeldet. Sonst liefert eine
LV aus einem anderen Semester einfach null Termine und verschwindet unbemerkt
aus dem Kalender.

Mit `--project` wird ein solcher Eintrag in das gewählte Semester übernommen —
aber nur Wochentag und Uhrzeit, mehr lässt sich aus einem vergangenen Semester
nicht seriös übertragen. Solche Termine heißen **[vorläufig]** und erscheinen
im Kalender gestrichelt. Nützlich, wenn TUMonline die neue Instanz noch nicht
veröffentlicht hat, man den Zeitslot aber schon einplanen will.

**Präsenz statt Kalendertage:** Termine in Videokonferenzen oder reinen
Online-Formaten werden erkannt. Die Kombinationssuche zählt deshalb
*Präsenztage* getrennt von belegten Tagen und sortiert danach — ein reiner
Online-Tag ist kein Uni-Besuch.

Einzeltermine haben Vorrang vor jeder Hochrechnung: Ausfalltage, Raumwechsel
und einmalig verschobene Uhrzeiten bleiben so erhalten.

### Variante C: als Tabelle

Das Angebot ist in TUMonline **kein iCal-Feed** — alternativ als Tabelle:

```bash
python3 -m tumcal template --out lv-angebot.csv   # Vorlage erzeugen
# Spalten aus TUMonline befüllen (Semesterplan / LV-Suche, Export oder Copy-Paste)
python3 -m tumcal plan --catalog lv-angebot.csv --semester ws2627 --open
```

Die Spalte `Tag`/`Von`/`Bis`/`Rhythmus` genügt — die konkreten Termine werden
über die Vorlesungszeit ausgerollt, inklusive Weihnachtsferien und Feiertagen.
`wöchentlich`, `14-tägig` und `Blockveranstaltung` werden unterschieden.

In der Planungsansicht:

- Angebot als blasse Blöcke, deine Auswahl in Farbe
- **Terminkonflikte** rot umrandet und oben aufgelistet
- Warnung, wenn du mehrere Gruppen derselben Übung anhakst
- ECTS-Summe der Auswahl
- **Anmelde-Checkliste** mit Direktlinks nach TUMonline
- Export der Auswahl als `auswahl.json` und als `.ics`

### Modulbeschreibungen einlesen

Der LV-Katalog sagt, *wann* etwas stattfindet. Die Modulbeschreibung sagt,
*was überhaupt dazugehört* — und deckt damit auf, welche Lehrveranstaltung im
eigenen Plan noch fehlt.

```bash
python3 -m tumcal modules --input module.txt --catalog paste.txt
python3 -m tumcal plan --catalog paste.txt --modules module.txt --open
```

Gelesen werden Modulkennung, ECTS, Sprache, Niveau, Präsenz- und
Gesamtstunden, die zugehörigen Lehrveranstaltungen und die Prüfungen. Die Art
jeder LV wird aus ihrem Namen erschlossen (`Tutorübungen zu …` → Übung,
`… - Lecture` → Vorlesung). Fehlt zu einem Modul eine Art im Katalog, wird das
gemeldet — eine Vorlesung mit integrierter Übung (`VI`) deckt den Übungsteil
mit ab.

ECTS hängen am Modul, nicht an der Gruppe: sie werden an alle Einträge des
Moduls geschrieben, in der Summe aber je Modul nur einmal gezählt. Die
angezeigte Punktzahl ändert sich dadurch nicht, wenn du die Übungsgruppe
wechselst.

### Studienordnung gegenprüfen

Die Modulbeschreibung sagt, was zu einem Modul gehört. Die Studienordnung sagt,
welche Module überhaupt vorgeschrieben sind — und ob der eigene Plan dazu passt.

```bash
python3 -m tumcal curriculum --catalog paste.txt --semester 1
```

Gemeldet werden Pflichtmodule des Fachsemesters, die im Plan fehlen, sowie
Planeinträge, die die Ordnung als Wahlmodul führt oder gar nicht nennt.

Wichtig zur Einordnung: Die **Wahlkataloge stehen nicht abschließend in der
Satzung** — laut FPSO aktualisiert sie der Prüfungsausschuss fortlaufend und
gibt Änderungen zu Semesterbeginn auf der Studiengangsseite bekannt. Ein Modul,
das hier fehlt, kann also trotzdem anerkannt sein. Verbindlich ist der
Studienplan in TUMonline, nicht diese Liste. Für den **Pflichtbereich** gilt
das nicht: der ist in Anlage 1 abschließend geregelt. Zusätzlich
werden die Credits aus Grundlagenprüfungen ausgewiesen — bei TUM WI müssen
davon mindestens 12 bis zum Ende des zweiten Fachsemesters bestanden sein
(§ 38 Abs. 2 FPSO).

Die Modulliste liegt als CSV in `tumcal/data/` (B.Sc. Wirtschaftsinformatik,
FPSO vom 10.08.2023 i. d. F. vom 12.02.2026). Für einen anderen Studiengang
genügt eine eigene CSV im selben Format via `--curriculum`.

### Prüfungstermine

Klausuren stehen nicht im Lehrveranstaltungskalender: Sie liegen nach der
Vorlesungszeit und haben eigene, deutlich frühere Anmeldefristen.

```bash
python3 -m tumcal exams --input pruefungen.txt --conflicts
```

Gelesen werden Termin, Uhrzeit, Räume, Prüfende, Anmeldezeitraum und
Abmeldefrist; Wiederholungstermine werden als solche erkannt. Mehrere
Prüfungen am selben Tag werden hervorgehoben, auch wenn sie sich zeitlich
nicht überschneiden.

### Konfliktfreie Kombinationen finden

Bei mehreren Übungsschienen mit je einem Dutzend Gruppen ist die Frage nicht
„kollidiert das?", sondern „welche Kombinationen gehen überhaupt?".

```bash
python3 -m tumcal combos --catalog paste.txt --top 5
python3 -m tumcal combos --catalog paste.txt --not-before 11:00 --prefer-small
```

`--not-before` verwirft wählbare Gruppen, die regelmäßig früher beginnen;
ein einzelner verschobener Termin kippt eine Gruppe dabei nicht heraus,
sondern wird als Ausnahme ausgewiesen. Fest stehende Veranstaltungen sind
nicht wählbar — liegen sie früher, wird das gemeldet statt stillschweigend
hingenommen. Bleibt für eine Veranstaltung keine Gruppe übrig, bricht der
Lauf mit einer Meldung ab, statt die Veranstaltung aus dem Plan fallen zu
lassen. `--prefer-small` sortiert kleine Gruppen nach vorn.

Gruppen derselben Veranstaltung (gleiches Modul, gleiche Art) gelten als
Wahlblock: aus jedem wird genau eine Gruppe gezogen, fest stehende
Veranstaltungen sind immer dabei. Ausgegeben werden die konfliktfreien
Kombinationen, sortiert nach kompakter Woche (wenige Tage, wenig Leerlauf).
Kombinationen, die sich nur im Seminarraum unterscheiden, werden
zusammengefasst.

Danach im Terminal:

```bash
python3 -m tumcal conflicts --catalog lv-angebot.csv --select auswahl.json
python3 -m tumcal anmelden  --catalog lv-angebot.csv --select auswahl.json --open
```

### Präferenzen statt Einzelwahl

TUMonline meldet dich seit WS 20/21 **am Anmeldeverfahren** an, nicht an einer
einzelnen Gruppe. Du kannst mehrere Gruppen einer Lehrveranstaltung anmelden
und je Gruppe eine Präferenz von niedrig bis hoch setzen; verteilt wird nach
Fristende per Losverfahren, wobei zuerst das Regelwerk des Verfahrens greift
und erst danach die Präferenzen ausgewertet werden. Der Anmeldezeitpunkt
spielt keine Rolle.

Der Planer bildet das ab: Mehrere Gruppen derselben LV anzuhaken ist der
Normalfall, **die Reihenfolge der Auswahl ist die Präferenz** (1 = hoch). Auf
Terminkonflikte werden nur die Erstpräferenzen geprüft — Alternativen derselben
LV schließen einander aus und können sich deshalb nicht überschneiden. Die
Anmelde-Checkliste gibt die Präferenzreihenfolge je Lehrveranstaltung aus.

### Zur Anmeldung selbst

`anmelden` **führt die Anmeldung nicht durch**. Es listet deine Auswahl mit
Fristen auf und öffnet auf Wunsch die TUMonline-Seiten nacheinander im Browser —
den Anmeldeklick machst du selbst, in deiner eigenen Sitzung.

Das ist Absicht: Die LV-Anmeldung ist eine verbindliche Handlung unter deinem
Namen, sie setzt den TUM-Login mit Zwei-Faktor voraus, und ein Skript, das
blind auf Formularknöpfe klickt, die es nie gesehen hat, ist genau da falsch.
Entspannend dabei: Seit WS 20/21 gibt es **kein „First come, first served"** —
innerhalb des Anmeldezeitraums ist der Zeitpunkt egal, es zählt kein Sekundenvorsprung.

## Kalender-Abo statt HTML

Denselben Token-Link kannst du direkt in Google Calendar, Apple Kalender oder
Outlook als Abo eintragen („Kalender über URL abonnieren"). Die Aktualisierung
dauert dort allerdings mehrere Stunden, und die Einträge bleiben unaufgeräumt.

## Semestertermine

In `tumcal/semester.py` hinterlegt (WS 2026/27: Vorlesungszeit 12.10.2026 –
05.02.2027, Weihnachtsferien 24.12. – 06.01., Allerheiligen 01.11.). Quelle ist
das TUM-Rundschreiben „Termine und Feiertage im Studienjahr 2026/27"; einzelne
Fakultäten weichen ab — vor der Anmeldung in TUMonline gegenprüfen.

## Tests

```bash
python3 -m pytest tests/ -q
```

150 Tests gegen die Fixtures in `tests/fixtures/` — ICS-Beispiel, CSV-Angebot,
TUMonline-Kopien, Modulbeschreibungen und Prüfungsseiten (öffentliches
Lehrangebot, keine persönlichen Daten).
