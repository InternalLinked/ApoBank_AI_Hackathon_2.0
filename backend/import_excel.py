"""Importiert die Musterliste (Excel) in die SQLite-Datenbank und legt je Vermittler ein Obsidian-Gehirn an.

Aufruf:
    python -m backend.import_excel                 # Standardpfade aus config.py
    python -m backend.import_excel --reset         # DB vorher leeren
    python -m backend.import_excel --excel X.xlsx --no-vault

Der Import ist idempotent (Upsert ueber VermittlerNr); vorhandene Obsidian-Notizen
werden nicht ueberschrieben, nur ihre verwalteten Bloecke aktualisiert.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl

from . import db, obsidian
from .config import settings

# Excel-Spalte -> (Tabelle, DB-Spalte)
COLUMN_MAP: dict[str, tuple[str, str]] = {
    "Marktgebiet": ("filiale", "marktgebiet"),
    "FilialNr": ("filiale", "filial_nr"),
    "Filiale": ("filiale", "name"),
    "Mitarbeiter_ID": ("betreuer", "mitarbeiter_id"),
    "Mitarbeiter_AP": ("betreuer", "kuerzel"),
    "VPB": ("betreuer", "name"),
    "Betreuung_seit": ("vermittler", "betreuung_seit"),
    "Betreuung_bis": ("vermittler", "betreuung_bis"),
    "VermittlerNr": ("vermittler", "vermittler_nr"),
    "Name": ("vermittler", "name"),
    "Vorname": ("vermittler", "vorname"),
    "Titel": ("vermittler", "titel"),
    "Sonstiger_Titel": ("vermittler", "sonstiger_titel"),
    "Firma_Filiale": ("vermittler", "firma_filiale"),
    "Firma_Holding": ("vermittler", "firma_holding"),
    "Vermittlertyp": ("vermittler", "vermittlertyp"),
    "Geburtstag": ("vermittler", "geburtstag"),
    "Status": ("vermittler", "status"),
    "Abrechnungskreis": ("vermittler", "abrechnungskreis"),
    "KNR": ("vermittler", "knr"),
    "Anrede": ("vermittler", "anrede"),
    "Status Vertriebspartner": ("vermittler", "status_vertriebspartner"),
    "Interessen": ("vermittler", "interessen"),
    "Adressentyp": ("kontakt", "adressentyp"),
    "Postleitzahl": ("kontakt", "plz"),
    "Ort": ("kontakt", "ort"),
    "Strasse": ("kontakt", "strasse"),
    "eMail": ("kontakt", "email"),
    "Dienstanschluss": ("kontakt", "telefon_dienst"),
    "Dienst_Handy": ("kontakt", "handy_dienst"),
    "Privatanschluss": ("kontakt", "telefon_privat"),
}
VOLUMEN_RE = re.compile(r"^Volumen in Euro in (\d{4})$")
ANZAHL_RE = re.compile(r"^(?:Anzahl Darlehen |ANZ_DL_)(\d{4})$")


def _clean(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def read_rows(excel_path: Path) -> list[dict[str, Any]]:
    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(it)]
    rows = []
    for raw in it:
        if raw is None or all(v is None for v in raw):
            continue
        rows.append({h: _clean(v) for h, v in zip(header, raw) if h})
    wb.close()
    return rows


def _split(row: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, int]]]:
    parts: dict[str, dict[str, Any]] = {"filiale": {}, "betreuer": {}, "vermittler": {}, "kontakt": {}}
    zahlen: dict[int, dict[str, int]] = {}
    for col, val in row.items():
        if col in COLUMN_MAP:
            table, field = COLUMN_MAP[col]
            parts[table][field] = val
        elif m := VOLUMEN_RE.match(col):
            zahlen.setdefault(int(m.group(1)), {})["volumen_eur"] = int(val or 0)
        elif m := ANZAHL_RE.match(col):
            zahlen.setdefault(int(m.group(1)), {})["anzahl_darlehen"] = int(val or 0)
    if parts["kontakt"].get("plz") is not None:
        parts["kontakt"]["plz"] = str(parts["kontakt"]["plz"])
    return parts, zahlen


def _upsert(conn: sqlite3.Connection, table: str, data: dict[str, Any], key: str) -> None:
    cols = list(data)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != key)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT({key}) DO UPDATE SET {updates}",
        [data[c] for c in cols],
    )


def import_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> list[int]:
    nrs: list[int] = []
    for row in rows:
        parts, zahlen = _split(row)
        nr = int(parts["vermittler"]["vermittler_nr"])
        _upsert(conn, "filiale", parts["filiale"], "filial_nr")
        parts["betreuer"]["filial_nr"] = parts["filiale"]["filial_nr"]
        _upsert(conn, "betreuer", parts["betreuer"], "mitarbeiter_id")

        ref = obsidian.reference(nr)
        v = dict(parts["vermittler"], mitarbeiter_id=parts["betreuer"]["mitarbeiter_id"],
                 obsidian_pfad=ref["pfad"], obsidian_uri=ref["uri"])
        _upsert(conn, "vermittler", v, "vermittler_nr")
        conn.execute("UPDATE vermittler SET geaendert_am = datetime('now') WHERE vermittler_nr = ?", (nr,))
        _upsert(conn, "kontakt", dict(parts["kontakt"], vermittler_nr=nr), "vermittler_nr")

        for jahr, z in zahlen.items():
            conn.execute(
                "INSERT INTO geschaeftszahlen (vermittler_nr, jahr, sparte, volumen_eur, anzahl_darlehen) "
                "VALUES (?, ?, 'gesamt', ?, ?) ON CONFLICT(vermittler_nr, jahr, sparte) DO UPDATE SET "
                "volumen_eur = excluded.volumen_eur, anzahl_darlehen = excluded.anzahl_darlehen",
                (nr, jahr, z.get("volumen_eur", 0), z.get("anzahl_darlehen", 0)),
            )
        nrs.append(nr)
    return nrs


def reset_db() -> None:
    path = Path(settings.db_path)
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()


def run(excel_path: Path | None = None, reset: bool = False, vault: bool = True) -> dict[str, int]:
    excel_path = Path(excel_path or settings.excel_path)
    if reset:
        reset_db()
    db.init_db()
    rows = read_rows(excel_path)
    conn = db.connect()
    try:
        nrs = import_rows(conn, rows)
        conn.commit()
        hubs = 0
        if vault:
            for nr in nrs:
                obsidian.sync_hub(db.get_vermittler_full(conn, nr))
                hubs += 1
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("filiale", "betreuer", "vermittler", "kontakt", "geschaeftszahlen")}
    finally:
        conn.close()
    return {"zeilen_excel": len(rows), "obsidian_hubs": hubs, **counts}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--excel", type=Path, default=None, help="Pfad zur Excel-Datei")
    ap.add_argument("--reset", action="store_true", help="Datenbank vor dem Import loeschen")
    ap.add_argument("--no-vault", action="store_true", help="Keine Obsidian-Notizen erzeugen")
    args = ap.parse_args()
    result = run(args.excel, reset=args.reset, vault=not args.no_vault)
    print(f"DB:    {settings.db_path}")
    print(f"Vault: {settings.vault_path}")
    for k, v in result.items():
        print(f"  {k:18} {v}")


if __name__ == "__main__":
    main()
