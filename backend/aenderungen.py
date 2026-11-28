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
    if art in ("profil_fakt_neu", "notiz_neu"):
        return None  # neu angelegt – es gibt keinen bisherigen Wert, also auch keinen Konflikt
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


# --------------------------------------------------------------------------- Neue Infos (Profil, Notiz)

NEU_ARTEN = ("profil_fakt_neu", "notiz_neu")
_GRUPPEN_LABEL = {"partner": "Gesprächsinhalt", "business": "Geschäftliches", "next-step": "Nächster Schritt"}


def profil_kategorie(label: str, wert: str) -> str:
    l = label.lower()
    for slug, text in obsidian.PROFIL_KATEGORIEN.items():
        if l == text.lower() or l == slug or l.split(" ")[0] in text.lower():
            return slug
    return obsidian.kategorie_erkennen(f"{label} {wert}")


def neue_daten_vorschlag(conn: sqlite3.Connection, nr: int,
                         angaben: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """`im_obsidian_speichern` im Chat: neue Profil-Infos/Notizen als Vorschlag statt sofort speichern."""
    v = db.get_vermittler_full(conn, nr)
    if v is None:
        return {"fehler": f"Vermittler {nr} nicht gefunden – kein Vorschlag erstellt."}, None
    vorhandene = {f["text"].lower() for f in obsidian.read_profil(nr)["fakten"]}
    items: list[dict[str, Any]] = []
    hinweise: list[str] = []
    for angabe in angaben:
        gruppe, label, wert = str(angabe.get("gruppe", "")), str(angabe.get("label", "")).strip(), str(angabe.get("wert", "")).strip()
        if not wert:
            continue
        if gruppe == "persoenlich":
            if wert.lower() in vorhandene:
                hinweise.append(f"'{wert}' steht schon im Profil")
                continue
            kategorie = profil_kategorie(label, wert)
            items.append({"art": "profil_fakt_neu", "bereich": "Persönliches Profil", "kategorie": kategorie,
                          "label": obsidian.PROFIL_KATEGORIEN.get(kategorie, "Sonstiges"), "alt": None, "neu": wert,
                          "angabe": {"gruppe": gruppe, "label": label, "wert": wert, "quelle": angabe.get("quelle") or "Chat"}})
        else:
            items.append({"art": "notiz_neu", "bereich": "Neue Notiz",
                          "label": _GRUPPEN_LABEL.get(gruppe, "Notiz") + (f" · {label}" if label else ""),
                          "alt": None, "neu": wert,
                          "angabe": {"gruppe": gruppe, "label": label, "wert": wert, "quelle": angabe.get("quelle") or "Chat"}})
    if not items:
        return {"fehler": "Kein Vorschlag erstellt.", "details": hinweise}, None
    vorschlag = {"vermittler_nr": nr, "vermittler": v["anzeigename"], "begruendung": "Neue Infos aus dem Chat",
                 "aenderungen": items}
    return {
        "status": "Vorschlag erstellt – NICHT gespeichert. Der Nutzer muss ihn im Tab 'Aenderungen' bestaetigen.",
        "vorgeschlagen": [{"ziel": i["bereich"], "feld": i["label"], "neu": i["neu"]} for i in items],
        "nicht_uebernommen": hinweise,
    }, vorschlag


def notiz_titel(angaben: list[dict[str, Any]], max_len: int = 60) -> str:
    """Titel aus dem Inhalt statt "Aus dem Chat" – so steht im Obsidian-Netz, worum es geht."""
    erste = str(angaben[0].get("wert", "")).strip() or "Notiz"
    titel = erste if len(erste) <= max_len else erste[: max_len - 1].rstrip() + "…"
    return f"{titel} (+{len(angaben) - 1})" if len(angaben) > 1 else titel


def obsidian_speichern(conn: sqlite3.Connection, nr: int, angaben: list[dict[str, Any]]
                       ) -> tuple[dict[str, Any], int | None, list[dict[str, str]], str | None]:
    """Schreibt Angaben ins Obsidian-Netz (Profil bzw. Notiz). Wird erst nach der Bestaetigung aufgerufen."""
    v = db.get_vermittler_full(conn, nr)
    if v is None:
        return {"fehler": "Vermittler nicht gefunden – nichts gespeichert"}, None, [], None
    findings: list[dict[str, str]] = []
    gespeichert: list[dict[str, Any]] = []
    notiz: list[dict[str, Any]] = []
    for index, item in enumerate(angaben, start=1):
        gruppe, label, wert = str(item["gruppe"]), str(item["label"]).strip(), str(item["wert"]).strip()
        if not wert:
            continue
        if gruppe == "persoenlich":
            fakt = obsidian.add_profil_fakt(v, wert, profil_kategorie(label, wert))
            gespeichert.append({"ziel": f"Persoenliches Profil / {fakt['kategorie_label']}", "info": wert,
                                "uri": obsidian.read_profil(nr)["uri"]})
        else:
            notiz.append(item)
        findings.append({"id": f"saved-{index}", "group": gruppe, "label": label, "value": wert,
                         "source": str(item.get("quelle") or "Chat"), "status": "confirmed"})
    if notiz:
        inhalt = [f"- **{i['label']}:** {i['wert']}" for i in notiz if i["gruppe"] != "next-step"]
        massnahmen = [{"beschreibung": str(i["wert"])} for i in notiz if i["gruppe"] == "next-step"]
        res = obsidian.add_entry(v, {
            "typ": "notiz", "titel": notiz_titel(notiz), "inhalt": "\n".join(inhalt) or "Vereinbarte nächste Schritte.",
            "massnahmen": massnahmen, "tags": ["chat"], "autor": "copilot", "quelle": "chat",
        })
        conn.execute(
            "INSERT INTO obsidian_eintrag (vermittler_nr, typ, titel, datum, datei, autor, quelle) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nr, res["typ"], res["titel"], res["datum"], res["datei"], "copilot", "chat"),
        )
        gespeichert.append({"ziel": "Notiz", "titel": res["titel"], "uri": res["uri"]})
    return ({"status": "gespeichert", "gespeichert": gespeichert, "akte_link": obsidian.reference(nr)["uri"]},
            nr, findings, "Obsidian")


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
    for i in (i for i in items if i["art"] in ("profil_fakt_aendern", "profil_fakt_loeschen")):
        obsidian.delete_profil_fakt(nr, i["fakt_id"])
        if i["art"] == "profil_fakt_aendern":
            obsidian.add_profil_fakt(v_neu, i["neu"], i["kategorie"])
    neue_angaben = [i["angabe"] for i in items if i["art"] in NEU_ARTEN]
    if neue_angaben:  # neue Profil-Infos und Notizen aus dem Chat
        obsidian_speichern(conn, nr, neue_angaben)
    obsidian.sync_hub(db.get_vermittler_full(conn, nr))
    # Bewusst KEINE eigene "Aenderung wurde gemacht"-Notiz: Im Obsidian-Netz steht die Information selbst
    # (Profil-Fakt, Notiz, aktualisierte Stammdaten im Hub). Wer wann was geaendert hat (alt -> neu),
    # bleibt in der Tabelle chat_aenderung nachvollziehbar.
    return {"vermittler_nr": nr, "anzahl": len(items),
            "aenderungen": [{"bereich": i["bereich"], "feld": i["label"], "alt": i["alt"], "neu": i["neu"]} for i in items]}
