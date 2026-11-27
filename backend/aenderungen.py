"""Aenderungsvorschlaege der KI: erst anzeigen, dann nach Klick ausfuehren.

Ablauf:
1. Die KI ruft `aenderung_vorschlagen` auf. `vorschlag_bauen` prueft jedes Feld gegen eine Whitelist,
   liest den AKTUELLEN Wert (alt) und baut eine Liste alt -> neu. Nichts wird geschrieben.
2. `main.py` speichert den Vorschlag in `chat_aenderung` (gebunden an Chat + Browser-ID).
3. Die Oberflaeche zeigt ihn im Tab "Aenderungen". Erst `POST /api/chat/aenderungen/{id}/bestaetigen`
   ruft `ausfuehren` auf: Konfliktpruefung (hat sich ein Wert seit dem Vorschlag geaendert?), dann
   alle Aenderungen in einer Transaktion, Hub-Sync und eine Protokollnotiz im Obsidian-Gehirn.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from . import db, obsidian

STAMMDATEN_FELDER: dict[str, str] = {
    "anrede": "Anrede", "titel": "Titel", "sonstiger_titel": "Sonstiger Titel",
    "vorname": "Vorname", "name": "Nachname", "geburtstag": "Geburtstag",
    "firma_filiale": "Firma", "firma_holding": "Holding", "vermittlertyp": "Vermittlertyp",
    "status": "Status", "abrechnungskreis": "Abrechnungskreis",
    "status_vertriebspartner": "Status Vertriebspartner", "interessen": "Interessen/Hobbys",
    "betreuung_seit": "Betreuung seit", "betreuung_bis": "Betreuung bis",
}
KONTAKT_FELDER: dict[str, str] = {
    "email": "E-Mail", "telefon_dienst": "Telefon (dienstlich)", "handy_dienst": "Handy (dienstlich)",
    "telefon_privat": "Telefon (privat)", "strasse": "Straße", "plz": "PLZ", "ort": "Ort",
    "adressentyp": "Adressentyp",
}
ZAHLEN_FELDER: dict[str, str] = {"volumen_eur": "Kreditvolumen (EUR)", "anzahl_darlehen": "Anzahl Darlehen"}
PFLICHTFELDER = {"vorname", "name", "status"}
DATUMS_FELDER = {"geburtstag", "betreuung_seit", "betreuung_bis"}
STATUS_WERTE = {"aktiv", "inaktiv", "gesperrt"}
ARTEN = ("stammdaten", "kontakt", "geschaeftszahlen", "profil_fakt_aendern", "profil_fakt_loeschen")

ART_LABEL = {
    "stammdaten": "Stammdaten", "kontakt": "Kontakt", "geschaeftszahlen": "Geschäftszahlen",
    "profil_fakt_aendern": "Persönliches Profil", "profil_fakt_loeschen": "Persönliches Profil",
}


class AenderungsKonflikt(Exception):
    def __init__(self, konflikte: list[dict[str, Any]]):
        super().__init__("Werte haben sich seit dem Vorschlag geaendert")
        self.konflikte = konflikte


def _leer(wert: Any) -> Any:
    return None if wert is None or (isinstance(wert, str) and not wert.strip()) else wert


def _als_text(wert: Any) -> str | None:
    wert = _leer(wert)
    return None if wert is None else str(wert).strip()


def _zahl(wert: str) -> int:
    """'1.250.000 €' / '1250000' / '1,25 Mio' -> int (ganze Euro bzw. Stueck)."""
    roh = str(wert).lower().replace("€", "").replace("eur", "").replace(" ", "").strip()
    faktor = 1
    for suffix, f in (("mio.", 1_000_000), ("mio", 1_000_000), ("tsd.", 1_000), ("tsd", 1_000)):
        if roh.endswith(suffix):
            roh, faktor = roh[: -len(suffix)], f
            break
    if faktor > 1:
        roh = roh.replace(".", "").replace(",", ".") if roh.count(",") == 1 else roh.replace(",", "")
        return round(float(roh) * faktor)
    roh = roh.replace(".", "").replace(",", "")
    if not roh.isdigit():
        raise ValueError(f"'{wert}' ist keine ganze Zahl")
    return int(roh)


def _fakt_finden(nr: int, schluessel: str) -> dict[str, Any] | None:
    """Fakt per ID oder per (Teil-)Text finden – das Modell kennt oft nur den Text."""
    fakten = obsidian.read_profil(nr)["fakten"]
    schluessel = schluessel.strip()
    exakt = [f for f in fakten if f["id"] == schluessel or f["text"].lower() == schluessel.lower()]
    if exakt:
        return exakt[0]
    teil = [f for f in fakten if schluessel and schluessel.lower() in f["text"].lower()]
    return teil[0] if len(teil) == 1 else None


def _aktuell(conn: sqlite3.Connection, v: dict[str, Any], item: dict[str, Any]) -> Any:
    art, feld = item["art"], item.get("feld")
    if art == "stammdaten":
        wert = v.get(feld)
        return ", ".join(wert) if isinstance(wert, list) else _als_text(wert)
    if art == "kontakt":
        return _als_text((v.get("kontakt") or {}).get(feld))
    if art == "geschaeftszahlen":
        row = conn.execute(f"SELECT {feld} FROM geschaeftszahlen WHERE vermittler_nr = ? AND jahr = ? "
                           "AND sparte = 'gesamt'", (v["vermittler_nr"], item["jahr"])).fetchone()
        return None if row is None else int(row[0])
    fakt = next((f for f in obsidian.read_profil(v["vermittler_nr"])["fakten"] if f["id"] == item["fakt_id"]), None)
    return None if fakt is None else fakt["text"]


def vorschlag_bauen(conn: sqlite3.Connection, nr: int, begruendung: str,
                    roh: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Prueft die Wuensche des Modells. Liefert (Antwort ans Modell, Vorschlag oder None)."""
    v = db.get_vermittler_full(conn, nr)
    if v is None:
        return {"fehler": f"Vermittler {nr} nicht gefunden – kein Vorschlag erstellt."}, None
    items: list[dict[str, Any]] = []
    fehler: list[str] = []
    for eintrag in roh:
        art = str(eintrag.get("art", ""))
        feld = str(eintrag.get("feld") or "").strip()
        wert = eintrag.get("wert")
        try:
            if art == "stammdaten":
                if feld not in STAMMDATEN_FELDER:
                    raise ValueError(f"Feld '{feld}' ist nicht aenderbar (erlaubt: {', '.join(STAMMDATEN_FELDER)})")
                neu = _als_text(wert)
                if feld == "interessen" and neu:
                    neu = ", ".join(t.strip() for t in neu.split(",") if t.strip())
                if feld == "status" and neu not in STATUS_WERTE:
                    raise ValueError(f"Status muss {', '.join(sorted(STATUS_WERTE))} sein")
                if feld in PFLICHTFELDER and not neu:
                    raise ValueError(f"{STAMMDATEN_FELDER[feld]} darf nicht leer sein")
                if feld in DATUMS_FELDER and neu:
                    try:
                        neu = date.fromisoformat(neu).isoformat()
                    except ValueError as exc:
                        raise ValueError(f"{STAMMDATEN_FELDER[feld]} muss ein Datum im Format JJJJ-MM-TT sein") from exc
                item = {"art": art, "feld": feld, "label": STAMMDATEN_FELDER[feld], "neu": neu}
            elif art == "kontakt":
                if feld not in KONTAKT_FELDER:
                    raise ValueError(f"Kontaktfeld '{feld}' unbekannt (erlaubt: {', '.join(KONTAKT_FELDER)})")
                item = {"art": art, "feld": feld, "label": KONTAKT_FELDER[feld], "neu": _als_text(wert)}
            elif art == "geschaeftszahlen":
                jahr = int(eintrag.get("jahr") or 0)
                if feld not in ZAHLEN_FELDER or not 1990 <= jahr <= 2100:
                    raise ValueError("Geschaeftszahlen brauchen feld volumen_eur|anzahl_darlehen und ein gueltiges jahr")
                neu_zahl = _zahl(str(wert))
                if neu_zahl < 0:
                    raise ValueError("Werte duerfen nicht negativ sein")
                item = {"art": art, "feld": feld, "jahr": jahr, "label": f"{ZAHLEN_FELDER[feld]} {jahr}", "neu": neu_zahl}
            elif art in ("profil_fakt_aendern", "profil_fakt_loeschen"):
                fakt = _fakt_finden(nr, str(eintrag.get("fakt_id") or ""))
                if fakt is None:
                    raise ValueError(f"Profil-Fakt '{eintrag.get('fakt_id')}' nicht eindeutig gefunden")
                neu = None if art == "profil_fakt_loeschen" else _als_text(wert)
                if art == "profil_fakt_aendern" and not neu:
                    raise ValueError("Neuer Text fuer den Profil-Fakt fehlt (zum Entfernen profil_fakt_loeschen nutzen)")
                item = {"art": art, "fakt_id": fakt["id"], "kategorie": fakt["kategorie"],
                        "label": fakt["kategorie_label"], "neu": neu}
            else:
                raise ValueError(f"Unbekannte Art '{art}' (erlaubt: {', '.join(ARTEN)})")
        except (TypeError, ValueError) as exc:
            fehler.append(str(exc))
            continue
        item["alt"] = _aktuell(conn, v, item)
        item["bereich"] = ART_LABEL[art]
        if item["alt"] == item["neu"]:
            fehler.append(f"{item['label']}: ist bereits '{item['neu']}' – nichts zu aendern")
            continue
        items.append(item)

    if not items:
        return {"fehler": "Kein Vorschlag erstellt.", "details": fehler}, None
    vorschlag = {
        "vermittler_nr": nr,
        "vermittler": v["anzeigename"],
        "begruendung": begruendung.strip()[:300],
        "aenderungen": items,
    }
    an_modell = {
        "status": "Vorschlag erstellt – NICHT gespeichert. Der Nutzer muss ihn im Tab 'Aenderungen' bestaetigen.",
        "aenderungen": [{"bereich": i["bereich"], "feld": i["label"], "alt": i["alt"], "neu": i["neu"]} for i in items],
        "nicht_uebernommen": fehler,
    }
    return an_modell, vorschlag


