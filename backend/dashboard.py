"""Berater-Dashboard (POC): Kennzahlen und Diagramme nur ueber die eigenen Vermittler eines Betreuers.

Der Betreuer ist fest eingestellt (`settings.betreuerkonto_id`, Standard: Hartmann) – kein Login.
Die Diagramme haben dasselbe Format wie die Analysen im Chat (`analysen.ausfuehren`), damit das Frontend
sie mit denselben Bausteinen zeichnet. Das Betreuerkonto steckt als `feste_werte["konto"]` im SQL und ist
nicht waehlbar – jede Abfrage ist dadurch auf die eigenen Vermittler begrenzt.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

from . import analysen

Conn = sqlite3.Connection

_KENNZAHL = {"name": "kennzahl", "label": "Kennzahl", "standard": "volumen", "optionen": [
    {"wert": "volumen", "label": "Kreditvolumen", "einheit": "eur"},
    {"wert": "anzahl", "label": "Anzahl Darlehen", "einheit": "anzahl"}]}
_WERT = "CASE :kennzahl WHEN 'anzahl' THEN g.anzahl_darlehen ELSE g.volumen_eur END"
_NAME = "TRIM(COALESCE(v.vorname || ' ', '') || v.name)"
_EIGENE = "v.mitarbeiter_id = :konto"


def _jahre(conn: Conn) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT jahr FROM geschaeftszahlen WHERE sparte = 'gesamt' ORDER BY jahr DESC").fetchall()]


def _standard_jahr(jahre: list[int]) -> int:
    """2025 ist das letzte abgeschlossene Jahr (2026 ist unterjaehrig)."""
    return 2025 if 2025 in jahre else jahre[0]


def _jahr_param(jahre: list[int]) -> dict[str, Any]:
    return {"name": "jahr", "label": "Jahr", "standard": str(_standard_jahr(jahre)),
            "optionen": [{"wert": str(j), "label": str(j), "einheit": ""} for j in jahre[:analysen.MAX_OPTIONEN]]}


def _verlauf(jahre: list[int]) -> dict[str, Any]:
    return {
        "titel_vorlage": "{kennzahl} je Jahr", "titel": "Entwicklung meines Portfolios",
        "sql": f"SELECT g.jahr AS Jahr, SUM({_WERT}) AS Wert FROM v_vermittler v "
               f"JOIN geschaeftszahlen g ON g.vermittler_nr = v.vermittler_nr "
               f"WHERE g.sparte = 'gesamt' AND {_EIGENE} GROUP BY g.jahr ORDER BY g.jahr",
        "diagramm_basis": {"typ": "linie", "x": "Jahr", "y": "Wert", "einheit": "eur"},
        "parameter": [_KENNZAHL],
    }


def _top(jahre: list[int]) -> dict[str, Any]:
    return {
        "titel_vorlage": "Meine Top {limit} nach {kennzahl} {jahr}", "titel": "Meine Top-Vermittler",
        "sql": f"SELECT v.vermittler_nr AS vermittler_nr, {_NAME} AS Vermittler, {_WERT} AS Wert "
               f"FROM v_vermittler v JOIN geschaeftszahlen g ON g.vermittler_nr = v.vermittler_nr "
               f"WHERE g.sparte = 'gesamt' AND g.jahr = :jahr AND {_EIGENE} AND {_WERT} IS NOT NULL "
               f"ORDER BY {_WERT} DESC, v.vermittler_nr LIMIT :limit",
        "diagramm_basis": {"typ": "balken", "x": "Vermittler", "y": "Wert", "einheit": "eur"},
        "parameter": [_jahr_param(jahre), {"name": "limit", "label": "Anzahl", "standard": "10", "optionen": [
            {"wert": str(n), "label": str(n), "einheit": ""} for n in (5, 10, 25)]}, _KENNZAHL],
    }


def _karte(jahre: list[int]) -> dict[str, Any]:
    return {
        "titel_vorlage": "{kennzahl} {jahr} nach Standort", "titel": "Meine Vermittler auf der Karte",
        "sql": f"WITH basis AS (SELECT v.ort, v.plz, {_NAME} AS name, {_WERT} AS wert "
               f"FROM v_vermittler v JOIN geschaeftszahlen g ON g.vermittler_nr = v.vermittler_nr "
               f"WHERE g.sparte = 'gesamt' AND g.jahr = :jahr AND {_EIGENE}) "
               "SELECT b.ort AS Ort, ROUND(AVG(p.lat), 4) AS lat, ROUND(AVG(p.lon), 4) AS lon, "
               "COUNT(*) AS \"Anzahl Vermittler\", GROUP_CONCAT(b.name, ', ') AS Vermittler, "
               "COALESCE(SUM(b.wert), 0) AS Wert "
               "FROM basis b JOIN plz_koordinaten p ON p.plz = b.plz GROUP BY b.ort ORDER BY Wert DESC",
        "diagramm_basis": {"typ": "karte", "x": "Ort", "y": "Wert", "einheit": "eur"},
        "parameter": [_jahr_param(jahre), _KENNZAHL],
    }


def _status(jahre: list[int]) -> dict[str, Any]:
    return {
        "titel_vorlage": "{kennzahl} {jahr} nach Partnerstatus", "titel": "Nach Status Vertriebspartner",
        "sql": f"SELECT COALESCE(v.status_vertriebspartner, 'ohne Angabe') AS Status, "
               f"COUNT(*) AS \"Anzahl Vermittler\", COALESCE(SUM({_WERT}), 0) AS Wert "
               f"FROM v_vermittler v LEFT JOIN geschaeftszahlen g ON g.vermittler_nr = v.vermittler_nr "
               f"AND g.sparte = 'gesamt' AND g.jahr = :jahr WHERE {_EIGENE} GROUP BY 1 ORDER BY Wert DESC",
        "diagramm_basis": {"typ": "balken", "x": "Status", "y": "Wert", "einheit": "eur"},
        "parameter": [_jahr_param(jahre), _KENNZAHL],
    }


def _liste(jahre: list[int]) -> dict[str, Any]:
    return {
        "titel_vorlage": "Alle meine Vermittler – {jahr} im Vergleich zum Vorjahr", "titel": "Alle meine Vermittler",
        "sql": f"SELECT v.vermittler_nr AS vermittler_nr, {_NAME} AS Vermittler, v.ort AS Ort, "
               "v.status_vertriebspartner AS Status, "
               "akt.volumen_eur AS \"Volumen\", vor.volumen_eur AS \"Volumen Vorjahr\", "
               "ROUND(100.0 * (akt.volumen_eur - vor.volumen_eur) / NULLIF(vor.volumen_eur, 0), 1) AS \"Veraenderung Prozent\", "
               "akt.anzahl_darlehen AS \"Anzahl Darlehen\" "
               "FROM v_vermittler v "
               "LEFT JOIN geschaeftszahlen akt ON akt.vermittler_nr = v.vermittler_nr AND akt.sparte = 'gesamt' AND akt.jahr = :jahr "
               "LEFT JOIN geschaeftszahlen vor ON vor.vermittler_nr = v.vermittler_nr AND vor.sparte = 'gesamt' AND vor.jahr = :jahr - 1 "
               f"WHERE {_EIGENE} ORDER BY akt.volumen_eur DESC NULLS LAST, v.name",
        "diagramm_basis": {"typ": "tabelle", "x": "Vermittler", "y": "Volumen", "einheit": "eur"},
        "parameter": [_jahr_param([j for j in jahre if j - 1 in jahre] or jahre)],
    }


# Reihenfolge = Reihenfolge auf dem Dashboard
DIAGRAMME: dict[str, Callable[[list[int]], dict[str, Any]]] = {
    "verlauf": _verlauf, "top": _top, "karte": _karte, "status": _status, "liste": _liste,
}


def basis(conn: Conn, schluessel: str, konto: str) -> dict[str, Any]:
    """Unberechnete Analyse eines Dashboard-Diagramms (KeyError bei unbekanntem Schluessel)."""
    baue = DIAGRAMME[schluessel]
    jahre = _jahre(conn)
    analyse = baue(jahre)
    analyse["parameter"] = analysen.parameter_pruefen(analyse["parameter"], analyse["sql"])
    return {"id": f"dashboard-{schluessel}", **analyse, "feste_werte": {"konto": konto}}


def _kennzahlen(conn: Conn, konto: str, jahre: list[int]) -> dict[str, Any]:
    jahr = _standard_jahr(jahre)
    zeile = conn.execute(
        "SELECT COUNT(*) AS anzahl, SUM(v.status = 'aktiv') AS aktiv, "
        "SUM(akt.volumen_eur) AS volumen, SUM(vor.volumen_eur) AS volumen_vorjahr, SUM(akt.anzahl_darlehen) AS darlehen "
        "FROM vermittler v "
        "LEFT JOIN geschaeftszahlen akt ON akt.vermittler_nr = v.vermittler_nr AND akt.sparte = 'gesamt' AND akt.jahr = ? "
        "LEFT JOIN geschaeftszahlen vor ON vor.vermittler_nr = v.vermittler_nr AND vor.sparte = 'gesamt' AND vor.jahr = ? "
        "WHERE v.mitarbeiter_id = ?", (jahr, jahr - 1, konto)).fetchone()
    volumen, vorjahr = zeile["volumen"] or 0, zeile["volumen_vorjahr"] or 0
    return {
        "jahr": jahr, "vorjahr": jahr - 1,
        "anzahl_vermittler": zeile["anzahl"], "aktive_vermittler": zeile["aktiv"] or 0,
        "volumen_eur": volumen, "volumen_vorjahr_eur": vorjahr,
        "veraenderung_prozent": round(100 * (volumen - vorjahr) / vorjahr, 1) if vorjahr else None,
        "anzahl_darlehen": zeile["darlehen"] or 0,
    }


def dashboard(conn: Conn, konto: str) -> dict[str, Any] | None:
    """Alles fuer die Dashboard-Ansicht; None, wenn es das Betreuerkonto nicht gibt."""
    berater = conn.execute(
        "SELECT b.mitarbeiter_id, b.kuerzel, b.name, f.filial_nr, f.name AS filiale, f.marktgebiet "
        "FROM betreuer b LEFT JOIN filiale f ON f.filial_nr = b.filial_nr WHERE b.mitarbeiter_id = ?", (konto,)).fetchone()
    if berater is None:
        return None
    jahre = _jahre(conn)
    diagramme = [analysen.ausfuehren(basis(conn, schluessel, konto)) for schluessel in DIAGRAMME] if jahre else []
    return {
        "berater": dict(berater),
        "kennzahlen": _kennzahlen(conn, konto, jahre) if jahre else None,
        "analysen": diagramme,
    }
