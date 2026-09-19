"""Semestertermine der TUM - Grundlage für das Ausrollen wöchentlicher Termine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(frozen=True)
class Semester:
    key: str
    label: str
    lecture_start: date
    lecture_end: date
    # Vorlesungsfreie Blöcke (jeweils inklusive) und einzelne Feiertage.
    breaks: tuple[tuple[date, date], ...] = ()
    holidays: tuple[date, ...] = ()
    note: str = ""

    def is_lecture_day(self, day: date) -> bool:
        if not (self.lecture_start <= day <= self.lecture_end):
            return False
        if day in self.holidays:
            return False
        return not any(start <= day <= end for start, end in self.breaks)

    def lecture_days(self, weekday: int) -> list[date]:
        """Alle Vorlesungstage eines Wochentags (0 = Montag)."""
        day = self.lecture_start
        while day.weekday() != weekday:
            day += timedelta(days=1)
        days: list[date] = []
        while day <= self.lecture_end:
            if self.is_lecture_day(day):
                days.append(day)
            day += timedelta(days=7)
        return days


# Quelle: TUM-Rundschreiben "Termine und Feiertage im Studienjahr 2026/27".
# Bitte vor der Anmeldung in TUMonline gegenprüfen - Fakultäten weichen ab.
WS2627 = Semester(
    key="ws2627",
    label="Wintersemester 2026/27",
    lecture_start=date(2026, 10, 12),
    lecture_end=date(2027, 2, 5),
    breaks=((date(2026, 12, 24), date(2027, 1, 6)),),
    holidays=(date(2026, 11, 1),),  # Allerheiligen
    note="Vorlesungszeit 12.10.2026-05.02.2027, Weihnachtsferien 24.12.-06.01.",
)

SS27 = Semester(
    key="ss27",
    label="Sommersemester 2027",
    lecture_start=date(2027, 4, 12),
    lecture_end=date(2027, 7, 16),
    breaks=(),
    holidays=(
        date(2027, 5, 6),   # Christi Himmelfahrt
        date(2027, 5, 17),  # Pfingstmontag
        date(2027, 5, 27),  # Fronleichnam
    ),
    note="Termine vorläufig - bitte in TUMonline prüfen.",
)

SEMESTERS: dict[str, Semester] = {s.key: s for s in (WS2627, SS27)}


def get_semester(key: str) -> Semester:
    try:
        return SEMESTERS[key.lower().replace("/", "").replace(" ", "")]
    except KeyError:
        raise SystemExit(
            f"Unbekanntes Semester '{key}'. Verfügbar: {', '.join(SEMESTERS)}"
        ) from None