def ausfuehren(conn: sqlite3.Connection, vorschlag: dict[str, Any]) -> dict[str, Any]:
    """Fuehrt einen bestaetigten Vorschlag aus. Wirft AenderungsKonflikt, wenn sich Werte geaendert haben."""
    nr = int(vorschlag["vermittler_nr"])
    v = db.get_vermittler_full(conn, nr)
    if v is None:
        raise AenderungsKonflikt([{"label": "Vermittler", "erwartet": nr, "aktuell": "gelöscht"}])
    items = vorschlag["aenderungen"]
    konflikte = [
        {"label": i["label"], "erwartet": i["alt"], "aktuell": aktuell}
        for i in items if (aktuell := _aktuell(conn, v, i)) != i["alt"]
    ]
    if konflikte:
        raise AenderungsKonflikt(konflikte)

    stammdaten = {i["feld"]: i["neu"] for i in items if i["art"] == "stammdaten"}
    if stammdaten:  # Spaltennamen nur aus der Whitelist (siehe vorschlag_bauen)
        assert set(stammdaten) <= set(STAMMDATEN_FELDER)
        sets = ", ".join(f"{k} = ?" for k in stammdaten)
        conn.execute(f"UPDATE vermittler SET {sets}, geaendert_am = datetime('now') WHERE vermittler_nr = ?",
                     [*stammdaten.values(), nr])
    kontakt = {i["feld"]: i["neu"] for i in items if i["art"] == "kontakt"}
    if kontakt:
        assert set(kontakt) <= set(KONTAKT_FELDER)
        cols = list(kontakt)
        conn.execute(
            f"INSERT INTO kontakt (vermittler_nr, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))}) "
            f"ON CONFLICT(vermittler_nr) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in cols)}",
            [nr, *kontakt.values()])
    for i in (i for i in items if i["art"] == "geschaeftszahlen"):
        assert i["feld"] in ZAHLEN_FELDER
        conn.execute(
            f"INSERT INTO geschaeftszahlen (vermittler_nr, jahr, sparte, {i['feld']}) VALUES (?, ?, 'gesamt', ?) "
            f"ON CONFLICT(vermittler_nr, jahr, sparte) DO UPDATE SET {i['feld']} = excluded.{i['feld']}",
            (nr, i["jahr"], i["neu"]))
    if stammdaten or kontakt:
        conn.execute("UPDATE vermittler SET geaendert_am = datetime('now') WHERE vermittler_nr = ?", (nr,))

    # Dateien erst nach den DB-Aenderungen (bei einem Fehler rollt get_conn die DB zurueck)
    v_neu = db.get_vermittler_full(conn, nr)
    for i in (i for i in items if i["art"].startswith("profil_fakt")):
        obsidian.delete_profil_fakt(nr, i["fakt_id"])
        if i["art"] == "profil_fakt_aendern":
            obsidian.add_profil_fakt(v_neu, i["neu"], i["kategorie"])
    obsidian.sync_hub(v_neu)

    def fmt(wert: Any) -> str:
        return "–" if wert in (None, "") else str(wert)

    protokoll = obsidian.add_entry(v_neu, {
        "typ": "notiz",
        "titel": "Änderungen aus dem Chat bestätigt",
        "inhalt": "\n".join(f"- **{i['bereich']} · {i['label']}:** {fmt(i['alt'])} → {fmt(i['neu'])}" for i in items)
                  + (f"\n\nAnlass: {vorschlag['begruendung']}" if vorschlag.get("begruendung") else ""),
        "tags": ["aenderung", "chat"], "autor": "copilot", "quelle": "chat-bestaetigt",
    })
    conn.execute(
        "INSERT INTO obsidian_eintrag (vermittler_nr, typ, titel, datum, datei, autor, quelle) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (nr, protokoll["typ"], protokoll["titel"], protokoll["datum"], protokoll["datei"], "copilot", "chat-bestaetigt"))
    return {"vermittler_nr": nr, "anzahl": len(items), "protokoll": protokoll["datei"]}
