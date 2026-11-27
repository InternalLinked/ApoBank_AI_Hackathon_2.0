"""Excel-Export (.xlsx) fuer den Analyse-Tab und die Partnerakte.

Erzeugt im Backend mit openpyxl (schon Abhaengigkeit), damit das Frontend keine Zusatzbibliothek braucht.
Sicherheit: Texte, die mit = + - @ beginnen, werden als Text gespeichert und nie als Formel ausgefuehrt
(Schutz vor Formel-Einschleusung ueber Notizen oder Namen).
"""
from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

KOPF_FARBE = "0D2857"   # Dunkelblau der Seitenleiste
MAX_ZEILEN = 5000
_EUR_SPALTE = re.compile(r"(volumen|eur|betrag|summe|umsatz)", re.IGNORECASE)
_FORMEL_START = ("=", "+", "-", "@")


def _zelle(ws: Worksheet, zeile: int, spalte: int, wert: Any) -> Any:
    zelle = ws.cell(row=zeile, column=spalte)
    if isinstance(wert, str) and wert.startswith(_FORMEL_START):
        zelle.value = wert
        zelle.data_type = "s"   # als Text erzwingen, nie als Formel
    else:
        zelle.value = wert
    return zelle


def _kopfzeile(ws: Worksheet, spalten: list[str], zeile: int = 1) -> None:
    for i, name in enumerate(spalten, start=1):
        zelle = _zelle(ws, zeile, i, name)
        zelle.font = Font(bold=True, color="FFFFFF")
        zelle.fill = PatternFill("solid", fgColor=KOPF_FARBE)
        zelle.alignment = Alignment(vertical="center")
    ws.freeze_panes = ws.cell(row=zeile + 1, column=1)


def _breiten(ws: Worksheet, maximal: int = 60) -> None:
    for spalte in ws.columns:
        laenge = max((len(str(z.value)) for z in spalte if z.value is not None), default=8)
        ws.column_dimensions[get_column_letter(spalte[0].column)].width = min(maximal, max(10, laenge + 2))


def _als_bytes(wb: Workbook) -> bytes:
    puffer = io.BytesIO()
    wb.save(puffer)
    return puffer.getvalue()


def dateiname(titel: str) -> str:
    """Sicherer Dateiname: nur Buchstaben/Zahlen/-_ , max. 80 Zeichen, mit Datum."""
    basis = re.sub(r"[^\w\-]+", "_", titel, flags=re.UNICODE).strip("_")[:80] or "Export"
    return f"{basis}_{datetime.now():%Y-%m-%d}.xlsx"


