"""Agentenwerkzeuge auf dem Team-Schema (v_vermittler, geschaeftszahlen) und dem Obsidian-Gehirn.

Grundsätze:
- Lesen nur über eine schreibgeschützte Verbindung (`backend.db.connect(readonly=True)`), alle SQL parametrisiert.
- Kennzahlen rechnet SQL, nicht das Sprachmodell.
- Mehrdeutigkeit → `rueckfrage` bzw. `kandidaten` statt Raten.
- Schreiben gibt es hier NICHT: `notiz_erfassen` und `entwurf_vermittler` erzeugen nur Entwürfe.
  Gespeichert wird ausschließlich über `entwuerfe.bestaetigen` nach Klick des Nutzers.
- Jedes Ergebnis hat dasselbe Format (art, titel, spalten, zeilen, hinweise, quelle, ...).
"""
from __future__ import annotations

import difflib
import itertools
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from contextlib import contextmanager
from datetime import date
from typing import Any

from .. import db, obsidian

KENNZAHLEN = {
    "kreditvolumen": ("volumen_eur", "Kreditvolumen (EUR)"),
    "darlehen_anzahl": ("anzahl_darlehen", "Anzahl Darlehen"),
    "wachstum_kreditvolumen": (None, "Wachstum Kreditvolumen zum Vorjahr"),
}
JAHR_BEDEUTUNGEN = {
    "betreuungsbeginn": "Betreuungsbeginn im Jahr",
    "betreut_im_jahr": "im Jahr betreut",
    "geschaeft_im_jahr": "Geschäft im Jahr (Kreditvolumen oder Darlehen > 0)",
}
MASSNAHMEN_STATUS = ("geplant", "offen", "erledigt")
MAX_ZEILEN_FUER_MODELL = 40
TASK_RE = re.compile(r"^- \[(?P<x>[ xX])\] (?P<text>.*?)(?: 👤 (?P<wer>.*?))?(?: 📅 (?P<frist>\d{4}-\d{2}-\d{2}))?\s*$")
NAME_SQL = "trim(coalesce(v.titel || ' ', '') || v.vorname || ' ' || v.name)"
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def normalisiere_name(text: str | None) -> str:
    """Kleinschreibung, Umlaute ausgeschrieben, Akzente entfernt – für tolerante Namenssuche."""
    t = (text or "").translate(_UMLAUTE).lower()
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


def ergebnis(art: str, titel: str, *, spalten=None, zeilen=None, hinweise=None, quelle=None, **extra) -> dict:
    erg = {"art": art, "titel": titel, "spalten": spalten or [], "zeilen": zeilen or [],
           "hinweise": hinweise or [], "quelle": quelle or {}}
    erg.update(extra)
    return erg


def fuer_modell(erg: dict) -> str:
    """Kompakte JSON-Fassung für das Modell; lange Tabellen werden gekürzt (die Oberfläche zeigt alles)."""
    kopie = dict(erg)
    if len(kopie.get("zeilen", [])) > MAX_ZEILEN_FUER_MODELL:
        kopie["zeilen"] = kopie["zeilen"][:MAX_ZEILEN_FUER_MODELL]
        kopie["hinweise"] = list(kopie.get("hinweise", [])) + [
            f"Für das Modell gekürzt auf {MAX_ZEILEN_FUER_MODELL} von {len(erg['zeilen'])} Zeilen."]
    return json.dumps(kopie, ensure_ascii=False, default=str)


def massnahmen_aus_eintrag(eintrag: dict) -> list[dict]:
    """Liest Obsidian-Tasks (`- [ ] Text 👤 Person 📅 JJJJ-MM-TT`) aus einem Eintrag des Team-Gehirns."""
    out = []
    for zeile in eintrag.get("inhalt", "").splitlines():
        m = TASK_RE.match(zeile.strip())
        if not m:
            continue
        text = m.group("text").strip()
        status = "erledigt" if m.group("x").lower() == "x" else "offen"
        if status == "offen" and text.endswith("(geplant)"):
            status, text = "geplant", text[: -len("(geplant)")].strip()
        out.append({"beschreibung": text, "verantwortlich": m.group("wer"), "frist": m.group("frist"),
                    "status": status, "datei": eintrag.get("datei"), "datum": eintrag["frontmatter"].get("datum")})
    return out


