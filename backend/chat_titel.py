"""Titel-Bot: gibt neuen Chats einen kurzen, sprechenden Titel (z. B. "Top-Vermittler Süd 2025").

Eigener, kleiner KI-Aufruf mit dem schnellsten Modell. Er laeuft PARALLEL zur eigentlichen Antwort und macht sie
deshalb nicht langsamer:
  - Start sofort beim Eingang der ersten Nachricht (`starten`),
  - die Antwort wartet danach hoechstens `WARTEN_S` auf den Titel,
  - ist er noch nicht fertig, gilt erst die gekuerzte Frage; der Bot traegt seinen Titel nach (`nachtragen`).
Es geht nur der Text der ersten Frage an das Modell (keine Anhaenge, keine Datenbankinhalte).
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from . import modellwahl
from .config import settings

logger = logging.getLogger("apobank.titel")

STANDARD_TITEL = "Neue Unterhaltung"
MAX_LAENGE = 48
WARTEN_S = 0.5            # so lange darf die Antwort nach ihrer Fertigstellung noch auf den Titel warten
TIMEOUT_S = 10.0

ANWEISUNG = (
    "Du gibst Chats im Vertriebs-Copilot der apoBank einen Titel für die Chatliste. "
    "Antworte NUR mit dem Titel: Deutsch mit Umlauten, 2 bis 5 Wörter, höchstens 40 Zeichen, ohne Anführungszeichen, "
    "ohne Punkt am Ende, keine Emojis. Benenne das Thema, nicht die Frageform "
    "(z. B. 'Top-Vermittler Süd 2025', 'Gespräch mit Dr. Hans Baumann', 'Rückgang Volumen Filiale Köln'). "
    "Namen, Orte, Jahre und Kennzahlen aus der Frage übernehmen. Bei Begrüßung oder Smalltalk: 'Kurzer Austausch'."
)

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chat-titel")


def ersatz(frage: str) -> str:
    """Titel ohne KI: die gekuerzte erste Frage (wie bisher)."""
    text = " ".join(frage.split())
    return text if len(text) <= 60 else text[:59].rstrip() + "…"


def bereinigen(roh: str | None) -> str | None:
    """Modellantwort -> Titel: erste Zeile, ohne Anfuehrungszeichen/Praefix/Schlusspunkt, gekuerzt."""
    if not roh:
        return None
    zeile = next((z.strip() for z in roh.splitlines() if z.strip()), "")
    rand = " \t\"'„“”‚‘’`*#.!?:;,"
    zeile = re.sub(r"^(titel|title)\s*:\s*", "", zeile.strip(rand), flags=re.IGNORECASE).strip(rand)
    zeile = " ".join(zeile.split())
    if not zeile:
        return None
    if len(zeile) > MAX_LAENGE:
        zeile = zeile[:MAX_LAENGE - 1].rsplit(" ", 1)[0].rstrip(" -–,") + "…"
    return zeile


def _ki_titel(frage: str) -> str | None:
    """Ein einzelner, schneller Modellaufruf; Fehler -> None (dann bleibt der Ersatztitel)."""
    from openai import OpenAI

    modell = modellwahl.MODELL_SCHNELL
    extra = {"reasoning": {"effort": "minimal"}} if modellwahl.unterstuetzt_reasoning(modell) else {}
    client = OpenAI(api_key=settings.openai_api_key, timeout=TIMEOUT_S, max_retries=0)
    antwort = client.responses.create(model=modell, instructions=ANWEISUNG, input=frage[:1500],
                                      max_output_tokens=300, store=False, **extra)
    return bereinigen(getattr(antwort, "output_text", None))


def _sicher(frage: str) -> str | None:
    try:
        return _ki_titel(frage)
    except Exception as exc:  # Titel ist Kosmetik: nie die Antwort scheitern lassen
        logger.warning("Titel-Bot fehlgeschlagen (%s): %s", type(exc).__name__, exc)
        return None


def starten(frage: str) -> Future[str | None] | None:
    """Startet den Titel-Bot im Hintergrund; None, wenn keine KI konfiguriert ist."""
    if not settings.openai_api_key or not frage.strip():
        return None
    return _pool.submit(_sicher, frage)


def abholen(future: Future[str | None] | None, warten_s: float = WARTEN_S) -> str | None:
    """Fertigen KI-Titel holen, hoechstens `warten_s` warten."""
    if future is None:
        return None
    try:
        return future.result(timeout=warten_s)
    except Exception:
        return None


def nachtragen(future: Future[str | None], konversation_id: str, ersatz_titel: str) -> None:
    """Kommt der KI-Titel erst nach der Antwort, wird er nachgetragen – nur wenn noch der Ersatztitel gilt."""
    db_uri = Path(settings.db_path).resolve().as_uri() + "?mode=rw"

    def schreiben(titel: str) -> None:
        # Die Anfrage speichert den Ersatztitel erst beim Commit -> kurz wiederholen, bis er da ist
        for _ in range(20):
            try:
                with closing(sqlite3.connect(db_uri, uri=True, timeout=0.25)) as conn:
                    geaendert = conn.execute("UPDATE chat_konversation SET titel = ? WHERE id = ? AND titel = ?",
                                             (titel, konversation_id, ersatz_titel)).rowcount
                    conn.commit()
                if geaendert:
                    return
                # Nach dem Commit kann der Chat bereits geloescht oder sein Titel geaendert sein.
                with closing(sqlite3.connect(db_uri, uri=True, timeout=0.25)) as conn:
                    zeile = conn.execute("SELECT titel FROM chat_konversation WHERE id = ?", (konversation_id,)).fetchone()
                if zeile is None or zeile[0] not in (STANDARD_TITEL, ersatz_titel):
                    return
            except sqlite3.Error as exc:
                logger.warning("Titel konnte nicht nachgetragen werden: %s", exc)
            time.sleep(0.5)

    def fertig(f: Future[str | None]) -> None:
        titel = f.result() if not f.cancelled() and f.exception() is None else None
        if titel and titel != ersatz_titel:
            # eigener Thread: der Callback kann im Anfrage-Thread laufen, der die DB-Sperre noch haelt
            threading.Thread(target=schreiben, args=(titel,), daemon=True, name="chat-titel-nachtrag").start()

    future.add_done_callback(fertig)
