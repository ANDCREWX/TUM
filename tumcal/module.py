"""Modulbeschreibungen aus TUMonline lesen.

Der Katalog der Lehrveranstaltungen sagt, wann etwas stattfindet. Die
Modulbeschreibung sagt, was überhaupt dazugehört - und deckt damit auf,
welche Lehrveranstaltung im eigenen Plan noch fehlt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .catalog import CourseOption
from .model import detect_kind

# Arten, die einander vertreten können: eine Vorlesung mit integrierter
# Übung erfüllt den Vorlesungsteil des Moduls.
KIND_FAMILIES = {
    "VO": {"VO", "VI", "VU"},
    "VI": {"VO", "VI", "VU"},
    "VU": {"VO", "VI", "VU"},
    "UE": {"UE", "TT", "VI", "VU"},
    "TT": {"UE", "TT", "VI", "VU"},
    "SE": {"SE", "PS"},
    "PS": {"SE", "PS"},
    "PR": {"PR", "PT"},
    "PT": {"PR", "PT"},
}

_SEMESTER_MARKER = re.compile(r"^(\d\.|-|SEMESTER|Credits|\d+)$", re.IGNORECASE)
_MODUL_CODE = re.compile(r"\b([A-Z]{2}\d{4,6}(?:_[A-Z])?)\b")
_ZAHL = re.compile(r"\d+")


@dataclass
class ModuleInfo:
    code: str = ""
    name: str = ""
    ects: float = 0.0
    level: str = ""
    language: str = ""
    turnus: str = ""
    responsible: str = ""
    presence_hours: int = 0
    total_hours: int = 0
    lectures: tuple[str, ...] = ()
    exams: tuple[str, ...] = ()

    @property
    def expected(self) -> list[tuple[str, str]]:
        """Die Lehrveranstaltungen des Moduls mit erkannter Art."""
        out = []
        for name in self.lectures:
            kind = detect_kind(name)
            out.append((name, "VO" if kind == "SONSTIGES" else kind))
        return out


def _wert(zeilen: list[str], label: str) -> str:
    """In der Kopierausgabe steht der Wert jeweils in der Folgezeile."""
    for index, zeile in enumerate(zeilen):
        if zeile.strip().rstrip(":") == label and index + 1 < len(zeilen):
            return zeilen[index + 1].strip()
    return ""


def _abschnitt(zeilen: list[str], start: str, ende: str) -> list[str]:
    try:
        von = next(i for i, z in enumerate(zeilen) if z.strip() == start)
    except StopIteration:
        return []
    rest = zeilen[von + 1 :]
    bis = next((i for i, z in enumerate(rest) if z.strip() == ende), len(rest))
    return [z.strip() for z in rest[:bis] if z.strip()]


def parse_modules(text: str) -> list[ModuleInfo]:
    """Zerlegt eine oder mehrere kopierte Modulbeschreibungen."""
    bloecke = re.split(r"^\s*Überblick\s*$", text.replace("\r\n", "\n"), flags=re.MULTILINE)
    module: list[ModuleInfo] = []

    for block in bloecke:
        zeilen = block.split("\n")
        code = _wert(zeilen, "Modulkennung")
        name = _wert(zeilen, "Name")
        if not code and not name:
            continue

        ects_text = _wert(zeilen, "ECTS-Credits")
        ects_match = _ZAHL.search(ects_text)

        # "Lehrveranstaltungen und Prüfungen" enthält zwei Unterlisten.
        lv_roh = _abschnitt(zeilen, "Lehrveranstaltungen", "Prüfungen")
        pruef_roh = _abschnitt(zeilen, "Prüfungen", "Beschreibung")

        def eintraege(roh: list[str]) -> tuple[str, ...]:
            return tuple(
                z for z in roh
                if not _SEMESTER_MARKER.match(z) and z != "Lehrveranstaltungen und Prüfungen"
            )

        praesenz = _ZAHL.search(_wert(zeilen, "Präsenzstunden") or "")
        gesamt = _ZAHL.search(_wert(zeilen, "Gesamtstunden") or "")

        module.append(
            ModuleInfo(
                code=code,
                name=name,
                ects=float(ects_match.group(0)) if ects_match else 0.0,
                level=_wert(zeilen, "Modulniveau"),
                language=_wert(zeilen, "Sprache"),
                turnus=_wert(zeilen, "Turnus"),
                responsible=_wert(zeilen, "Modulverantwortliche*r"),
                presence_hours=int(praesenz.group(0)) if praesenz else 0,
                total_hours=int(gesamt.group(0)) if gesamt else 0,
                lectures=eintraege(lv_roh),
                exams=eintraege(pruef_roh),
            )
        )
    return module


def _passt(option: CourseOption, code: str) -> bool:
    """Modulkennung des Katalogeintrags mit der des Moduls abgleichen."""
    if not option.module:
        # Manche Einträge tragen die Kennung nur im Titel oder in der LV-Nummer.
        treffer = _MODUL_CODE.search(f"{option.title} {option.lv_id}")
        return bool(treffer and treffer.group(1) == code)
    return option.module == code or option.module.split("_")[0] == code.split("_")[0]


def apply_ects(options: list[CourseOption], modules: list[ModuleInfo]) -> list[CourseOption]:
    """Schreibt die ECTS des Moduls an jeden zugehörigen Eintrag.

    Die Punkte gehören zum Modul, nicht zur einzelnen Lehrveranstaltung
    oder Gruppe. Sie hängen deshalb an allen Einträgen des Moduls - wer
    sie summiert, muss je Modul nur einmal zählen (siehe ects_total).
    """
    out: list[CourseOption] = []
    for option in options:
        treffer = next((m for m in modules if m.ects and _passt(option, m.code)), None)
        out.append(replace(option, ects=treffer.ects) if treffer else option)
    return out


def ects_total(options) -> float:
    """Summe über die Module - eine Vorlesung und ihre Übung zählen einmal."""
    je_modul: dict[str, float] = {}
    for option in options:
        if option.ects:
            je_modul[option.module or option.title] = option.ects
    return sum(je_modul.values())


def missing_lectures(
    options: list[CourseOption], modules: list[ModuleInfo]
) -> list[tuple[ModuleInfo, str, str]]:
    """Lehrveranstaltungen, die das Modul nennt, im Katalog aber fehlen."""
    fehlend = []
    for modul in modules:
        vorhanden = {o.kind for o in options if _passt(o, modul.code)}
        for name, kind in modul.expected:
            if not (KIND_FAMILIES.get(kind, {kind}) & vorhanden):
                fehlend.append((modul, name, kind))
    return fehlend