TOOL_SPECS: list[dict[str, Any]] = [
    {"name": "vermittler_suchen",
     "description": "Sucht Vermittler nach Name (tolerant gegenüber Umlauten und Tippfehlern), Vermittlernummer, "
                    "Firma, Ort, Marktgebiet oder Status. Liefert Kandidaten mit Unterscheidungsmerkmalen. Bei "
                    "mehreren Treffern NICHT selbst wählen, sondern den Nutzer fragen.",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string", "description": "Name, Namensteil, Firma oder Ort"},
         "vermittler_nr": {"type": "integer"},
         "marktgebiet": {"type": "string"},
         "status": {"type": "string", "enum": ["aktiv", "inaktiv", "gesperrt"]}}}},
    {"name": "aktiven_vermittler_setzen",
     "description": "Merkt sich den eindeutig ausgewählten Vermittler für Folgefragen in dieser Sitzung.",
     "input_schema": {"type": "object", "properties": {"vermittler_nr": {"type": "integer"}},
                      "required": ["vermittler_nr"]}},
    {"name": "vermittlerakte",
     "description": "Vermittlerakte: Stammdaten, Kontakt, Betreuung, Interessen, Geschäftszahlen je Jahr mit "
                    "Datenstatus, offene Maßnahmen und letzte Gespräche aus dem Gedächtnis. Ohne Nummer wird der "
                    "aktive Vermittler verwendet. Auch für die Vorbereitung eines Termins.",
     "input_schema": {"type": "object", "properties": {"vermittler_nr": {"type": "integer"}}}},
    {"name": "ranking",
     "description": "Rangliste der Vermittler nach einer Kennzahl in einem Jahr (Gleichstände teilen sich einen "
                    "Platz). kriterium_bestaetigt nur auf true setzen, wenn der Nutzer Kennzahl UND Jahr ausdrücklich "
                    "genannt oder bestätigt hat; sonst vorher nachfragen.",
     "input_schema": {"type": "object", "properties": {
         "kennzahl": {"type": "string", "enum": list(KENNZAHLEN)},
         "jahr": {"type": "integer"},
         "anzahl": {"type": "integer", "minimum": 1, "maximum": 50},
         "marktgebiet": {"type": "string"},
         "status": {"type": "string", "enum": ["aktiv", "inaktiv", "gesperrt"]},
         "kriterium_bestaetigt": {"type": "boolean"}},
         "required": ["kennzahl", "jahr", "kriterium_bestaetigt"]}},
    {"name": "vermittler_filtern",
     "description": "Filtert Vermittler kombiniert nach Jahr (mit Bedeutung), Marktgebiet, Status, Kennzahl-"
                    "Schwellen oder 'ohne Geschäft in allen Jahren'. Ein Jahr ohne jahr_bedeutung führt zu einer "
                    "Rückfrage.",
     "input_schema": {"type": "object", "properties": {
         "jahr": {"type": "integer"},
         "jahr_bedeutung": {"type": "string", "enum": list(JAHR_BEDEUTUNGEN)},
         "marktgebiet": {"type": "string"},
         "status": {"type": "string", "enum": ["aktiv", "inaktiv", "gesperrt"]},
         "kennzahl": {"type": "string", "enum": ["kreditvolumen", "darlehen_anzahl"]},
         "min_wert": {"type": "number"}, "max_wert": {"type": "number"},
         "ohne_geschaeft_alle_jahre": {"type": "boolean"}}}},
    {"name": "massnahmen_abfragen",
     "description": "Maßnahmen aus dem Gedächtnis nach Status (Standard: geplant und offen), optional nur "
                    "überfällige. Ohne Nummer der aktive Vermittler; ist keiner aktiv, alle Vermittler.",
     "input_schema": {"type": "object", "properties": {
         "vermittler_nr": {"type": "integer"},
         "status": {"type": "array", "items": {"type": "string", "enum": list(MASSNAHMEN_STATUS)}},
         "nur_ueberfaellig": {"type": "boolean"}}}},
    {"name": "gespraeche_abrufen",
     "description": "Letzte Gespräche/Notizen eines Vermittlers aus dem dauerhaften Gedächtnis (auch aus früheren "
                    "Sitzungen). Ohne Nummer der aktive Vermittler.",
     "input_schema": {"type": "object", "properties": {"vermittler_nr": {"type": "integer"},
                                                        "anzahl": {"type": "integer", "minimum": 1, "maximum": 20}}}},
    {"name": "notiz_erfassen",
     "description": "Analysiert eine Gesprächsnotiz und erstellt einen ENTWURF (nichts wird gespeichert). Ohne "
                    "'text' wird die letzte Nutzernachricht wörtlich verwendet (empfohlen). Gespeichert wird erst, "
                    "wenn der Nutzer den Entwurf in der Oberfläche bestätigt.",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string"},
                                                        "vermittler_nr": {"type": "integer"}}}},
    {"name": "entwurf_vermittler",
     "description": "Erstellt einen ENTWURF für einen neuen Vermittler (nichts wird gespeichert). Pflicht: vorname, "
                    "name. Fehlende Pflichtangaben erfragen. Gespeichert wird erst nach Bestätigung durch den Nutzer.",
     "input_schema": {"type": "object", "properties": {
         "vorname": {"type": "string"}, "name": {"type": "string"}, "vermittler_nr": {"type": "integer"},
         "firma_filiale": {"type": "string"}, "vermittlertyp": {"type": "string"},
         "mitarbeiter_id": {"type": "string", "description": "Betreuer-ID (muss existieren)"},
         "email": {"type": "string"}, "telefon_dienst": {"type": "string"}, "ort": {"type": "string"}}}},
]


