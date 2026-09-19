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

## Verwendung

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

## Kalender-Abo statt HTML

Denselben Token-Link kannst du direkt in Google Calendar, Apple Kalender oder
Outlook als Abo eintragen („Kalender über URL abonnieren"). Die Aktualisierung
dauert dort allerdings mehrere Stunden, und die Einträge bleiben unaufgeräumt.

## Tests

```bash
python3 -m pytest tests/ -q
```

Die Tests laufen gegen `tests/fixtures/beispiel.ics` — eine künstliche Datei im
TUMonline-Format, keine echten Daten.