def content_disposition(name: str) -> str:
    """RFC 5987: ASCII-Fallback + UTF-8-Name (Umlaute bleiben im Browser erhalten)."""
    ascii_name = name.encode("ascii", "ignore").decode() or "Export.xlsx"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def tabelle(titel: str, spalten: list[str], zeilen: list[list[Any]], sql: str | None = None) -> bytes:
    """Analyse-Ergebnis als Tabelle; das verwendete SQL steht nachvollziehbar auf einem zweiten Blatt."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Analyse"
    _kopfzeile(ws, spalten)
    eur = {i for i, name in enumerate(spalten) if _EUR_SPALTE.search(name)}
    for r, zeile in enumerate(zeilen[:MAX_ZEILEN], start=2):
        for c, wert in enumerate(zeile, start=1):
            zelle = _zelle(ws, r, c, wert)
            if isinstance(wert, (int, float)):
                zelle.number_format = '#,##0 "€"' if (c - 1) in eur else "#,##0.##"
    _breiten(ws)
    if spalten:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(spalten))}{max(1, min(len(zeilen), MAX_ZEILEN) + 1)}"

    info = wb.create_sheet("Info")
    for r, (feld, wert) in enumerate([
        ("Titel", titel), ("Erstellt", f"{datetime.now():%d.%m.%Y %H:%M}"),
        ("Zeilen", min(len(zeilen), MAX_ZEILEN)), ("Quelle", "apoBank Vermittler-Datenbank (read-only Abfrage)"),
        ("SQL", sql or "–"),
    ], start=1):
        _zelle(info, r, 1, feld).font = Font(bold=True)
        _zelle(info, r, 2, wert).alignment = Alignment(wrap_text=True, vertical="top")
    info.column_dimensions["A"].width = 12
    info.column_dimensions["B"].width = 100
    return _als_bytes(wb)


def vermittler(v: dict[str, Any], profil: dict[str, Any], eintraege: list[dict[str, Any]]) -> bytes:
    """Partnerakte: Stammdaten/Kontakt, Geschaeftszahlen, persoenliches Profil, Notizen (je ein Blatt)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Partnerprofil"
    kontakt = v.get("kontakt") or {}
    betreuung = v.get("betreuung") or {}
    interessen = v.get("interessen_profil") or v.get("interessen") or []
    felder = [
        ("Vermittlernummer", v.get("vermittler_nr")), ("Name", v.get("anzeigename")),
        ("Anrede", v.get("anrede")), ("Titel", v.get("titel")), ("Firma", v.get("firma_filiale")),
        ("Holding", v.get("firma_holding")), ("Vermittlertyp", v.get("vermittlertyp")), ("Status", v.get("status")),
        ("Status Vertriebspartner", v.get("status_vertriebspartner")), ("Abrechnungskreis", v.get("abrechnungskreis")),
        ("Interessen", ", ".join(map(str, interessen)) if isinstance(interessen, list) else interessen),
        ("Geburtstag", v.get("geburtstag")),
        ("E-Mail", kontakt.get("email")), ("Telefon (dienstlich)", kontakt.get("telefon_dienst")),
        ("Handy (dienstlich)", kontakt.get("handy_dienst")), ("Telefon (privat)", kontakt.get("telefon_privat")),
        ("Straße", kontakt.get("strasse")), ("PLZ", kontakt.get("plz")), ("Ort", kontakt.get("ort")),
        ("Betreuer", betreuung.get("name")), ("Filiale", betreuung.get("filiale")),
        ("Marktgebiet", betreuung.get("marktgebiet")), ("Betreuung seit", v.get("betreuung_seit")),
    ]
    _kopfzeile(ws, ["Feld", "Wert"])
    for r, (feld, wert) in enumerate(felder, start=2):
        _zelle(ws, r, 1, feld).font = Font(bold=True)
        _zelle(ws, r, 2, "–" if wert in (None, "") else wert)
    _breiten(ws)

    gz = wb.create_sheet("Geschäftszahlen")
    _kopfzeile(gz, ["Jahr", "Sparte", "Kreditvolumen", "Anzahl Darlehen"])
    for r, z in enumerate(sorted(v.get("geschaeftszahlen") or [], key=lambda z: z.get("jahr", 0)), start=2):
        _zelle(gz, r, 1, z.get("jahr"))
        _zelle(gz, r, 2, z.get("sparte"))
        _zelle(gz, r, 3, z.get("volumen_eur")).number_format = '#,##0 "€"'
        _zelle(gz, r, 4, z.get("anzahl_darlehen"))
    _breiten(gz)

    pr = wb.create_sheet("Persönliches Profil")
    _kopfzeile(pr, ["Kategorie", "Info", "Notiert am"])
    for r, f in enumerate(profil.get("fakten") or [], start=2):
        _zelle(pr, r, 1, f.get("kategorie_label"))
        _zelle(pr, r, 2, f.get("text"))
        _zelle(pr, r, 3, f.get("datum"))
    _breiten(pr)

    no = wb.create_sheet("Notizen")
    _kopfzeile(no, ["Datum", "Typ", "Titel", "Offene Maßnahmen", "Datei"])
    for r, e in enumerate(eintraege, start=2):
        fm = e.get("frontmatter") or e
        _zelle(no, r, 1, fm.get("datum"))
        _zelle(no, r, 2, fm.get("typ"))
        _zelle(no, r, 3, fm.get("titel"))
        _zelle(no, r, 4, fm.get("offene_massnahmen"))
        _zelle(no, r, 5, e.get("datei"))
    _breiten(no)
    return _als_bytes(wb)
