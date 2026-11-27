"""SQLite-Zugriff: Verbindungen, Schema-Initialisierung und Lese-Helfer."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

from . import obsidian
from .config import settings

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def connect(readonly: bool = False) -> sqlite3.Connection:
    path = Path(settings.db_path)
    if readonly:
        uri = f"file:{quote(path.resolve().as_posix(), safe='/:')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA_SQL)
        _add_missing_columns(conn)
        conn.commit()
    finally:
        conn.close()


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Rein additive Spalten nachruesten, damit bestehende DBs kein --reset (Datenverlust) brauchen."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(chat_konversation)")}
    if "client_id" not in columns:
        conn.execute("ALTER TABLE chat_konversation ADD COLUMN client_id TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_konversation_client "
                 "ON chat_konversation(client_id, aktualisiert_am)")


def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI-Dependency: eine Verbindung pro Request, Commit bei Erfolg."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def split_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def anzeigename(v: dict[str, Any]) -> str:
    return " ".join(p for p in (v.get("titel"), v.get("vorname"), v.get("name")) if p)


def get_vermittler_full(conn: sqlite3.Connection, vermittler_nr: int) -> dict[str, Any] | None:
    """Vollstaendiges, verschachteltes Vermittlerprofil (Stammdaten, Kontakt, Betreuung, Zahlen, Obsidian)."""
    row = conn.execute("SELECT * FROM v_vermittler WHERE vermittler_nr = ?", (vermittler_nr,)).fetchone()
    if row is None:
        return None
    v = dict(row)
    zahlen = rows_to_dicts(conn.execute(
        "SELECT jahr, sparte, volumen_eur, anzahl_darlehen FROM geschaeftszahlen "
        "WHERE vermittler_nr = ? ORDER BY jahr DESC, sparte", (vermittler_nr,)).fetchall())
    n_eintraege = conn.execute(
        "SELECT COUNT(*) FROM obsidian_eintrag WHERE vermittler_nr = ?", (vermittler_nr,)).fetchone()[0]
    return {
        "vermittler_nr": v["vermittler_nr"],
        "knr": v["knr"],
        "anzeigename": anzeigename(v),
        "anrede": v["anrede"],
        "titel": v["titel"],
        "sonstiger_titel": v["sonstiger_titel"],
        "vorname": v["vorname"],
        "name": v["name"],
        "geburtstag": v["geburtstag"],
        "firma_filiale": v["firma_filiale"],
        "firma_holding": v["firma_holding"],
        "vermittlertyp": v["vermittlertyp"],
        "status": v["status"],
        "abrechnungskreis": v["abrechnungskreis"],
        "status_vertriebspartner": v["status_vertriebspartner"],
        "interessen": split_list(v["interessen"]),
        "kontakt": {
            "adressentyp": v["adressentyp"],
            "strasse": v["strasse"],
            "plz": v["plz"],
            "ort": v["ort"],
            "email": v["email"],
            "telefon_dienst": v["telefon_dienst"],
            "handy_dienst": v["handy_dienst"],
            "telefon_privat": v["telefon_privat"],
        },
        "betreuung": {
            "mitarbeiter_id": v["mitarbeiter_id"],
            "kuerzel": v["betreuer_kuerzel"],
            "name": v["betreuer_name"],
            "filial_nr": v["filial_nr"],
            "filiale": v["filiale"],
            "marktgebiet": v["marktgebiet"],
            "seit": v["betreuung_seit"],
            "bis": v["betreuung_bis"],
        },
        "geschaeftszahlen": zahlen,
        "obsidian": {
            "pfad": v["obsidian_pfad"],
            # URI live bilden, damit ein umbenannter Vault (APOBANK_VAULT_NAME) sofort greift
            "uri": obsidian.obsidian_uri(v["obsidian_pfad"]) if v["obsidian_pfad"] else v["obsidian_uri"],
            "profil_pfad": obsidian.profil_rel(vermittler_nr),
            "profil_uri": obsidian.obsidian_uri(obsidian.profil_rel(vermittler_nr)),
            "anzahl_eintraege": n_eintraege,
        },
        "erstellt_am": v["erstellt_am"],
        "geaendert_am": v["geaendert_am"],
    }