class Toolbox:
    """Führt Werkzeuge aus und hält den Kurzzeitkontext einer Sitzung (aktiver Vermittler, offene Entwürfe)."""

    def __init__(self, heute: date | None = None, analysator: Any = None):
        """analysator: Objekt mit `analysiere(text) -> dict` und `modell_id` (siehe notizen.NotizAnalysator)."""
        self.heute = heute or date.today()
        self.analysator = analysator
        self.kontext: dict[str, Any] = {"aktiver_vermittler": None, "entwuerfe": {}, "letzte_nutzernachricht": ""}
        self._ids = itertools.count(1)

    # ------------------------------------------------------------------ Infrastruktur
    def specs(self) -> list[dict]:
        return TOOL_SPECS

    @contextmanager
    def _conn(self):
        conn = db.connect(readonly=True)
        conn.create_function("norm", 1, normalisiere_name, deterministic=True)
        try:
            yield conn
        finally:
            conn.close()

    def ausfuehren(self, name: str, eingabe: dict | None) -> dict:
        funktion = getattr(self, f"t_{name}", None)
        if funktion is None:
            return ergebnis("fehler", "Unbekanntes Werkzeug", hinweise=[f"Werkzeug '{name}' existiert nicht."])
        try:
            return funktion(**(eingabe or {}))
        except (TypeError, ValueError) as exc:
            return ergebnis("fehler", "Ungültige Parameter", hinweise=[str(exc)], quelle={"werkzeug": name})
        except sqlite3.Error as exc:
            return ergebnis("fehler", "Datenbankfehler", hinweise=[str(exc)], quelle={"werkzeug": name})

    def _quelle(self, werkzeug: str, parameter: dict, datensaetze=None, datenstand=None) -> dict:
        return {"werkzeug": werkzeug, "parameter": {k: v for k, v in parameter.items() if v not in (None, [], "")},
                "datenstand": datenstand or f"Datenbank, abgefragt {self.heute.isoformat()}",
                "datensaetze": datensaetze or []}

    def _nr(self, vermittler_nr) -> int | None:
        wert = vermittler_nr if vermittler_nr not in (None, "") else self.kontext.get("aktiver_vermittler")
        return int(wert) if wert not in (None, "") else None

    def _status_jahr(self, jahr: int) -> str:
        return "vorläufig (unterjährig)" if jahr >= self.heute.year else "final"

    def _neue_id(self, praefix: str) -> str:
        return f"{praefix}-{self.heute:%Y%m%d}-{id(self) % 10000:04d}-{next(self._ids)}"

    # ------------------------------------------------------------------ Lesen
    def t_vermittler_suchen(self, text=None, vermittler_nr=None, marktgebiet=None, status=None):
        params = {"text": text, "vermittler_nr": vermittler_nr, "marktgebiet": marktgebiet, "status": status}
        auswahl = (f"SELECT v.vermittler_nr, {NAME_SQL}, v.firma_filiale, v.marktgebiet, v.filiale, v.ort, v.status "
                   "FROM v_vermittler v WHERE 1=1")
        sql, werte, hinweise = auswahl, [], []
        if vermittler_nr not in (None, ""):
            sql += " AND v.vermittler_nr = ?"
            werte.append(int(vermittler_nr))
        for token in normalisiere_name(text).split() if text else []:
            sql += (" AND (norm(v.vorname || ' ' || v.name) LIKE ? OR norm(coalesce(v.firma_filiale, '')) LIKE ? "
                    "OR norm(coalesce(v.ort, '')) LIKE ?)")
            werte += [f"%{token}%"] * 3
        if marktgebiet:
            sql += " AND v.marktgebiet = ? COLLATE NOCASE"
            werte.append(marktgebiet)
        if status:
            sql += " AND v.status = ?"
            werte.append(status)
        sql += " ORDER BY v.name, v.vorname, v.vermittler_nr LIMIT 25"
        with self._conn() as conn:
            zeilen = [list(r) for r in conn.execute(sql, werte)]
            if not zeilen and text:
                namen = [r[0] for r in conn.execute("SELECT DISTINCT norm(vorname || ' ' || name) FROM vermittler")]
                nah = difflib.get_close_matches(normalisiere_name(text), namen, n=5, cutoff=0.75)
                if nah:
                    platz = ",".join("?" * len(nah))
                    zeilen = [list(r) for r in conn.execute(
                        auswahl + f" AND norm(v.vorname || ' ' || v.name) IN ({platz}) ORDER BY v.name, v.vermittler_nr",
                        nah)]
                    hinweise.append(f"Kein exakter Treffer für „{text}“ – ähnliche Namen gefunden. Bitte bestätigen.")
        quelle = self._quelle("vermittler_suchen", params, [z[0] for z in zeilen])
        if not zeilen:
            return ergebnis("hinweis", "Kein Vermittler gefunden", quelle=quelle, hinweise=[
                f"Kein Vermittler zu „{text or vermittler_nr or marktgebiet}“ gefunden. Es werden keine Daten erfunden."])
        if len(zeilen) > 1:
            hinweise.append(f"{len(zeilen)} Treffer – bitte anhand Vermittlernummer, Firma oder Marktgebiet auswählen.")
        return ergebnis("kandidaten" if (len(zeilen) > 1 or hinweise) else "tabelle", "Gefundene Vermittler",
                        spalten=["Vermittler-Nr.", "Name", "Firma", "Marktgebiet", "Filiale", "Ort", "Status"],
                        zeilen=zeilen, hinweise=hinweise, quelle=quelle)

    def t_aktiven_vermittler_setzen(self, vermittler_nr):
        nr = int(vermittler_nr)
        with self._conn() as conn:
            row = conn.execute(f"SELECT {NAME_SQL}, v.firma_filiale, v.marktgebiet FROM v_vermittler v "
                               "WHERE v.vermittler_nr = ?", (nr,)).fetchone()
        quelle = self._quelle("aktiven_vermittler_setzen", {"vermittler_nr": nr}, [nr] if row else [])
        if not row:
            return ergebnis("hinweis", "Vermittler nicht gefunden", hinweise=[f"Vermittlernummer {nr} existiert nicht."],
                            quelle=quelle)
        self.kontext["aktiver_vermittler"] = nr
        return ergebnis("hinweis", "Aktiver Vermittler gesetzt", quelle=quelle,
                        hinweise=[f"Aktiver Vermittler: {row[0]} (Nr. {nr}, {row[1]}, Marktgebiet {row[2]})."],
                        aktiver_vermittler={"vermittler_nr": nr, "name": row[0], "firma": row[1], "marktgebiet": row[2]})

    def _massnahmen(self, nr: int | None) -> list[dict]:
        """Maßnahmen aus Obsidian-Einträgen (Team-Gehirn); ohne Nummer über alle Vermittler-Ordner."""
        nummern = [nr] if nr else []
        if not nr:
            wurzel = obsidian.abs_path("Vermittler")
            if wurzel.is_dir():
                nummern = [int(p.name[3:]) for p in wurzel.iterdir() if p.is_dir() and p.name[3:].isdigit()]
        alle = []
        for n in nummern:
            for e in obsidian.list_entries(n):
                for m in massnahmen_aus_eintrag(e):
                    m["vermittler_nr"] = n
                    m["ueberfaellig"] = bool(m["frist"] and m["frist"] < self.heute.isoformat()
                                             and m["status"] != "erledigt")
                    alle.append(m)
        return alle

    def t_vermittlerakte(self, vermittler_nr=None):
        nr = self._nr(vermittler_nr)
        if not nr:
            return ergebnis("rueckfrage", "Welcher Vermittler?", hinweise=["Bitte Namen oder Vermittlernummer nennen."])
        with self._conn() as conn:
            v = db.get_vermittler_full(conn, nr)
        if v is None:
            return ergebnis("hinweis", "Vermittler nicht gefunden", hinweise=[f"Vermittlernummer {nr} existiert nicht."])
        self.kontext["aktiver_vermittler"] = nr
        gehirn = obsidian.read_brain(nr, limit=3)
        massnahmen = [m for m in self._massnahmen(nr) if m["status"] != "erledigt"]
        zahlen = sorted((z for z in v["geschaeftszahlen"] if z["sparte"] == "gesamt"), key=lambda z: z["jahr"])
        k, b = v["kontakt"], v["betreuung"]
        hinweise = []
        if not k.get("handy_dienst"):
            hinweise.append("Diensthandynummer nicht hinterlegt.")
        if not v["interessen"]:
            hinweise.append("Keine Interessen hinterlegt.")
        vorl = [z["jahr"] for z in zahlen if z["jahr"] >= self.heute.year]
        if vorl:
            hinweise.append(f"{', '.join(map(str, vorl))} ist unterjährig/vorläufig und nicht mit vollständigen Jahren vergleichbar.")
        if v["status"] != "aktiv":
            hinweise.append(f"Status des Vermittlers: {v['status']}.")
        abschnitte = [
            {"titel": "Stammdaten", "spalten": ["Feld", "Wert"], "zeilen": [
                ["Vermittler-Nr.", v["vermittler_nr"]], ["Name", v["anzeigename"]], ["Firma", v["firma_filiale"]],
                ["Typ", v["vermittlertyp"]], ["Status", v["status"]],
                ["Vertriebspartnerstatus", v["status_vertriebspartner"]],
                ["Marktgebiet / Filiale", f"{b.get('marktgebiet')} / {b.get('filiale')}"],
                ["Betreuung", f"{b.get('name')} seit {b.get('seit')}" + (f" bis {b['bis']}" if b.get("bis") else "")],
                ["E-Mail", k.get("email")], ["Telefon (Dienst)", k.get("telefon_dienst")],
                ["Diensthandy", k.get("handy_dienst") or "nicht hinterlegt"],
                ["Interessen", ", ".join(v["interessen"]) or "keine hinterlegt"]]},
            {"titel": "Geschäftszahlen", "spalten": ["Jahr", "Kreditvolumen (EUR)", "Anzahl Darlehen", "Datenstatus"],
             "zeilen": [[z["jahr"], z["volumen_eur"], z["anzahl_darlehen"], self._status_jahr(z["jahr"])] for z in zahlen],
             "diagramm": {"typ": "linie", "x": "Jahr", "y": "Kreditvolumen (EUR)"}},
            {"titel": "Offene und geplante Maßnahmen", "spalten": ["Maßnahme", "Verantwortlich", "Frist", "Status", "Überfällig"],
             "zeilen": [[m["beschreibung"], m["verantwortlich"], m["frist"], m["status"], "ja" if m["ueberfaellig"] else "nein"]
                        for m in sorted(massnahmen, key=lambda m: m["frist"] or "9999")]},
            {"titel": "Letzte Gespräche und Notizen", "spalten": ["Datum", "Typ", "Titel", "Auszug"],
             "zeilen": [[e["frontmatter"].get("datum"), e["frontmatter"].get("typ"), e["frontmatter"].get("titel"),
                         _auszug(e["inhalt"])] for e in gehirn["eintraege"]]},
        ]
        return ergebnis("akte", f"Vermittlerakte {v['anzeigename']} (Nr. {nr})", abschnitte=abschnitte,
                        hinweise=hinweise, zusammenfassung=gehirn["zusammenfassung"],
                        obsidian_uri=v["obsidian"]["uri"],
                        quelle=self._quelle("vermittlerakte", {"vermittler_nr": nr}, [nr]))

    def t_ranking(self, kennzahl, jahr, kriterium_bestaetigt=False, anzahl=3, marktgebiet=None, status=None):
        params = {"kennzahl": kennzahl, "jahr": jahr, "anzahl": anzahl, "marktgebiet": marktgebiet, "status": status}
        if not kriterium_bestaetigt or kennzahl not in KENNZAHLEN:
            return ergebnis("rueckfrage", "Nach welcher Kennzahl?", quelle=self._quelle("ranking", params), hinweise=[
                "Bitte Kennzahl und Jahr nennen: Kreditvolumen, Anzahl Darlehen oder Wachstum des Kreditvolumens."])
        jahr, anzahl = int(jahr), max(1, min(int(anzahl or 3), 50))
        spalte, bezeichnung = KENNZAHLEN[kennzahl]
        flt, werte = "", []
        if marktgebiet:
            flt += " AND v.marktgebiet = ? COLLATE NOCASE"
            werte.append(marktgebiet)
        if status:
            flt += " AND v.status = ?"
            werte.append(status)
        hinweise: list[str] = []
        with self._conn() as conn:
            if spalte:  # Spaltenname aus der Whitelist KENNZAHLEN
                zeilen = [list(r) for r in conn.execute(
                    f"SELECT * FROM (SELECT RANK() OVER (ORDER BY g.{spalte} DESC) AS platz, v.vermittler_nr, {NAME_SQL}, "
                    f"v.firma_filiale, v.marktgebiet, v.status, g.{spalte} FROM v_vermittler v JOIN geschaeftszahlen g "
                    f"ON g.vermittler_nr = v.vermittler_nr AND g.jahr = ? AND g.sparte = 'gesamt' WHERE 1=1{flt}) "
                    "WHERE platz <= ? ORDER BY platz, vermittler_nr", [jahr, *werte, anzahl])]
                spalten = ["Platz", "Vermittler-Nr.", "Name", "Firma", "Marktgebiet", "Status", bezeichnung]
            else:
                basis = ("FROM v_vermittler v JOIN geschaeftszahlen a ON a.vermittler_nr = v.vermittler_nr AND a.jahr = ? "
                         "AND a.sparte = 'gesamt' JOIN geschaeftszahlen b ON b.vermittler_nr = v.vermittler_nr "
                         f"AND b.jahr = ? AND b.sparte = 'gesamt' WHERE 1=1{flt}")
                zeilen = [list(r) for r in conn.execute(
                    "SELECT * FROM (SELECT RANK() OVER (ORDER BY 1.0 * (a.volumen_eur - b.volumen_eur) / b.volumen_eur DESC) "
                    f"AS platz, v.vermittler_nr, {NAME_SQL}, v.firma_filiale, v.marktgebiet, v.status, b.volumen_eur, "
                    "a.volumen_eur, ROUND(100.0 * (a.volumen_eur - b.volumen_eur) / b.volumen_eur, 1) "
                    f"{basis} AND b.volumen_eur > 0) WHERE platz <= ? ORDER BY platz, vermittler_nr",
                    [jahr, jahr - 1, *werte, anzahl])]
                neu = conn.execute(f"SELECT COUNT(*) {basis} AND b.volumen_eur = 0 AND a.volumen_eur > 0",
                                   [jahr, jahr - 1, *werte]).fetchone()[0]
                if neu:
                    hinweise.append(f"{neu} Vermittler hatten {jahr - 1} kein Volumen und {jahr} Neugeschäft: Wachstum "
                                    "nicht berechenbar („neu“), daher nicht im Ranking.")
                spalten = ["Platz", "Vermittler-Nr.", "Name", "Firma", "Marktgebiet", "Status",
                           f"Kreditvolumen {jahr - 1} (EUR)", f"Kreditvolumen {jahr} (EUR)", "Wachstum (%)"]
        if not zeilen:
            return ergebnis("hinweis", "Keine Daten", quelle=self._quelle("ranking", params),
                            hinweise=[f"Keine Geschäftszahlen für {jahr} mit diesen Filtern."])
        for platz, n in sorted(Counter(z[0] for z in zeilen).items()):
            if n > 1:
                hinweise.append(f"Gleichstand: Platz {platz} teilen sich {n} Vermittler.")
        for z in zeilen:
            if z[5] != "aktiv":
                hinweise.append(f"{z[2]} (Nr. {z[1]}) hat den Status „{z[5]}“.")
        if jahr >= self.heute.year:
            hinweise.append(f"{jahr} ist unterjährig/vorläufig – nicht mit vollständigen Jahren vergleichbar.")
        return ergebnis("tabelle", f"Top {anzahl} nach {bezeichnung} {jahr}", spalten=spalten, zeilen=zeilen,
                        hinweise=hinweise, quelle=self._quelle("ranking", params, [z[1] for z in zeilen],
                                                                  f"Geschäftsjahr {jahr}: {self._status_jahr(jahr)}"))

    def t_vermittler_filtern(self, jahr=None, jahr_bedeutung=None, marktgebiet=None, status=None, kennzahl=None,
                             min_wert=None, max_wert=None, ohne_geschaeft_alle_jahre=False):
        params = {"jahr": jahr, "jahr_bedeutung": jahr_bedeutung, "marktgebiet": marktgebiet, "status": status,
                  "kennzahl": kennzahl, "min_wert": min_wert, "max_wert": max_wert,
                  "ohne_geschaeft_alle_jahre": ohne_geschaeft_alle_jahre or None}
        if jahr and jahr_bedeutung not in JAHR_BEDEUTUNGEN:
            return ergebnis("rueckfrage", f"Was bedeutet „aus {jahr}“?", quelle=self._quelle("vermittler_filtern", params),
                            hinweise=["Bitte wählen: Betreuungsbeginn im Jahr, im Jahr betreut oder Geschäft im Jahr."])
        if kennzahl and not jahr:
            return ergebnis("rueckfrage", "Für welches Jahr?", hinweise=["Für Kennzahl-Schwellen bitte ein Jahr nennen."])
        sql = f"SELECT v.vermittler_nr, {NAME_SQL}, v.firma_filiale, v.marktgebiet, v.status FROM v_vermittler v WHERE 1=1"
        werte: list[Any] = []
        if jahr:
            jahr = int(jahr)
            if jahr_bedeutung == "betreuungsbeginn":
                sql += " AND substr(v.betreuung_seit, 1, 4) = ?"
                werte.append(str(jahr))
            elif jahr_bedeutung == "betreut_im_jahr":
                sql += " AND v.betreuung_seit <= ? AND (v.betreuung_bis IS NULL OR v.betreuung_bis >= ?)"
                werte += [f"{jahr}-12-31", f"{jahr}-01-01"]
            else:
                sql += (" AND EXISTS (SELECT 1 FROM geschaeftszahlen g WHERE g.vermittler_nr = v.vermittler_nr "
                        "AND g.jahr = ? AND g.sparte = 'gesamt' AND (g.volumen_eur > 0 OR g.anzahl_darlehen > 0))")
                werte.append(jahr)
        if marktgebiet:
            sql += " AND v.marktgebiet = ? COLLATE NOCASE"
            werte.append(marktgebiet)
        if status:
            sql += " AND v.status = ?"
            werte.append(status)
        if kennzahl in ("kreditvolumen", "darlehen_anzahl") and (min_wert is not None or max_wert is not None):
            spalte = KENNZAHLEN[kennzahl][0]
            sql += (f" AND EXISTS (SELECT 1 FROM geschaeftszahlen g WHERE g.vermittler_nr = v.vermittler_nr AND g.jahr = ? "
                    f"AND g.sparte = 'gesamt' AND g.{spalte} >= ? AND g.{spalte} <= ?)")
            werte += [jahr, min_wert if min_wert is not None else -1e18, max_wert if max_wert is not None else 1e18]
        if ohne_geschaeft_alle_jahre:
            sql += (" AND NOT EXISTS (SELECT 1 FROM geschaeftszahlen g WHERE g.vermittler_nr = v.vermittler_nr "
                    "AND (g.volumen_eur > 0 OR g.anzahl_darlehen > 0))")
        sql += " ORDER BY v.name, v.vorname, v.vermittler_nr LIMIT 500"
        with self._conn() as conn:
            zeilen = [list(r) for r in conn.execute(sql, werte)]
        hinweise = [f"{len(zeilen)} Vermittler gefunden."]
        if jahr_bedeutung:
            hinweise.append(f"Jahresfilter: {JAHR_BEDEUTUNGEN[jahr_bedeutung]} {jahr}.")
        return ergebnis("tabelle", "Gefilterte Vermittler", spalten=["Vermittler-Nr.", "Name", "Firma", "Marktgebiet", "Status"],
                        zeilen=zeilen, hinweise=hinweise,
                        quelle=self._quelle("vermittler_filtern", params, [z[0] for z in zeilen]))

    def t_massnahmen_abfragen(self, vermittler_nr=None, status=None, nur_ueberfaellig=False):
        nr = self._nr(vermittler_nr)
        status = [s for s in (status or ["geplant", "offen"]) if s in MASSNAHMEN_STATUS] or ["geplant", "offen"]
        params = {"vermittler_nr": nr, "status": status, "nur_ueberfaellig": nur_ueberfaellig or None}
        liste = [m for m in self._massnahmen(nr) if m["status"] in status and (m["ueberfaellig"] or not nur_ueberfaellig)]
        namen = {}
        if liste:
            with self._conn() as conn:
                nummern = sorted({m["vermittler_nr"] for m in liste})
                namen = {r[0]: r[1] for r in conn.execute(
                    f"SELECT v.vermittler_nr, {NAME_SQL} FROM v_vermittler v WHERE v.vermittler_nr IN "
                    f"({','.join('?' * len(nummern))})", nummern)}
        liste.sort(key=lambda m: (m["frist"] or "9999", m["vermittler_nr"]))
        zeilen = [[m["vermittler_nr"], namen.get(m["vermittler_nr"]), m["beschreibung"], m["verantwortlich"], m["frist"],
                   m["status"], "ja" if m["ueberfaellig"] else "nein", m["datum"]] for m in liste]
        ueber = sum(1 for m in liste if m["ueberfaellig"])
        titel = ("Überfällige Maßnahmen" if nur_ueberfaellig else "Maßnahmen") + (f" – Nr. {nr}" if nr else " – alle Vermittler")
        return ergebnis("tabelle", titel, zeilen=zeilen,
                        spalten=["Vermittler-Nr.", "Vermittler", "Maßnahme", "Verantwortlich", "Frist", "Status",
                                 "Überfällig", "Aus Gespräch vom"],
                        hinweise=[f"{len(zeilen)} Maßnahmen ({', '.join(status)}), davon {ueber} überfällig "
                                  f"(Stand {self.heute.isoformat()})."],
                        quelle=self._quelle("massnahmen_abfragen", params, sorted({m["vermittler_nr"] for m in liste}),
                                            f"Gedächtnis (Obsidian), Stand {self.heute.isoformat()}"))

    def t_gespraeche_abrufen(self, vermittler_nr=None, anzahl=3):
        nr = self._nr(vermittler_nr)
        if not nr:
            return ergebnis("rueckfrage", "Welcher Vermittler?", hinweise=["Bitte Namen oder Vermittlernummer nennen."])
        eintraege = obsidian.list_entries(nr)[: max(1, min(int(anzahl or 3), 20))]
        zeilen = [[e["frontmatter"].get("datum"), e["frontmatter"].get("typ"), e["frontmatter"].get("titel"),
                   ", ".join(e["frontmatter"].get("teilnehmer") or []), _auszug(e["inhalt"], 600)] for e in eintraege]
        hinweise = [] if zeilen else ["Für diesen Vermittler sind noch keine Gespräche gespeichert."]
        return ergebnis("tabelle", f"Letzte Gespräche – Nr. {nr}", zeilen=zeilen, hinweise=hinweise,
                        spalten=["Datum", "Typ", "Titel", "Teilnehmer", "Inhalt"],
                        quelle=self._quelle("gespraeche_abrufen", {"vermittler_nr": nr},
                                            [e["datei"] for e in eintraege], "Gedächtnis (Obsidian)"))

    # ------------------------------------------------------------------ Entwürfe (kein Schreiben!)
    def t_notiz_erfassen(self, text=None, vermittler_nr=None):
        from .notizen import abgleich, zuordnung_pruefen
        text = (text or self.kontext.get("letzte_nutzernachricht") or "").strip()
        if self.analysator is None:
            return ergebnis("fehler", "Notizanalyse nicht verfügbar")
        if not text:
            return ergebnis("rueckfrage", "Welche Notiz?", hinweise=["Bitte den Gesprächsinhalt angeben."])
        try:
            daten = self.analysator.analysiere(text)
        except ValueError as exc:
            return ergebnis("fehler", "Notiz nicht verarbeitbar", hinweise=[str(exc)])
        nr, rueck = zuordnung_pruefen(self, daten, self._nr(vermittler_nr))
        if rueck:
            return rueck
        with self._conn() as conn:
            v = db.get_vermittler_full(conn, nr)
        if v is None:
            return ergebnis("hinweis", "Vermittler nicht gefunden", hinweise=[f"Vermittlernummer {nr} existiert nicht."])
        abgl = abgleich(v, daten)
        entwurf = {"entwurf_id": self._neue_id("E"), "typ": "gespraechsnotiz", "vermittler_nr": nr,
                   "vermittler_name": v["anzeigename"], "daten": daten, "abgleich": abgl, "rohtext": text,
                   "modell_id": getattr(self.analysator, "modell_id", None), "erstellt_am": self.heute.isoformat()}
        self.kontext["entwuerfe"][entwurf["entwurf_id"]] = entwurf
        self.kontext["aktiver_vermittler"] = nr
        return ergebnis("entwurf", f"Entwurf Gesprächsnotiz für {v['anzeigename']} (Nr. {nr}) – noch NICHT gespeichert",
                        spalten=["Feld", "Wert"], zeilen=_entwurf_zeilen(daten, abgl), entwurf=entwurf,
                        hinweise=daten["unsicherheiten"] + daten["auffaelligkeiten"]
                        + ["Bitte prüfen und in der Oberfläche bestätigen oder verwerfen."],
                        quelle=self._quelle("notiz_erfassen", {"vermittler_nr": nr}, [nr], "Entwurf (nicht gespeichert)"))

    def t_entwurf_vermittler(self, vorname=None, name=None, vermittler_nr=None, firma_filiale=None, vermittlertyp=None,
                             mitarbeiter_id=None, email=None, telefon_dienst=None, ort=None):
        fehlend = [f for f, w in (("Vorname", vorname), ("Name", name)) if not (w and str(w).strip())]
        if fehlend:
            return ergebnis("rueckfrage", "Angaben fehlen", hinweise=[f"Bitte noch angeben: {', '.join(fehlend)}."])
        hinweise = []
        with self._conn() as conn:
            if vermittler_nr and conn.execute("SELECT 1 FROM vermittler WHERE vermittler_nr = ?", (int(vermittler_nr),)).fetchone():
                return ergebnis("hinweis", "Vermittlernummer existiert bereits",
                                hinweise=[f"Nr. {vermittler_nr} ist vergeben. Bitte andere Nummer oder leer lassen."])
            if mitarbeiter_id and not conn.execute("SELECT 1 FROM betreuer WHERE mitarbeiter_id = ?", (mitarbeiter_id,)).fetchone():
                return ergebnis("hinweis", "Betreuer unbekannt", hinweise=[f"Betreuer-ID {mitarbeiter_id} existiert nicht."])
            vettern = [r[0] for r in conn.execute(
                "SELECT vermittler_nr FROM vermittler WHERE norm(vorname || ' ' || name) = ?",
                (normalisiere_name(f"{vorname} {name}"),))]
        if vettern:
            hinweise.append(f"Achtung: Es gibt bereits Vermittler mit diesem Namen (Nr. {', '.join(map(str, vettern))}).")
        if not vermittler_nr:
            hinweise.append("Vermittlernummer wird beim Speichern automatisch vergeben.")
        daten = {k: w for k, w in {"vorname": vorname, "name": name, "vermittler_nr": vermittler_nr,
                                  "firma_filiale": firma_filiale, "vermittlertyp": vermittlertyp,
                                  "mitarbeiter_id": mitarbeiter_id, "email": email, "telefon_dienst": telefon_dienst,
                                  "ort": ort}.items() if w not in (None, "")}
        entwurf = {"entwurf_id": self._neue_id("V"), "typ": "vermittler", "daten": daten}
        self.kontext["entwuerfe"][entwurf["entwurf_id"]] = entwurf
        return ergebnis("entwurf", f"Entwurf neuer Vermittler {vorname} {name} – noch NICHT gespeichert",
                        spalten=["Feld", "Wert"], zeilen=[[k, w] for k, w in daten.items()], entwurf=entwurf,
                        hinweise=hinweise + ["Bitte prüfen und in der Oberfläche bestätigen oder verwerfen."],
                        quelle=self._quelle("entwurf_vermittler", daten, datenstand="Entwurf (nicht gespeichert)"))


