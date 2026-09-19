"""Holt den persönlichen ICS-Export aus TUMonline (Token-Link, kein Passwort)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "tumcal" / "config.json"
ENV_VAR = "TUM_ICAL_URL"
USER_AGENT = "tumcal/1.0 (persoenlicher Kalender-Export)"


class FetchError(RuntimeError):
    pass


def resolve_url(explicit: str | None = None) -> str:
    """Reihenfolge: CLI-Argument, Umgebungsvariable, Konfigdatei."""
    if explicit:
        return explicit.strip()

    from_env = os.environ.get(ENV_VAR, "").strip()
    if from_env:
        return from_env

    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FetchError(f"{CONFIG_PATH} ist kein gültiges JSON: {exc}") from exc
        url = (data.get("ical_url") or "").strip()
        if url:
            return url

    raise FetchError(
        "Keine iCal-URL gefunden. Entweder --url übergeben, "
        f"{ENV_VAR} setzen oder 'python -m tumcal config --url ...' ausführen."
    )


def save_url(url: str) -> Path:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({"ical_url": url.strip()}, indent=2) + "\n", encoding="utf-8"
    )
    # Der Token im Link ist ein Geheimnis - Datei nur für den Besitzer lesbar.
    CONFIG_PATH.chmod(0o600)
    return CONFIG_PATH


def fetch_ics(url: str, timeout: int = 60) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(
            f"TUMonline antwortete mit HTTP {exc.code}. "
            "Ist der Token-Link noch gültig (Kalender in TUMonline veröffentlicht)?"
        ) from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Verbindung zu TUMonline fehlgeschlagen: {exc.reason}") from exc

    text = payload.decode("utf-8-sig", errors="replace")
    if "BEGIN:VCALENDAR" not in text:
        raise FetchError(
            "Antwort enthält kein iCalendar-Dokument. Vermutlich wurde eine "
            "Login-Seite ausgeliefert - bitte den Token-Link neu erzeugen."
        )
    return text


def read_ics(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8-sig", errors="replace")
