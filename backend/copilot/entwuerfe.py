"""Freigabe von Entwürfen – NUR nach ausdrücklicher Bestätigung durch den Nutzer (Klick in der Oberfläche).

Diese Funktion ist KEIN Werkzeug des Sprachmodells. Sie nutzt die bestehende Logik des Team-Backends:
- Gesprächsnotiz → `backend.main.add_obsidian_eintrag` (Obsidian-Eintrag + Tabelle `obsidian_eintrag`)
- neue Interessen → `backend.main.update_vermittler` (Teilupdate + Hub-Sync)
- neuer Vermittler → `backend.main.create_vermittler` (Validierung, Nummernvergabe, Hub-Anlage)
Idempotent: Die Entwurfs-ID steht in `obsidian_eintrag.quelle` bzw. wird pro Sitzung gemerkt.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException

from .. import db
from .werkzeuge import normalisiere_name

QUELLE_PRAEFIX = "copilot-freigabe:"


def _fmt(wert: float) -> str:
    return f"{wert:,.0f}".replace(",", ".")


def _inhalt_markdown(d: dict, abgleich: list[str]) -> str:
    teile = [d["zusammenfassung"] or "(keine Zusammenfassung)"]
    if d["zielsetzung"]:
        teile.append(f"**Zielsetzung:** {d['zielsetzung']}")
    if d["vereinbarungen"]:
        teile += ["", "### Vereinbarungen", *[f"- {v}" for v in d["vereinbarungen"]]]
    if d["interessen_neu"]:
        teile += ["", f"**Neue Interessen:** {', '.join(d['interessen_neu'])}"]
    if d["zielvorschlaege"]:
        teile += ["", "### Zielvorschläge (NICHT genehmigt)",
                  *[f"- {z['jahr']} · {z['kennzahl']}: {_fmt(z['wert'])}" for z in d["zielvorschlaege"]]]
    if d["meilensteine"]:
        teile += ["", "### Quartalsmeilensteine (Vorschlag)",
                  *[f"- Q{m['quartal']}/{m['jahr']}: {m['beschreibung']}" for m in d["meilensteine"]]]
    erledigt = [m for m in d["massnahmen"] if m["status"] == "erledigt"]
    if erledigt:
        teile += ["", "### Erledigte Maßnahmen", *[f"- [x] {m['beschreibung']}" for m in erledigt]]
    if d["ist_zahlen_genannt"]:
        teile += ["", "### Im Gespräch genannte Zahlen",
                  *[f"- {z['jahr']} · {z['kennzahl']}: {_fmt(z['wert'])}" for z in d["ist_zahlen_genannt"]]]
    if abgleich:
        teile += ["", "### Abgleich mit der Datenbank", *[f"- {a}" for a in abgleich]]
    if d["hinweise_naechstes_gespraech"]:
        teile += ["", f"**Für das nächste Gespräch:** {d['hinweise_naechstes_gespraech']}"]
    if d["wiedervorlage_am"]:
        teile += [f"**Wiedervorlage:** {d['wiedervorlage_am']}"]
    if d["unsicherheiten"]:
        teile += ["", "### Offene Punkte der Analyse", *[f"- {u}" for u in d["unsicherheiten"]]]
    teile += ["", "_Erfasst mit dem KI-Copiloten, vom Nutzer geprüft und bestätigt._"]
    return "\n".join(teile)


def bestaetigen(entwurf: dict, nutzer: str = "Demo-Nutzer") -> dict[str, Any]:
    from .. import main as team_api  # Team-Endpunkte als Funktionen wiederverwenden
    from ..schemas import EintragIn, MassnahmeIn, VermittlerCreate, VermittlerUpdate, KontaktIn

    conn = db.connect()
    try:
        if entwurf["typ"] == "gespraechsnotiz":
            quelle = QUELLE_PRAEFIX + entwurf["entwurf_id"]
            if conn.execute("SELECT 1 FROM obsidian_eintrag WHERE quelle = ?", (quelle,)).fetchone():
                return {"status": "bereits gespeichert", "entwurf_id": entwurf["entwurf_id"]}
            d, nr = entwurf["daten"], entwurf["vermittler_nr"]
            massnahmen = [MassnahmeIn(beschreibung=m["beschreibung"] + (" (geplant)" if m["status"] == "geplant" else ""),
                                      verantwortlich=m["verantwortlich"],
                                      faellig_am=date.fromisoformat(m["frist"]) if m["frist"] else None)
                          for m in d["massnahmen"] if m["status"] != "erledigt"]
            eintrag = EintragIn(typ="gespraech", titel=(d["anlass"] or "Gespräch")[:200], inhalt=_inhalt_markdown(d, entwurf.get("abgleich", [])),
                                datum=date.fromisoformat(d["datum"]) if d["datum"] else None, teilnehmer=d["teilnehmer"],
                                massnahmen=massnahmen, tags=["copilot", *d["interessen_neu"]], autor=nutzer, quelle=quelle)
            res = team_api.add_obsidian_eintrag(nr, eintrag, conn)
            neue = []
            if d["interessen_neu"]:
                v = db.get_vermittler_full(conn, nr)
                bekannt = {normalisiere_name(i) for i in v["interessen"]}
                neue = [i for i in d["interessen_neu"] if normalisiere_name(i) not in bekannt]
                if neue:
                    team_api.update_vermittler(nr, VermittlerUpdate(interessen=v["interessen"] + neue), conn)
            conn.commit()
            return {"status": "gespeichert", "entwurf_id": entwurf["entwurf_id"], "vermittler_nr": nr,
                    "datei": res["datei"], "obsidian_uri": res["uri"], "massnahmen": len(massnahmen),
                    "neue_interessen": neue}
        if entwurf["typ"] == "vermittler":
            if entwurf.get("gespeichert_als"):
                return {"status": "bereits gespeichert", "vermittler_nr": entwurf["gespeichert_als"]}
            d = dict(entwurf["daten"])
            kontakt = {k: d.pop(k) for k in ("email", "telefon_dienst", "ort") if k in d}
            try:
                v = team_api.create_vermittler(VermittlerCreate(**d, kontakt=KontaktIn(**kontakt) if kontakt else None), conn)
            except HTTPException as exc:
                conn.rollback()
                return {"status": "abgelehnt", "grund": exc.detail}
            conn.commit()
            entwurf["gespeichert_als"] = v["vermittler_nr"]
            return {"status": "gespeichert", "entwurf_id": entwurf["entwurf_id"], "vermittler_nr": v["vermittler_nr"],
                    "obsidian_uri": v["obsidian"]["uri"]}
        raise ValueError(f"Unbekannter Entwurfstyp: {entwurf['typ']}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
