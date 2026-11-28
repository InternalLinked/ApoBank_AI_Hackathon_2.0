"""Analysen mit Auswahlfeldern (Dropdowns) ueber dem Diagramm – ohne neue KI-Frage neu berechnen.

Die KI schreibt ihr SQL mit benannten Platzhaltern (`:jahr`, `:limit`, `:kennzahl`) und legt fest, welche
Werte waehlbar sind. Waehlt der Nutzer etwas anderes, fuehrt das Backend dasselbe SQL read-only mit den
neuen Werten aus. Sicher, weil
  - nur vorher festgelegte Werte erlaubt sind (alles andere -> Fehler),
  - Werte immer als Bind-Parameter uebergeben werden (nie in den SQL-Text eingesetzt),
  - die Ausfuehrung ueber db.run_readonly_sql laeuft (nur SELECT, Timeout).
"""
from __future__ import annotations

import copy
import re
from typing import Any

from . import db

MAX_ZEILEN = 200
MAX_PARAMETER = 4
MAX_OPTIONEN = 12
EINHEITEN = {"eur", "anzahl", "prozent", "keine"}
_NAME = re.compile(r"^[a-z][a-z_]{0,19}$")
_KENNUNG = re.compile(r"(^|_)(nr|id)$", re.IGNORECASE)


class AnalyseFehler(ValueError):
    pass


def _wert(roh: Any) -> str:
    return str(roh).strip()[:40]


def parameter_pruefen(roh: list[dict[str, Any]] | None, sql: str) -> list[dict[str, Any]]:
    """Bereinigt die Dropdown-Vorgaben der KI. Unbrauchbares wird verworfen statt eine Fehlbedienung anzubieten."""
    ergebnis: list[dict[str, Any]] = []
    for p in (roh or [])[:MAX_PARAMETER]:
        name = str(p.get("name") or "").strip().lower()
        if not _NAME.match(name) or not re.search(rf":{name}\b", sql) or any(e["name"] == name for e in ergebnis):
            continue  # Platzhalter kommt im SQL nicht vor -> Dropdown waere wirkungslos
        optionen = []
        for o in (p.get("optionen") or [])[:MAX_OPTIONEN]:
            wert = _wert(o.get("wert"))
            if not wert or any(x["wert"] == wert for x in optionen):
                continue
            einheit = str(o.get("einheit") or "").strip()
            optionen.append({"wert": wert, "label": str(o.get("label") or wert).strip()[:30],
                             "einheit": einheit if einheit in EINHEITEN else ""})
        if len(optionen) < 2:
            continue  # eine einzige Option ist keine Auswahl
        standard = _wert(p.get("standard"))
        if standard not in {o["wert"] for o in optionen}:
            standard = optionen[0]["wert"]
        ergebnis.append({"name": name, "label": str(p.get("label") or name).strip()[:30],
                         "standard": standard, "optionen": optionen})
    return ergebnis


def _bind(wert: str) -> int | str:
    """Ganzzahlen als int binden (LIMIT, Jahre), alles andere als Text."""
    return int(wert) if re.fullmatch(r"-?\d{1,9}", wert) else wert


def _titel(vorlage: str, parameter: list[dict[str, Any]], werte: dict[str, str]) -> str:
    """'Top {limit} Vermittler {jahr}' -> 'Top 10 Vermittler 2025' (Labels der gewaehlten Optionen)."""
    labels = {p["name"]: next(o["label"] for o in p["optionen"] if o["wert"] == werte[p["name"]]) for p in parameter}
    return re.sub(r"\{([a-z_]+)\}", lambda m: labels.get(m.group(1), m.group(0)), vorlage)[:120]


def ausfuehren(analyse: dict[str, Any], werte: dict[str, str] | None = None) -> dict[str, Any]:
    """Fuehrt das SQL einer Analyse mit den gewaehlten Werten aus und liefert die aktualisierte Analyse.

    Wirft AnalyseFehler bei unerlaubten Werten und db.SqlFehler bei SQL-Fehlern.
    """
    parameter = analyse.get("parameter") or []
    gewaehlt: dict[str, str] = {}
    for p in parameter:
        wert = _wert((werte or {}).get(p["name"], (analyse.get("werte") or {}).get(p["name"], p["standard"])))
        if wert not in {o["wert"] for o in p["optionen"]}:
            raise AnalyseFehler(f"Wert '{wert}' ist fuer '{p['label']}' nicht erlaubt.")
        gewaehlt[p["name"]] = wert
    unbekannt = set(werte or {}) - set(gewaehlt)
    if unbekannt:
        raise AnalyseFehler(f"Unbekannte Auswahl: {', '.join(sorted(unbekannt))}")

    # feste_werte: vom Backend gesetzte Bind-Parameter (z. B. Betreuerkonto), vom Nutzer nicht waehlbar
    binds = {**(analyse.get("feste_werte") or {}), **{k: _bind(v) for k, v in gewaehlt.items()}}
    ergebnis = db.run_readonly_sql(analyse["sql"], binds or None, max_rows=MAX_ZEILEN)
    neu = copy.deepcopy(analyse)
    neu.update(spalten=ergebnis["spalten"], zeilen=ergebnis["zeilen"], anzahl=ergebnis["anzahl"],
               abgeschnitten=ergebnis["abgeschnitten"], werte=gewaehlt)
    diagramm = dict(neu.get("diagramm_basis") or neu.get("diagramm") or {})
    for p in parameter:  # z. B. Kennzahl "Anzahl Darlehen" -> Einheit "anzahl" statt "eur"
        einheit = next(o["einheit"] for o in p["optionen"] if o["wert"] == gewaehlt[p["name"]])
        if einheit:
            diagramm["einheit"] = einheit
    spalten = ergebnis["spalten"]
    if diagramm.get("typ") != "tabelle" and spalten:
        if diagramm.get("x") not in spalten:  # Beschriftung: erste Spalte, die keine Kennung ist (Name statt Nummer)
            diagramm["x"] = next((s for s in spalten if not _KENNUNG.search(s)), spalten[0])
        if diagramm.get("y") not in spalten:
            diagramm["y"] = spalten[-1]
    neu["diagramm"] = diagramm
    if parameter:
        neu["titel"] = _titel(neu.get("titel_vorlage") or neu.get("titel") or "Analyse", parameter, gewaehlt)
    return neu
