"""Einstellungen des KI-Agenten (Modell, Region, Datenschutz-Sperre).

Liest Umgebungsvariablen, optional aus einer lokalen `.env` im Repo-Wurzelordner (wird nie committet).
Die Pfade für Datenbank und Vault bleiben in `backend/config.py` (APOBANK_*-Variablen des Teams).

Datenschutz-Sperre: Daten aus der Kundendatei werden nicht an ein Modell außerhalb der EU gesendet,
solange keine ausdrückliche Freigabe gesetzt ist (FREIGABE_KUNDENDATEN_US=ja).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class EinstellungsFehler(RuntimeError):
    """Ungültige oder unzulässige Konfiguration."""


def lade_dotenv(pfad: Path | None = None) -> None:
    """KEY=VALUE-Zeilen übernehmen, ohne gesetzte Umgebungsvariablen zu überschreiben.

    Ohne `pfad`: erst `.env.local` (geheime Schlüssel), dann `.env` – wie in backend/config.py,
    damit ein leeres `OPENAI_API_KEY=` in `.env` den Schlüssel aus `.env.local` nicht verdeckt.
    """
    pfade = [pfad] if pfad else [REPO_ROOT / ".env.local", REPO_ROOT / ".env"]
    for datei in pfade:
        if not datei.is_file():
            continue
        for roh in datei.read_text(encoding="utf-8-sig").splitlines():
            zeile = roh.strip()
            if not zeile or zeile.startswith("#") or "=" not in zeile:
                continue
            key, wert = zeile.split("=", 1)
            os.environ.setdefault(key.strip(), wert.split(" #", 1)[0].strip().strip('"').strip("'"))


def _ja(wert: str | None) -> bool:
    return (wert or "").strip().lower() in {"ja", "yes", "true", "1"}


@dataclass(frozen=True)
class Einstellungen:
    llm_provider: str          # fake | bedrock
    llm_model_id: str
    aws_region: str
    datenquelle: str           # synthetisch | kundendatei
    freigabe_kundendaten_us: bool

    @property
    def region_ist_eu(self) -> bool:
        return self.aws_region.startswith("eu-")


def pruefe(e: Einstellungen) -> None:
    if e.llm_provider not in {"fake", "bedrock"}:
        raise EinstellungsFehler(f"LLM_PROVIDER muss 'fake' oder 'bedrock' sein, nicht '{e.llm_provider}'.")
    if e.datenquelle not in {"synthetisch", "kundendatei"}:
        raise EinstellungsFehler("COPILOT_DATENQUELLE muss 'synthetisch' oder 'kundendatei' sein.")
    if e.llm_provider == "bedrock" and not e.llm_model_id:
        raise EinstellungsFehler("LLM_MODEL_ID fehlt (Bedrock-Modell bzw. Inferenzprofil).")
    if (e.llm_provider == "bedrock" and e.datenquelle == "kundendatei"
            and not e.region_ist_eu and not e.freigabe_kundendaten_us):
        raise EinstellungsFehler(
            f"Gesperrt: Daten aus der Kundendatei würden an ein Modell in '{e.aws_region}' (außerhalb der EU) "
            "gesendet. Ohne ausdrückliche Freigabe (FREIGABE_KUNDENDATEN_US=ja) nur synthetische Daten "
            "verwenden (COPILOT_DATENQUELLE=synthetisch) oder LLM_PROVIDER=fake.")


def lade_einstellungen(dotenv: bool = True) -> Einstellungen:
    if dotenv:
        lade_dotenv()
    e = Einstellungen(
        llm_provider=os.environ.get("LLM_PROVIDER", "fake").strip().lower(),
        llm_model_id=os.environ.get("LLM_MODEL_ID", "").strip(),
        aws_region=os.environ.get("AWS_REGION", "us-west-2").strip(),
        # vorsichtiger Standard: Ohne Angabe gelten die Daten als Kundendaten
        datenquelle=os.environ.get("COPILOT_DATENQUELLE", "kundendatei").strip().lower(),
        freigabe_kundendaten_us=_ja(os.environ.get("FREIGABE_KUNDENDATEN_US")),
    )
    pruefe(e)
    return e
