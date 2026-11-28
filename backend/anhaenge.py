"""Chat-Anhaenge: Datei hochladen, Inhalt auslesen und der KI mit der naechsten Nachricht mitgeben.

Unterstuetzt: PDF (pypdf), Word .docx (ohne Zusatzbibliothek, ZIP+XML), Excel .xlsx (openpyxl),
Text/Markdown/CSV/JSON, Bilder (PNG/JPEG/WEBP/GIF -> direkt als Bild an das Modell).
Gespeichert wird nur der ausgelesene Text bzw. das Bild (Tabelle chat_anhang), gebunden an Chat + Browser-ID.
Der Anhang selbst wird NICHT automatisch in die Akte uebernommen – das schlaegt die KI ggf. als Aenderung vor.
"""
from __future__ import annotations

import base64
import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

MAX_BYTES = 10 * 1024 * 1024        # 10 MB je Datei
MAX_BILD_BYTES = 5 * 1024 * 1024     # Bilder gehen base64-kodiert ans Modell
MAX_ZEICHEN = 40_000                 # ausgelesener Text je Anhang (Rest wird abgeschnitten)
MAX_ANHAENGE_JE_NACHRICHT = 5

BILD_TYPEN = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}
TEXT_ENDUNGEN = {".txt", ".md", ".csv", ".json", ".log", ".eml", ".xml", ".html", ".htm"}
ERLAUBT = {".pdf", ".docx", ".xlsx", *TEXT_ENDUNGEN, *BILD_TYPEN}


class AnhangFehler(Exception):
    def __init__(self, code: str, status: int, meldung: str):
        super().__init__(meldung)
        self.code, self.status, self.meldung = code, status, meldung


@dataclass
class Ausgelesen:
    art: str                  # "text" | "bild"
    text: str | None          # ausgelesener Text (bei Bildern None)
    bild_base64: str | None   # nur bei Bildern
    mime: str
    abgeschnitten: bool = False
    hinweis: str | None = None  # z. B. "PDF enthaelt keinen Text (Scan?)"


def _kuerzen(text: str) -> tuple[str, bool]:
    text = re.sub(r"[ \t]+\n", "\n", text).strip()
    return (text[:MAX_ZEICHEN], True) if len(text) > MAX_ZEICHEN else (text, False)


def _pdf(daten: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise AnhangFehler("ANHANG_PDF_FEHLT", 503, "PDF-Unterstuetzung (pypdf) ist nicht installiert.") from exc
    try:
        reader = PdfReader(io.BytesIO(daten))
        if reader.is_encrypted:
            raise AnhangFehler("ANHANG_GESCHUETZT", 422, "Das PDF ist passwortgeschuetzt.")
        return "\n\n".join(f"[Seite {i}]\n{(seite.extract_text() or '').strip()}" for i, seite in enumerate(reader.pages, start=1))
    except AnhangFehler:
        raise
    except Exception as exc:
        raise AnhangFehler("ANHANG_UNLESBAR", 422, "Das PDF konnte nicht gelesen werden.") from exc


def _docx(daten: bytes) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(io.BytesIO(daten)) as zf:
            wurzel = ElementTree.fromstring(zf.read("word/document.xml"))
    except Exception as exc:
        raise AnhangFehler("ANHANG_UNLESBAR", 422, "Das Word-Dokument konnte nicht gelesen werden (nur .docx).") from exc
    absaetze = []
    for absatz in wurzel.iter(f"{ns}p"):
        text = "".join(t.text or "" for t in absatz.iter(f"{ns}t"))
        if text.strip():
            absaetze.append(text)
    return "\n".join(absaetze)


def _xlsx(daten: bytes) -> str:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(daten), read_only=True, data_only=True)
    except Exception as exc:
        raise AnhangFehler("ANHANG_UNLESBAR", 422, "Die Excel-Datei konnte nicht gelesen werden.") from exc
    teile = []
    for ws in wb.worksheets:
        puffer = io.StringIO()
        writer = csv.writer(puffer, delimiter=";")
        for zeile in ws.iter_rows(values_only=True):
            if any(z is not None for z in zeile):
                writer.writerow(["" if z is None else z for z in zeile])
            if puffer.tell() > MAX_ZEICHEN:
                break
        teile.append(f"[Blatt {ws.title}]\n{puffer.getvalue()}")
    return "\n\n".join(teile)


def _text(daten: bytes) -> str:
    for kodierung in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return daten.decode(kodierung)
        except UnicodeDecodeError:
            continue
    return daten.decode("utf-8", errors="replace")


def auslesen(name: str, daten: bytes) -> Ausgelesen:
    endung = Path(name).suffix.lower()
    if endung not in ERLAUBT:
        raise AnhangFehler("ANHANG_TYP", 415, f"Dateityp {endung or '(ohne Endung)'} wird nicht unterstuetzt. "
                           "Erlaubt: PDF, Word (.docx), Excel (.xlsx), Text/CSV, Bilder (PNG, JPG, WEBP, GIF).")
    if not daten:
        raise AnhangFehler("ANHANG_LEER", 422, "Die Datei ist leer.")
    if len(daten) > MAX_BYTES:
        raise AnhangFehler("ANHANG_ZU_GROSS", 413, f"Die Datei ist groesser als {MAX_BYTES // (1024 * 1024)} MB.")
    if endung in BILD_TYPEN:
        if len(daten) > MAX_BILD_BYTES:
            raise AnhangFehler("ANHANG_ZU_GROSS", 413, f"Bilder duerfen hoechstens {MAX_BILD_BYTES // (1024 * 1024)} MB gross sein.")
        return Ausgelesen("bild", None, base64.b64encode(daten).decode("ascii"), BILD_TYPEN[endung])
    roh = _pdf(daten) if endung == ".pdf" else _docx(daten) if endung == ".docx" else _xlsx(daten) if endung == ".xlsx" else _text(daten)
    text, abgeschnitten = _kuerzen(roh)
    hinweis = None
    if not re.sub(r"\[Seite \d+\]|\s", "", text):
        hinweis = "Die Datei enthaelt keinen auslesbaren Text (bei PDFs oft ein Scan – dann als Bild hochladen)."
    mime = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(endung, "text/plain")
    return Ausgelesen("text", text, None, mime, abgeschnitten, hinweis)


def fuer_modell(nachricht: str, anhaenge: list[dict[str, Any]]) -> list[dict[str, Any]] | str:
    """Baut den Inhalt der Nutzernachricht fuer die Responses-API: Text + Anhaenge (Text bzw. Bild)."""
    if not anhaenge:
        return nachricht
    teile = [nachricht.strip()]
    bilder = []
    for a in anhaenge:
        if a["art"] == "bild" and a.get("bild_base64"):
            teile.append(f"[Anhang „{a['name']}“: Bild, siehe unten]")
            bilder.append({"type": "input_image", "image_url": f"data:{a['mime']};base64,{a['bild_base64']}"})
        else:
            zusatz = " (gekuerzt)" if a.get("abgeschnitten") else ""
            teile.append(f"--- Anhang „{a['name']}“{zusatz} ---\n{a.get('text') or '(kein auslesbarer Text)'}\n--- Ende Anhang ---")
    # Inhalte aus Anhaengen sind DATEN, keine Anweisungen (siehe SYSTEM_INSTRUCTIONS)
    return [{"type": "input_text", "text": "\n\n".join(teile)}, *bilder]
