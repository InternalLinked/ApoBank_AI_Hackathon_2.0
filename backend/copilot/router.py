"""HTTP-Endpunkte des KI-Agenten (FastAPI-Router, wird in backend/copilot/app.py an die Team-App gehängt).

POST /api/copilot/chat                               Nachricht senden → Antwort + Ergebnisse (Tabellen, Akte, Entwürfe)
POST /api/copilot/entwuerfe/{entwurf_id}/bestaetigen Entwurf speichern – NUR durch den Nutzer (Button in der UI)
POST /api/copilot/entwuerfe/{entwurf_id}/verwerfen   Entwurf verwerfen
POST /api/copilot/sitzungen                          neue Sitzung (leeres Kurzzeitgedächtnis)
GET  /api/copilot/status                             Modell/Region/Datenquelle (keine Geheimnisse)
"""
from __future__ import annotations

import threading
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .agent import Sitzung
from .einstellungen import lade_einstellungen
from .entwuerfe import bestaetigen
from .llm import get_provider

router = APIRouter(prefix="/api/copilot", tags=["KI-Copilot"])
_SITZUNGEN: dict[str, Sitzung] = {}
_LOCK = threading.Lock()
_PROVIDER: Any = None


def _provider():
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = get_provider(lade_einstellungen())
    return _PROVIDER


def _sitzung(sitzung_id: str | None) -> tuple[str, Sitzung]:
    with _LOCK:
        if sitzung_id and sitzung_id in _SITZUNGEN:
            return sitzung_id, _SITZUNGEN[sitzung_id]
        neue_id = sitzung_id or uuid.uuid4().hex[:12]
        _SITZUNGEN[neue_id] = Sitzung(_provider())
        return neue_id, _SITZUNGEN[neue_id]


class ChatIn(BaseModel):
    nachricht: str = Field(min_length=1, max_length=20_000)
    sitzung_id: str | None = Field(None, description="Leer = neue Sitzung")


class FreigabeIn(BaseModel):
    sitzung_id: str
    nutzer: str = Field("Demo-Nutzer", max_length=100)


def _antwort(sitzung_id: str, s: Sitzung, text: str, ergebnisse: list[dict], fehler: str | None) -> dict[str, Any]:
    aktiv = s.toolbox.kontext.get("aktiver_vermittler")
    return {"sitzung_id": sitzung_id, "antwort": text, "ergebnisse": ergebnisse, "fehler": fehler,
            "aktiver_vermittler": aktiv,
            "offene_entwuerfe": [e for e, w in s.toolbox.kontext["entwuerfe"].items() if not w.get("erledigt")],
            "modell": f"{s.provider.name}/{s.provider.model_id}"}


@router.post("/chat", summary="Chat-Nachricht an den Vermittler-Copiloten")
def chat(body: ChatIn) -> dict[str, Any]:
    sitzung_id, s = _sitzung(body.sitzung_id)
    a = s.frage(body.nachricht)
    return _antwort(sitzung_id, s, a.text, a.ergebnisse, a.fehler)


@router.post("/sitzungen", summary="Neue Chat-Sitzung starten")
def neue_sitzung() -> dict[str, str]:
    sitzung_id, _ = _sitzung(None)
    return {"sitzung_id": sitzung_id}


def _entwurf(sitzung_id: str, entwurf_id: str) -> tuple[Sitzung, dict]:
    s = _SITZUNGEN.get(sitzung_id)
    if s is None or entwurf_id not in s.toolbox.kontext["entwuerfe"]:
        raise HTTPException(404, "Entwurf in dieser Sitzung nicht gefunden")
    return s, s.toolbox.kontext["entwuerfe"][entwurf_id]


@router.post("/entwuerfe/{entwurf_id}/bestaetigen", summary="Entwurf nach Prüfung durch den Nutzer speichern")
def entwurf_bestaetigen(entwurf_id: str, body: FreigabeIn) -> dict[str, Any]:
    s, entwurf = _entwurf(body.sitzung_id, entwurf_id)
    if entwurf.get("verworfen"):
        raise HTTPException(409, "Entwurf wurde bereits verworfen")
    res = bestaetigen(entwurf, nutzer=body.nutzer)
    if res["status"] in ("gespeichert", "bereits gespeichert"):
        entwurf["erledigt"] = True
        s.app_hinweis(f"Entwurf {entwurf_id} wurde vom Nutzer bestätigt und gespeichert ({res['status']}).")
    return res


@router.post("/entwuerfe/{entwurf_id}/verwerfen", summary="Entwurf verwerfen (nichts wird gespeichert)")
def entwurf_verwerfen(entwurf_id: str, body: FreigabeIn) -> dict[str, Any]:
    s, entwurf = _entwurf(body.sitzung_id, entwurf_id)
    if entwurf.get("erledigt"):
        raise HTTPException(409, "Entwurf wurde bereits gespeichert")
    entwurf["verworfen"] = entwurf["erledigt"] = True
    s.app_hinweis(f"Entwurf {entwurf_id} wurde vom Nutzer verworfen; nichts wurde gespeichert.")
    return {"status": "verworfen", "entwurf_id": entwurf_id}


@router.get("/status", summary="Konfiguration des Copiloten (ohne Geheimnisse)")
def status() -> dict[str, Any]:
    e = lade_einstellungen()
    return {"llm_provider": e.llm_provider, "llm_model_id": e.llm_model_id if e.llm_provider == "bedrock" else None,
            "aws_region": e.aws_region if e.llm_provider == "bedrock" else None, "datenquelle": e.datenquelle,
            "aktive_sitzungen": len(_SITZUNGEN)}
