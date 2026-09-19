"""Abgleich des eigenen Plans mit der Studienordnung (FPSO, Anlage 1)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from .catalog import CourseOption

DEFAULT_CURRICULUM = Path(__file__).parent / "data" / "wi-ba-fpso-2026.csv"


@dataclass(frozen=True)
class CurriculumModule:
    code: str
    name: str
    area: str = ""
    semester: int = 0
    sws: str = ""
    ects: float = 0.0
    exam_form: str = ""
    duration: str = ""
    language: str = ""
    foundation: bool = False


@dataclass
class PlanCheck:
    """Ergebnis des Abgleichs für ein Fachsemester."""

    semester: int
    planned: list[CurriculumModule]
    missing: list[CurriculumModule]
    unlisted: list[str]              # im Plan, aber nicht in der Ordnung
    foundation_planned: float        # Credits aus Grundlagenprüfungen im Plan
    foundation_total: float          # insgesamt verfügbare Grundlagen-Credits

    @property
    def planned_credits(self) -> float:
        return sum(m.ects for m in self.planned)

    @property
    def missing_credits(self) -> float:
        return sum(m.ects for m in self.missing)


def load_curriculum(path: str | Path | None = None) -> list[CurriculumModule]:
    text = Path(path or DEFAULT_CURRICULUM).read_text(encoding="utf-8")
    # Kommentarzeilen erlauben, damit die Quelle in der Datei stehen kann.
    nutzbar = "\n".join(z for z in text.splitlines() if not z.lstrip().startswith("#"))
    module = []
    for row in csv.DictReader(io.StringIO(nutzbar), delimiter=";"):
        if not (row.get("Nummer") or "").strip():
            continue
        module.append(
            CurriculumModule(
                code=row["Nummer"].strip(),
                name=(row.get("Modulbezeichnung") or "").strip(),
                area=(row.get("Bereich") or "").strip(),
                semester=int(row["Semester"]) if (row.get("Semester") or "").strip() else 0,
                sws=(row.get("SWS") or "").strip(),
                ects=float(row["Credits"]) if (row.get("Credits") or "").strip() else 0.0,
                exam_form=(row.get("Pruefungsart") or "").strip(),
                duration=(row.get("Dauer") or "").strip(),
                language=(row.get("Sprache") or "").strip(),
                foundation=(row.get("Grundlagenpruefung") or "").strip().lower()
                in ("ja", "yes", "true", "1"),
            )
        )
    return module


def _codes_in_plan(options: list[CourseOption]) -> dict[str, str]:
    """Modulkennungen im Plan, samt einem Beispieltitel je Kennung."""
    gefunden: dict[str, str] = {}
    for option in options:
        if option.module:
            gefunden.setdefault(option.module, option.title)
    return gefunden


def _gleich(a: str, b: str) -> bool:
    """WI001059_E und WI001059 sind dasselbe Modul."""
    return a == b or a.split("_")[0] == b.split("_")[0]


def check_plan(
    options: list[CourseOption], curriculum: list[CurriculumModule], semester: int = 1
) -> PlanCheck:
    im_plan = _codes_in_plan(options)
    des_semesters = [m for m in curriculum if m.semester == semester]

    geplant = [m for m in des_semesters if any(_gleich(m.code, c) for c in im_plan)]
    fehlend = [m for m in des_semesters if m not in geplant]
    unbekannt = [
        f"{code} ({titel})"
        for code, titel in im_plan.items()
        if not any(_gleich(m.code, code) for m in curriculum)
    ]

    grundlagen = [m for m in curriculum if m.foundation]
    return PlanCheck(
        semester=semester,
        planned=geplant,
        missing=fehlend,
        unlisted=sorted(unbekannt),
        foundation_planned=sum(
            m.ects for m in grundlagen if any(_gleich(m.code, c) for c in im_plan)
        ),
        foundation_total=sum(m.ects for m in grundlagen),
    )