def _auszug(inhalt: str, laenge: int = 220) -> str:
    teil = inhalt.split("## Inhalt", 1)[-1]
    teil = re.sub(r"\s+", " ", re.sub(r"^#.*$", "", teil, flags=re.MULTILINE)).strip()
    return teil[:laenge] + ("…" if len(teil) > laenge else "")


def _entwurf_zeilen(d: dict, abgleich: list[str]) -> list[list[Any]]:
    zeilen = [["Datum", d["datum"]], ["Teilnehmer", ", ".join(d["teilnehmer"])], ["Anlass", d["anlass"]],
              ["Zusammenfassung", d["zusammenfassung"]], ["Vereinbarungen", "; ".join(d["vereinbarungen"])],
              ["Neue Interessen", ", ".join(d["interessen_neu"])],
              ["Für das nächste Gespräch", d["hinweise_naechstes_gespraech"]], ["Wiedervorlage", d["wiedervorlage_am"]]]
    zeilen += [["Maßnahme", f"{m['beschreibung']} · {m['verantwortlich'] or '–'} · {m['frist'] or 'ohne Frist'} · {m['status']}"]
               for m in d["massnahmen"]]
    zeilen += [["Zielvorschlag (nicht genehmigt)", f"{z['jahr']} {z['kennzahl']}: {z['wert']:,.0f}".replace(",", ".")]
               for z in d["zielvorschlaege"]]
    zeilen += [["Quartalsmeilenstein", f"Q{m['quartal']}/{m['jahr']}: {m['beschreibung']}"] for m in d["meilensteine"]]
    zeilen += [["Im Gespräch genannte Ist-Zahl", f"{z['jahr']} {z['kennzahl']}: {z['wert']:,.0f}".replace(",", ".")]
               for z in d["ist_zahlen_genannt"]]
    zeilen += [["Abgleich mit Datenbank", a] for a in abgleich]
    return [z for z in zeilen if z[1] not in (None, "", [])]
