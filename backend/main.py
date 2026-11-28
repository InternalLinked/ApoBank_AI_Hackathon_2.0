"""FastAPI-Backend fuer den apoBank Vermittler-Copiloten.

Start:  uvicorn backend.main:app --reload
Doku:   http://127.0.0.1:8000/docs   (OpenAPI: /openapi.json -> direkt als Tool-Definition fuer Agenten nutzbar)
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from contextlib import asynccontextmanager, closing
from datetime import date
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import aenderungen, analysen, anhaenge, chat_titel, db, excel_export, obsidian, openai_copilot, transcribe, vermittler_links
from .config import settings
from .schemas import (AnalyseNeuIn, ChatKonversationCreate, ChatNachrichtIn, EintragIn, ExportTabelleIn, GeschaeftszahlIn, ProfilFaktIn,
                      SqlQueryIn, VermittlerCreate, VermittlerUpdate, ZusammenfassungIn)

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    with closing(db.connect()) as conn:
        konto, antworten = _startvorschlaege(conn)
    app.state.betreuerkonto = konto
    app.state.startvorschlaege = antworten
    obsidian.link_index.vorwaermen()  # Backlinks fuers Obsidian-Netz im Hintergrund einlesen (EFS ist langsam)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="apoBank Vermittler-Copilot API",
    version="0.1.0",
    description=(
        "Backend fuer einen KI-Agenten: Vermittler-Stammdaten, Kontakte, Betreuer und Geschaeftszahlen "
        "aus SQLite abfragen und iterieren (Pagination ueber `limit`/`offset` -> `next_offset`), "
        "Vertriebsanalysen, read-only SQL sowie ein Obsidian-'Gehirn' pro Vermittler zum Lesen und Ergaenzen "
        "von Wissen (Gespraechsprotokolle, Notizen, Massnahmen, KI-Zusammenfassungen)."
    ),
)
logger = logging.getLogger("apobank")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

FEHLER_CODES = {400: "UNGUELTIGE_ANFRAGE", 404: "NICHT_GEFUNDEN", 405: "METHODE_NICHT_ERLAUBT",
                409: "KONFLIKT", 422: "VALIDIERUNG", 500: "INTERNER_FEHLER"}


def _fehler_json(request: Request, status: int, detail: Any, code: str | None = None,
                 headers: dict[str, str] | None = None, **extra: Any) -> JSONResponse:
    """Einheitliches Fehlerformat: `detail` (wie FastAPI), `fehler_code`, `request_id` fuers Log."""
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status,
        content={"detail": detail, "fehler_code": code or FEHLER_CODES.get(status, f"HTTP_{status}"),
                 "request_id": request_id, **extra},
        headers={**(headers or {}), **({"X-Request-ID": request_id} if request_id else {})},
    )


# Vor CORSMiddleware registriert und damit innerhalb davon: auch 500er tragen CORS-Header,
# sonst sieht der Browser nur "Failed to fetch" statt der Fehlermeldung.
@app.middleware("http")
async def _request_log(request: Request, call_next):
    request.state.request_id = uuid4().hex[:12]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("%s %s -> 500 [%s]", request.method, request.url.path, request.state.request_id)
        return _fehler_json(request, 500, "Interner Serverfehler. Details stehen im Backend-Log.")
    if request.url.path.startswith("/api"):
        dauer_ms = (time.perf_counter() - start) * 1000
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(level, "%s %s -> %s (%.0f ms) [%s]", request.method, request.url.path,
                   response.status_code, dauer_ms, request.state.request_id)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

Conn = sqlite3.Connection


@app.exception_handler(StarletteHTTPException)
def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return _fehler_json(request, exc.status_code, exc.detail, headers=exc.headers)


@app.exception_handler(RequestValidationError)
def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())
    meldung = "; ".join(
        f"{'.'.join(str(p) for p in e.get('loc', []) if p != 'body') or 'Anfrage'}: {e.get('msg', '')}" for e in errors
    )
    return _fehler_json(request, 422, errors, meldung=f"Eingabe ungueltig – {meldung}")


@app.exception_handler(sqlite3.IntegrityError)
def _integrity_error(request: Request, exc: sqlite3.IntegrityError) -> JSONResponse:
    logger.warning("Datenbank-Konflikt [%s]: %s", getattr(request.state, "request_id", "-"), exc)
    return _fehler_json(request, 409, f"Datenbank-Konflikt: {exc}")


def _require(conn: Conn, vermittler_nr: int) -> dict[str, Any]:
    v = db.get_vermittler_full(conn, vermittler_nr)
    if v is None:
        raise HTTPException(404, f"Vermittler {vermittler_nr} nicht gefunden")
    return v


def _latest_year(conn: Conn) -> int:
    return conn.execute("SELECT COALESCE(MAX(jahr), strftime('%Y','now')) FROM geschaeftszahlen").fetchone()[0]


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date) else value


def _partner_summary(vermittler: dict[str, Any] | None) -> dict[str, Any] | None:
    if vermittler is None:
        return None
    betreuung = vermittler.get("betreuung") or {}
    return {
        "vermittler_nr": vermittler["vermittler_nr"],
        "name": vermittler["anzeigename"],
        "company": vermittler.get("firma_filiale") or "Kein Unternehmen hinterlegt",
        "partner_id": f"VM-{vermittler['vermittler_nr']}",
        "relationship_manager": betreuung.get("name") or "Nicht zugeordnet",
        "status": vermittler.get("status", "aktiv"),
    }


def _decode_metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    except json.JSONDecodeError:
        return {}


def _chat_message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "role": row["rolle"],
        "content": row["inhalt"],
        "created_at": row["erstellt_am"],
        "metadata": _decode_metadata(row["metadaten_json"]),
    }


CHAT_KONVERSATION_FIELDS = (
    "c.id, c.titel, c.vermittler_nr, c.aktualisiert_am, "
    "COALESCE((SELECT inhalt FROM chat_nachricht m WHERE m.konversation_id = c.id ORDER BY m.id DESC LIMIT 1), "
    "'Noch keine Nachrichten') AS vorschau"
)


def _chat_konversation(conn: Conn, conversation_id: str) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT {CHAT_KONVERSATION_FIELDS} FROM chat_konversation c WHERE c.id = ?", (conversation_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Chat nicht gefunden")
    return dict(row)


@app.get("/api/health", tags=["Meta"], summary="Laufzeitstatus fuer die Weboberflaeche")
def health(conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    return {
        "status": "ok",
        "openai_configured": bool(settings.openai_api_key),
        "vermittler_count": conn.execute("SELECT COUNT(*) FROM vermittler").fetchone()[0],
    }


# =========================================================================== Meta

TABLE_DOCS = {
    "filiale": "Filialen der apoBank mit Marktgebiet.",
    "betreuer": "Vertriebsmitarbeiter der Bank (VPB), je einer Filiale zugeordnet.",
    "vermittler": "Stammdaten der Vermittler (externe Handelsvertreter). PK vermittler_nr.",
    "kontakt": "Anschrift und Kontaktdaten je Vermittler (1:1).",
    "geschaeftszahlen": "Vermitteltes Kreditvolumen (EUR) und Anzahl Darlehen je Vermittler/Jahr/Sparte. "
                        "Aus der Excel nur sparte='gesamt'. Das laufende Jahr ist unterjaehrig.",
    "obsidian_eintrag": "Protokoll der ueber die API ins Obsidian-Gehirn geschriebenen Eintraege.",
    "v_vermittler": "VIEW: Vermittler + Kontakt + Betreuer + Filiale/Marktgebiet in einer flachen Zeile.",
}


@app.get("/api/schema", tags=["Meta"], summary="Datenbankschema fuer den Agenten")
def get_schema(conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """Tabellen, Views und Spalten inkl. Beschreibung – Grundlage fuer `POST /api/sql/query`."""
    objs = conn.execute(
        "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
        "AND name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    out = []
    for o in objs:
        cols = conn.execute(f"PRAGMA table_info({o['name']})").fetchall()
        out.append({
            "name": o["name"], "typ": o["type"], "beschreibung": TABLE_DOCS.get(o["name"]),
            "spalten": [{"name": c["name"], "typ": c["type"], "pk": bool(c["pk"])} for c in cols],
        })
    return {"objekte": out, "beispiel_abfragen": [
        "SELECT marktgebiet, COUNT(*) n FROM v_vermittler WHERE status='aktiv' GROUP BY marktgebiet",
        "SELECT v.vermittler_nr, v.name, g.volumen_eur FROM v_vermittler v JOIN geschaeftszahlen g "
        "USING(vermittler_nr) WHERE g.jahr=2025 AND v.filiale='Filiale Hamburg' ORDER BY g.volumen_eur DESC LIMIT 10",
    ]}


@app.get("/api/werte", tags=["Meta"], summary="Erlaubte Filterwerte (Kategorien)")
def get_werte(conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """Distinkte Werte der kategorialen Felder, damit der Agent gueltige Filter waehlen kann."""
    fields = ["marktgebiet", "filiale", "status", "vermittlertyp", "status_vertriebspartner",
              "abrechnungskreis", "adressentyp"]
    res: dict[str, Any] = {
        f: [r[0] for r in conn.execute(
            f"SELECT DISTINCT {f} FROM v_vermittler WHERE {f} IS NOT NULL ORDER BY 1").fetchall()]
        for f in fields
    }
    res["jahre"] = [r[0] for r in conn.execute("SELECT DISTINCT jahr FROM geschaeftszahlen ORDER BY 1")]
    res["sparten"] = [r[0] for r in conn.execute("SELECT DISTINCT sparte FROM geschaeftszahlen ORDER BY 1")]
    res["eintrag_typen"] = obsidian.EINTRAG_TYPEN
    return res


@app.post("/api/sql/query", tags=["Meta"], summary="Read-only SQL ausfuehren")
def sql_query(body: SqlQueryIn) -> dict[str, Any]:
    """Fuehrt genau ein lesendes Statement (SELECT/WITH) aus. Schreibzugriffe, PRAGMA und ATTACH sind gesperrt.
    Nutze `GET /api/schema` fuer Tabellen/Spalten."""
    try:
        return db.run_readonly_sql(body.sql, body.params, max_rows=body.max_rows)
    except db.SqlFehler as exc:
        raise HTTPException(400, f"SQL-Fehler: {exc}") from exc


# =========================================================================== Stammdaten

@app.get("/api/filialen", tags=["Stammdaten"])
def list_filialen(conn: Conn = Depends(db.get_conn)) -> list[dict[str, Any]]:
    return db.rows_to_dicts(conn.execute(
        "SELECT f.*, (SELECT COUNT(*) FROM v_vermittler v WHERE v.filial_nr = f.filial_nr) AS anzahl_vermittler "
        "FROM filiale f ORDER BY marktgebiet, name").fetchall())


@app.get("/api/betreuer", tags=["Stammdaten"])
def list_betreuer(filial_nr: int | None = None, marktgebiet: str | None = None,
                  conn: Conn = Depends(db.get_conn)) -> list[dict[str, Any]]:
    sql = ("SELECT b.*, f.name AS filiale, f.marktgebiet, "
           "(SELECT COUNT(*) FROM vermittler v WHERE v.mitarbeiter_id = b.mitarbeiter_id) AS anzahl_vermittler "
           "FROM betreuer b JOIN filiale f USING (filial_nr) WHERE 1=1")
    params: list[Any] = []
    if filial_nr is not None:
        sql += " AND b.filial_nr = ?"; params.append(filial_nr)
    if marktgebiet:
        sql += " AND f.marktgebiet = ?"; params.append(marktgebiet)
    return db.rows_to_dicts(conn.execute(sql + " ORDER BY f.name, b.name", params).fetchall())


SORT_COLUMNS = {
    "vermittler_nr": ["v.vermittler_nr"],
    "name": ["v.name", "v.vorname"],
    "ort": ["v.ort", "v.name"],
    "firma": ["v.firma_filiale"],
    "volumen": ["volumen_eur", "v.vermittler_nr"],
    "anzahl_darlehen": ["anzahl_darlehen", "v.vermittler_nr"],
    "betreuung_seit": ["v.betreuung_seit"],
    "geaendert_am": ["v.geaendert_am"],
}


@app.get("/api/vermittler", tags=["Vermittler"], summary="Vermittler suchen, filtern und seitenweise iterieren")
def list_vermittler(
    q: str | None = Query(None, description="Freitext: Name, Vorname, Firma, Holding, Ort, E-Mail, Nr. "
                                            "(mehrere Woerter = alle muessen passen)"),
    marktgebiet: str | None = None,
    filial_nr: int | None = None,
    filiale: str | None = None,
    mitarbeiter_id: str | None = Query(None, description="Betreuer-ID"),
    betreuer: str | None = Query(None, description="Betreuer-Name (VPB)"),
    status: Literal["aktiv", "inaktiv", "gesperrt"] | None = None,
    vermittlertyp: str | None = None,
    status_vertriebspartner: str | None = None,
    abrechnungskreis: str | None = None,
    ort: str | None = None,
    plz: str | None = Query(None, description="PLZ-Praefix, z. B. '20' fuer Hamburg"),
    interesse: str | None = None,
    jahr: int | None = Query(None, description="Jahr fuer volumen_eur/anzahl_darlehen (Standard: neuestes)"),
    min_volumen: int | None = None,
    max_volumen: int | None = None,
    sort: Literal[tuple(SORT_COLUMNS)] = "vermittler_nr",  # type: ignore[valid-type]
    order: Literal["asc", "desc"] = "asc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    conn: Conn = Depends(db.get_conn),
) -> dict[str, Any]:
    """Liefert eine Seite kompakter Vermittler-Datensaetze. Zum vollstaendigen Iterieren solange mit
    `offset = next_offset` erneut aufrufen, bis `next_offset` null ist."""
    jahr = jahr or _latest_year(conn)
    where, params = ["1=1"], []
    if q:
        for token in q.split():
            like = f"%{token}%"
            where.append("(v.name LIKE ? OR v.vorname LIKE ? OR v.firma_filiale LIKE ? OR v.firma_holding LIKE ? "
                         "OR v.ort LIKE ? OR v.email LIKE ? OR CAST(v.vermittler_nr AS TEXT) = ?)")
            params += [like] * 6 + [token]
    exact = {"v.marktgebiet": marktgebiet, "v.filial_nr": filial_nr, "v.filiale": filiale,
             "v.mitarbeiter_id": mitarbeiter_id, "v.betreuer_name": betreuer, "v.status": status,
             "v.vermittlertyp": vermittlertyp, "v.status_vertriebspartner": status_vertriebspartner,
             "v.abrechnungskreis": abrechnungskreis, "v.ort": ort}
    for col, val in exact.items():
        if val is not None:
            where.append(f"{col} = ? COLLATE NOCASE"); params.append(val)
    if plz:
        where.append("v.plz LIKE ?"); params.append(f"{plz}%")
    if interesse:
        where.append("v.interessen LIKE ?"); params.append(f"%{interesse}%")
    if min_volumen is not None:
        where.append("COALESCE(g.volumen_eur, 0) >= ?"); params.append(min_volumen)
    if max_volumen is not None:
        where.append("COALESCE(g.volumen_eur, 0) <= ?"); params.append(max_volumen)

    base = (
        "FROM v_vermittler v LEFT JOIN (SELECT vermittler_nr, SUM(volumen_eur) AS volumen_eur, "
        "SUM(anzahl_darlehen) AS anzahl_darlehen FROM geschaeftszahlen WHERE jahr = ? AND sparte = 'gesamt' "
        "GROUP BY vermittler_nr) g ON g.vermittler_nr = v.vermittler_nr WHERE " + " AND ".join(where)
    )
    all_params = [jahr] + params
    total = conn.execute(f"SELECT COUNT(*) {base}", all_params).fetchone()[0]
    order_sql = ", ".join(f"{c} {order.upper()}" for c in SORT_COLUMNS[sort])
    rows = conn.execute(
        "SELECT v.vermittler_nr, v.titel, v.vorname, v.name, v.firma_filiale, v.vermittlertyp, v.status, "
        "v.status_vertriebspartner, v.abrechnungskreis, v.plz, v.ort, v.email, v.telefon_dienst, "
        "v.mitarbeiter_id, v.betreuer_name, v.filial_nr, v.filiale, v.marktgebiet, v.obsidian_pfad, "
        "COALESCE(g.volumen_eur, 0) AS volumen_eur, COALESCE(g.anzahl_darlehen, 0) AS anzahl_darlehen "
        f"{base} ORDER BY {order_sql} LIMIT ? OFFSET ?", all_params + [limit, offset]).fetchall()
    next_offset = offset + limit if offset + limit < total else None
    return {"total": total, "limit": limit, "offset": offset, "next_offset": next_offset,
            "jahr_kennzahlen": jahr, "items": db.rows_to_dicts(rows)}


@app.get("/api/vermittler/{vermittler_nr}", tags=["Vermittler"], summary="Vollstaendiges Vermittlerprofil")
def get_vermittler(vermittler_nr: int, conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """`interessen` = DB-Spalte; `interessen_profil` = Interessen aus dem Obsidian-Profil
    (DB-Werte werden dort automatisch uebernommen, per Chat/Obsidian ergaenzte kommen hinzu)."""
    v = _require(conn, vermittler_nr)
    _profil_sicherstellen(v)
    return {**v, "interessen_profil": obsidian.profil_interessen(vermittler_nr)}


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/api/vermittler/{vermittler_nr}/export.xlsx", tags=["Export"],
         summary="Partnerakte als Excel (Stammdaten, Geschaeftszahlen, Profil, Notizen)")
def export_vermittler(vermittler_nr: int, conn: Conn = Depends(db.get_conn)) -> Response:
    v = _require(conn, vermittler_nr)
    _profil_sicherstellen(v)
    v = {**v, "interessen_profil": obsidian.profil_interessen(vermittler_nr)}
    inhalt = excel_export.vermittler(v, obsidian.read_profil(vermittler_nr), obsidian.list_entries(vermittler_nr))
    name = excel_export.dateiname(f"Partnerakte_VM-{vermittler_nr}_{v['anzeigename']}")
    return Response(inhalt, media_type=XLSX_MEDIA_TYPE, headers={"Content-Disposition": excel_export.content_disposition(name)})


@app.post("/api/export/tabelle", tags=["Export"], summary="Tabelle (z. B. Analyse-Ergebnis) als Excel herunterladen")
def export_tabelle(body: ExportTabelleIn) -> Response:
    """Schreibt nichts, speichert nichts – wandelt nur die mitgeschickte Tabelle in eine .xlsx-Datei um."""
    if any(len(zeile) > len(body.spalten) for zeile in body.zeilen):
        raise HTTPException(422, "Eine Zeile hat mehr Werte als Spalten.")
    inhalt = excel_export.tabelle(body.titel, body.spalten, body.zeilen, body.sql)
    return Response(inhalt, media_type=XLSX_MEDIA_TYPE,
                    headers={"Content-Disposition": excel_export.content_disposition(excel_export.dateiname(body.titel))})


def _profil_sicherstellen(v: dict[str, Any]) -> None:
    """Hub + Profil anlegen, falls sie fehlen, und DB-Interessen ins Profil uebernehmen."""
    if not obsidian.abs_path(obsidian.hub_rel(v["vermittler_nr"])).exists():
        obsidian.sync_hub(v)
    else:
        obsidian.ensure_profil(v)


@app.get("/api/vermittler/{vermittler_nr}/kontext", tags=["Vermittler"],
         summary="Profil + Obsidian-Gehirn als ein Kontextpaket fuer KI-Zusammenfassungen")
def get_kontext(vermittler_nr: int, limit_eintraege: int | None = Query(None, ge=1),
                conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    v = _require(conn, vermittler_nr)
    brain = obsidian.read_brain(vermittler_nr, limit=limit_eintraege)
    return {"profil": v, "zusammenfassung": brain["zusammenfassung"],
            "eintraege": [{"datei": e["datei"], **e["frontmatter"], "inhalt": e["inhalt"]} for e in brain["eintraege"]],
            "kontext_text": obsidian.brain_as_text(brain)}


def _write_kontakt(conn: Conn, nr: int, kontakt: dict[str, Any]) -> None:
    if not kontakt:
        return
    cols = list(kontakt)
    conn.execute(
        f"INSERT INTO kontakt (vermittler_nr, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))}) "
        f"ON CONFLICT(vermittler_nr) DO UPDATE SET {', '.join(f'{c} = excluded.{c}' for c in cols)}",
        [nr] + [kontakt[c] for c in cols])


def _vermittler_fields(data: dict[str, Any]) -> dict[str, Any]:
    out = {k: _iso(v) for k, v in data.items() if k != "kontakt"}
    if "interessen" in out and isinstance(out["interessen"], list):
        out["interessen"] = ", ".join(out["interessen"]) or None
    return out


@app.post("/api/vermittler", tags=["Vermittler"], status_code=201, summary="Neuen Vermittler anlegen")
def create_vermittler(body: VermittlerCreate, conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """Legt Stammdaten (+ optional Kontakt) an und erzeugt automatisch das Obsidian-Gehirn."""
    data = _vermittler_fields(body.model_dump(exclude_none=True))
    nr = data.get("vermittler_nr") or conn.execute(
        "SELECT COALESCE(MAX(vermittler_nr), 0) + 1 FROM vermittler").fetchone()[0]
    if conn.execute("SELECT 1 FROM vermittler WHERE vermittler_nr = ?", (nr,)).fetchone():
        raise HTTPException(409, f"Vermittler {nr} existiert bereits")
    if data.get("mitarbeiter_id") and not conn.execute(
            "SELECT 1 FROM betreuer WHERE mitarbeiter_id = ?", (data["mitarbeiter_id"],)).fetchone():
        raise HTTPException(422, f"Betreuer {data['mitarbeiter_id']} unbekannt (siehe GET /api/betreuer)")
    ref = obsidian.reference(nr)
    data.update(vermittler_nr=nr, obsidian_pfad=ref["pfad"], obsidian_uri=ref["uri"])
    conn.execute(f"INSERT INTO vermittler ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                 list(data.values()))
    if body.kontakt:
        _write_kontakt(conn, nr, body.kontakt.model_dump(exclude_none=True))
    v = _require(conn, nr)
    obsidian.sync_hub(v)
    return v


@app.patch("/api/vermittler/{vermittler_nr}", tags=["Vermittler"], summary="Vermittler aendern (Teilupdate)")
def update_vermittler(vermittler_nr: int, body: VermittlerUpdate,
                      conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    _require(conn, vermittler_nr)
    data = _vermittler_fields(body.model_dump(exclude_unset=True))
    if data:
        sets = ", ".join(f"{k} = ?" for k in data)
        conn.execute(f"UPDATE vermittler SET {sets}, geaendert_am = datetime('now') WHERE vermittler_nr = ?",
                     list(data.values()) + [vermittler_nr])
    if body.kontakt is not None:
        _write_kontakt(conn, vermittler_nr, body.kontakt.model_dump(exclude_unset=True))
    v = _require(conn, vermittler_nr)
    obsidian.sync_hub(v)
    return v


@app.get("/api/vermittler/{vermittler_nr}/geschaeftszahlen", tags=["Geschaeftszahlen"])
def get_geschaeftszahlen(vermittler_nr: int, conn: Conn = Depends(db.get_conn)) -> list[dict[str, Any]]:
    return _require(conn, vermittler_nr)["geschaeftszahlen"]


@app.put("/api/vermittler/{vermittler_nr}/geschaeftszahlen/{jahr}", tags=["Geschaeftszahlen"],
         summary="Geschaeftszahlen eines Jahres setzen (Upsert)")
def put_geschaeftszahlen(vermittler_nr: int, jahr: int, body: GeschaeftszahlIn,
                         conn: Conn = Depends(db.get_conn)) -> list[dict[str, Any]]:
    _require(conn, vermittler_nr)
    conn.execute(
        "INSERT INTO geschaeftszahlen (vermittler_nr, jahr, sparte, volumen_eur, anzahl_darlehen) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(vermittler_nr, jahr, sparte) DO UPDATE SET "
        "volumen_eur = excluded.volumen_eur, anzahl_darlehen = excluded.anzahl_darlehen",
        (vermittler_nr, jahr, body.sparte, body.volumen_eur, body.anzahl_darlehen))
    v = _require(conn, vermittler_nr)
    obsidian.sync_hub(v)
    return v["geschaeftszahlen"]


# =========================================================================== Analysen

GRUPPEN = {
    "vermittler": ("v.vermittler_nr", "v.vermittler_nr, v.titel, v.vorname, v.name, v.firma_filiale, "
                                      "v.filiale, v.marktgebiet, v.betreuer_name"),
    "filiale": ("v.filial_nr", "v.filial_nr, v.filiale, v.marktgebiet"),
    "marktgebiet": ("v.marktgebiet", "v.marktgebiet"),
    "betreuer": ("v.mitarbeiter_id", "v.mitarbeiter_id, v.betreuer_name, v.filiale"),
    "vermittlertyp": ("v.vermittlertyp", "v.vermittlertyp"),
    "status_vertriebspartner": ("v.status_vertriebspartner", "v.status_vertriebspartner"),
    "abrechnungskreis": ("v.abrechnungskreis", "v.abrechnungskreis"),
}
Gruppe = Literal[tuple(GRUPPEN)]  # type: ignore[valid-type]


def _analytics_filter(marktgebiet: str | None, filial_nr: int | None, mitarbeiter_id: str | None,
                      status: str | None) -> tuple[str, list[Any]]:
    where, params = [], []
    for col, val in (("v.marktgebiet", marktgebiet), ("v.filial_nr", filial_nr),
                     ("v.mitarbeiter_id", mitarbeiter_id), ("v.status", status)):
        if val is not None:
            where.append(f"{col} = ? COLLATE NOCASE"); params.append(val)
    return (" AND " + " AND ".join(where)) if where else "", params


@app.get("/api/analytics/ranking", tags=["Analysen"], summary="Ranking nach Kreditvolumen")
def ranking(gruppe: Gruppe = "vermittler", jahr: int | None = None,  # type: ignore[valid-type]
            marktgebiet: str | None = None, filial_nr: int | None = None, mitarbeiter_id: str | None = None,
            status: str | None = None, limit: int = Query(10, ge=1, le=500),
            conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """z. B. 'beste Vermittler einer Region': `gruppe=vermittler&marktgebiet=Nord&jahr=2025`."""
    jahr = jahr or _latest_year(conn)
    key, select = GRUPPEN[gruppe]
    flt, params = _analytics_filter(marktgebiet, filial_nr, mitarbeiter_id, status)
    rows = conn.execute(
        f"SELECT {select}, COUNT(DISTINCT v.vermittler_nr) AS anzahl_vermittler, "
        "SUM(g.volumen_eur) AS volumen_eur, SUM(g.anzahl_darlehen) AS anzahl_darlehen, "
        "ROUND(1.0 * SUM(g.volumen_eur) / MAX(SUM(g.anzahl_darlehen), 1)) AS volumen_je_darlehen "
        "FROM v_vermittler v JOIN geschaeftszahlen g ON g.vermittler_nr = v.vermittler_nr "
        f"AND g.jahr = ? AND g.sparte = 'gesamt' WHERE 1=1 {flt} "
        f"GROUP BY {key} ORDER BY volumen_eur DESC LIMIT ?", [jahr] + params + [limit]).fetchall()
    return {"jahr": jahr, "gruppe": gruppe, "items": db.rows_to_dicts(rows)}


@app.get("/api/analytics/wachstum", tags=["Analysen"], summary="Volumenwachstum zwischen zwei Jahren")
def wachstum(von_jahr: int, bis_jahr: int, gruppe: Gruppe = "vermittler",  # type: ignore[valid-type]
             marktgebiet: str | None = None, filial_nr: int | None = None, mitarbeiter_id: str | None = None,
             status: str | None = None, sortierung: Literal["absolut", "prozent"] = "absolut",
             min_basis_eur: int = Query(0, ge=0, description="Mindestvolumen im Basisjahr (gegen Prozent-Ausreisser)"),
             richtung: Literal["desc", "asc"] = "desc", limit: int = Query(10, ge=1, le=500),
             conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """z. B. 'staerkstes Volumenwachstum': `von_jahr=2024&bis_jahr=2025&sortierung=prozent&min_basis_eur=500000`."""
    key, select = GRUPPEN[gruppe]
    flt, params = _analytics_filter(marktgebiet, filial_nr, mitarbeiter_id, status)
    order_col = "delta_eur" if sortierung == "absolut" else "wachstum_pct"
    rows = conn.execute(
        f"SELECT {select}, "
        "SUM(CASE WHEN g.jahr = ? THEN g.volumen_eur ELSE 0 END) AS volumen_von, "
        "SUM(CASE WHEN g.jahr = ? THEN g.volumen_eur ELSE 0 END) AS volumen_bis "
        "FROM v_vermittler v JOIN geschaeftszahlen g ON g.vermittler_nr = v.vermittler_nr "
        f"AND g.jahr IN (?, ?) AND g.sparte = 'gesamt' WHERE 1=1 {flt} GROUP BY {key}",
        [von_jahr, bis_jahr, von_jahr, bis_jahr] + params).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        if d["volumen_von"] < min_basis_eur:
            continue
        d["delta_eur"] = d["volumen_bis"] - d["volumen_von"]
        d["wachstum_pct"] = round(100 * d["delta_eur"] / d["volumen_von"], 1) if d["volumen_von"] else None
        items.append(d)
    valid = sorted((d for d in items if d[order_col] is not None), key=lambda d: d[order_col],
                   reverse=(richtung == "desc"))
    items = valid + [d for d in items if d[order_col] is None]  # ohne Basisvolumen ans Ende
    return {"von_jahr": von_jahr, "bis_jahr": bis_jahr, "gruppe": gruppe, "sortierung": sortierung,
            "items": items[:limit]}


@app.get("/api/analytics/ueberblick", tags=["Analysen"], summary="Portfolio-Kennzahlen")
def ueberblick(marktgebiet: str | None = None, filial_nr: int | None = None, mitarbeiter_id: str | None = None,
               conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    flt, params = _analytics_filter(marktgebiet, filial_nr, mitarbeiter_id, None)
    per_jahr = conn.execute(
        "SELECT g.jahr, SUM(g.volumen_eur) AS volumen_eur, SUM(g.anzahl_darlehen) AS anzahl_darlehen, "
        "SUM(g.volumen_eur > 0) AS aktive_vermittler FROM v_vermittler v JOIN geschaeftszahlen g "
        f"ON g.vermittler_nr = v.vermittler_nr AND g.sparte = 'gesamt' WHERE 1=1 {flt} "
        "GROUP BY g.jahr ORDER BY g.jahr", params).fetchall()

    def count_by(col: str) -> dict[str, int]:
        return {r[0]: r[1] for r in conn.execute(
            f"SELECT {col}, COUNT(*) FROM v_vermittler v WHERE 1=1 {flt} GROUP BY 1 ORDER BY 2 DESC", params)}

    return {
        "anzahl_vermittler": conn.execute(f"SELECT COUNT(*) FROM v_vermittler v WHERE 1=1 {flt}", params).fetchone()[0],
        "kennzahlen_je_jahr": db.rows_to_dicts(per_jahr),
        "nach_status": count_by("v.status"),
        "nach_status_vertriebspartner": count_by("v.status_vertriebspartner"),
        "nach_vermittlertyp": count_by("v.vermittlertyp"),
        "nach_marktgebiet": count_by("v.marktgebiet"),
    }


def _analyse_startantwort(titel: str, beschreibung: str, spalten: list[str], zeilen: list[list[Any]],
                          *, diagramm: bool = False) -> openai_copilot.CopilotReply:
    analysen = []
    if zeilen:
        analysen.append({
            "titel": titel, "sql": "", "spalten": spalten, "zeilen": zeilen, "anzahl": len(zeilen),
            "diagramm": {"typ": "balken" if diagramm else "tabelle",
                         "x": spalten[0], "y": spalten[-1], "einheit": "eur" if diagramm else "keine"},
        })
    return openai_copilot.CopilotReply(
        content=f"**{titel}**\n\n{beschreibung}",
        configured=bool(settings.openai_api_key), analysen=analysen,
    )


_TOP_SQL = (
    "SELECT v.vermittler_nr AS vermittler_nr, TRIM(COALESCE(v.vorname || ' ', '') || v.name) AS Vermittler, "
    "CASE :kennzahl WHEN 'anzahl' THEN g.anzahl_darlehen ELSE g.volumen_eur END AS Wert "
    "FROM v_vermittler v JOIN geschaeftszahlen g ON g.vermittler_nr = v.vermittler_nr "
    "WHERE g.sparte = 'gesamt' AND g.jahr = :jahr AND v.mitarbeiter_id = :konto "
    "AND (CASE :kennzahl WHEN 'anzahl' THEN g.anzahl_darlehen ELSE g.volumen_eur END) IS NOT NULL "
    "ORDER BY CASE :sortierung WHEN 'asc' THEN Wert ELSE -Wert END, v.vermittler_nr LIMIT :limit"
)


def _top_vermittler_analyse(conn: Conn) -> dict[str, Any] | None:
    """Startvorschlag 'Top-Vermittler' mit Dropdowns (Jahr, Anzahl, Kennzahl, Sortierung) – Neuberechnung ohne KI."""
    jahre = [r[0] for r in conn.execute(
        "SELECT DISTINCT jahr FROM geschaeftszahlen WHERE sparte = 'gesamt' ORDER BY jahr DESC").fetchall()][:analysen.MAX_OPTIONEN]
    if not jahre:
        return None
    standard_jahr = 2025 if 2025 in jahre else jahre[0]
    parameter = [
        {"name": "jahr", "label": "Jahr", "standard": str(standard_jahr),
         "optionen": [{"wert": str(j), "label": str(j), "einheit": ""} for j in jahre]},
        {"name": "limit", "label": "Anzahl Vermittler", "standard": "10",
         "optionen": [{"wert": str(n), "label": str(n), "einheit": ""} for n in (5, 10, 25, 50)]},
        {"name": "kennzahl", "label": "Kennzahl", "standard": "volumen", "optionen": [
            {"wert": "volumen", "label": "Kreditvolumen", "einheit": "eur"},
            {"wert": "anzahl", "label": "Anzahl Darlehen", "einheit": "anzahl"}]},
        {"name": "sortierung", "label": "Sortierung", "standard": "desc", "optionen": [
            {"wert": "desc", "label": "Größte zuerst", "einheit": ""},
            {"wert": "asc", "label": "Kleinste zuerst", "einheit": ""}]},
    ]
    basis = {
        "titel_vorlage": "Meine Top {limit} nach {kennzahl} {jahr}", "titel": "Meine Top-Vermittler",
        "sql": _TOP_SQL,
        "feste_werte": {"konto": settings.betreuerkonto_id},
        "diagramm_basis": {"typ": "balken", "x": "Vermittler", "y": "Wert", "einheit": "eur"},
        "parameter": parameter,
    }
    analyse = analysen.ausfuehren(basis)
    return analyse if analyse["zeilen"] else None


# Leitregionen nach erster PLZ-Ziffer – Beispielstaedte fuer die Auswahl
PLZ_REGIONEN = {
    "0": "Dresden, Leipzig", "1": "Berlin, Rostock", "2": "Hamburg, Bremen, Kiel", "3": "Hannover, Kassel",
    "4": "Düsseldorf, Ruhr, Münster", "5": "Köln, Bonn, Aachen", "6": "Frankfurt, Mannheim, Saar",
    "7": "Stuttgart, Karlsruhe", "8": "München, Augsburg", "9": "Nürnberg, Würzburg, Erfurt",
}

_KARTE_SQL = (
    "WITH basis AS ("
    " SELECT v.ort, v.plz, TRIM(COALESCE(v.vorname || ' ', '') || v.name) AS name,"
    " CASE :kennzahl WHEN 'anzahl' THEN g.anzahl_darlehen ELSE g.volumen_eur END AS wert"
    " FROM v_vermittler v JOIN geschaeftszahlen g ON g.vermittler_nr = v.vermittler_nr"
    # Region als 'p0'..'p9' (Text): eine reine Ziffer wuerde als Zahl gebunden und nie gleich SUBSTR(...) sein
    " WHERE g.sparte = 'gesamt' AND g.jahr = :jahr AND (:plz_region = 'alle' OR 'p' || SUBSTR(v.plz, 1, 1) = :plz_region)), "
    "rang AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY ort ORDER BY wert DESC) AS platz FROM basis WHERE wert IS NOT NULL) "
    "SELECT r.ort AS Ort, ROUND(AVG(p.lat), 4) AS lat, ROUND(AVG(p.lon), 4) AS lon, COUNT(*) AS \"Anzahl Vermittler\", "
    "GROUP_CONCAT(CASE WHEN r.platz <= 3 THEN r.name END, ', ') AS \"Top-Vermittler\", SUM(r.wert) AS Wert "
    "FROM rang r JOIN plz_koordinaten p ON p.plz = r.plz GROUP BY r.ort ORDER BY Wert DESC"
)


def _karten_analyse(conn: Conn) -> dict[str, Any] | None:
    """Startvorschlag 'Kartenansicht': Blasen je Ort auf der Deutschlandkarte (Jahr, Kennzahl, Marktgebiet waehlbar)."""
    jahre = [r[0] for r in conn.execute(
        "SELECT DISTINCT jahr FROM geschaeftszahlen WHERE sparte = 'gesamt' ORDER BY jahr DESC").fetchall()][:analysen.MAX_OPTIONEN]
    if not jahre:
        return None
    parameter = [
        {"name": "jahr", "label": "Jahr", "standard": str(2025 if 2025 in jahre else jahre[0]),
         "optionen": [{"wert": str(j), "label": str(j), "einheit": ""} for j in jahre]},
        {"name": "kennzahl", "label": "Kennzahl", "standard": "volumen", "optionen": [
            {"wert": "volumen", "label": "Kreditvolumen", "einheit": "eur"},
            {"wert": "anzahl", "label": "Anzahl Darlehen", "einheit": "anzahl"}]},
        {"name": "plz_region", "label": "PLZ-Region", "standard": "alle",
         "optionen": [{"wert": "alle", "label": "Ganz Deutschland", "einheit": ""},
                      *({"wert": f"p{ziffer}", "label": f"PLZ {ziffer} · {orte}", "einheit": ""}
                        for ziffer, orte in PLZ_REGIONEN.items())]},
    ]
    analyse = analysen.ausfuehren({
        "titel_vorlage": "{kennzahl} {jahr} nach Standort – {plz_region}", "titel": "Kartenansicht",
        "sql": _KARTE_SQL, "parameter": parameter,
        "diagramm_basis": {"typ": "karte", "x": "Ort", "y": "Wert", "einheit": "eur"},
    })
    return analyse if analyse["zeilen"] else None


def _startvorschlaege(conn: Conn) -> tuple[str | None, dict[str, openai_copilot.CopilotReply]]:
    konto = conn.execute("SELECT name FROM betreuer WHERE mitarbeiter_id = ?",
                         (settings.betreuerkonto_id,)).fetchone()
    top = _top_vermittler_analyse(conn) if konto else None
    rueckgaenge = wachstum(2024, 2025, richtung="asc", min_basis_eur=0, limit=10, conn=conn)["items"]
    regionen = ranking(gruppe="marktgebiet", jahr=2025, limit=500, conn=conn)["items"]
    portfolio = ueberblick(conn=conn)

    def name(row: dict[str, Any]) -> str:
        return " ".join(str(row[key]) for key in ("vorname", "name") if row.get(key)) or str(row["vermittler_nr"])

    antworten = {
        "top10": openai_copilot.CopilotReply(
            content=f"**{top['titel']}**\n\n{top['anzahl']} Vermittler aus dem Portfolio von mir." if top else
            ("**Meine Top 10 nach Kreditvolumen 2025**\n\n"
             + ("Für dieses Betreuerkonto liegen 2025 keine Volumendaten vor." if konto else
                "Dem angezeigten Konto ist kein Betreuer zugeordnet.")),
            configured=bool(settings.openai_api_key), analysen=[top] if top else [],
        ),
        "einbrueche": _analyse_startantwort(
            "Größte Volumeneinbrüche 2024 → 2025",
            "Bis zu zehn Vermittler, sortiert nach dem Rückgang in Euro.",
            ["Vermittler", "2024 (EUR)", "2025 (EUR)", "Veränderung (EUR)"],
            [[name(r), r["volumen_von"], r["volumen_bis"], r["delta_eur"]] for r in rueckgaenge if r["delta_eur"] < 0],
            diagramm=True,
        ),
        "marktgebiete": _analyse_startantwort(
            "Kreditvolumen 2025 nach Marktgebiet", "Das Diagramm vergleicht die Marktgebiete nach Kreditvolumen.",
            ["Marktgebiet", "Volumen (EUR)"], [[r["marktgebiet"], r["volumen_eur"]] for r in regionen], diagramm=True,
        ),
        "portfolio": _analyse_startantwort(
            "Portfolio-Überblick", f"Das Portfolio umfasst {portfolio['anzahl_vermittler']} Vermittler.",
            ["Merkmal", "Gruppe", "Vermittler"],
            [[merkmal, gruppe, anzahl] for merkmal, schluessel in
             (("Status", "nach_status"), ("Marktgebiet", "nach_marktgebiet"))
             for gruppe, anzahl in portfolio[schluessel].items()],
        ),
    }

    partner = db.get_vermittler_full(conn, 4251)
    gespraech = "Für Vermittler 4251 liegt keine Partnerakte vor."
    if partner:
        brain = obsidian.read_brain(4251, limit=3)
        zeilen = [f"**Gespräch mit {partner['anzeigename']}**"]
        if partner["geschaeftszahlen"]:
            zahlen = next((r for r in partner["geschaeftszahlen"] if r["jahr"] == 2025 and r["sparte"] == "gesamt"), None)
            if zahlen:
                volumen = f"{zahlen['volumen_eur']:,.0f}".replace(",", ".")
                zeilen.append(f"Kreditvolumen 2025: {volumen} EUR bei {zahlen['anzahl_darlehen']} Darlehen.")
        if brain["zusammenfassung"]:
            zeilen.append(brain["zusammenfassung"])
        notizen = [f"- [{e['frontmatter'].get('titel') or 'Eintrag'}]({obsidian.obsidian_uri(e['datei'])})"
                   for e in brain["eintraege"]]
        zeilen.append("Letzte Einträge:\n" + "\n".join(notizen) if notizen else "Es liegen keine Gesprächsnotizen vor.")
        zeilen.append("**Themen für das Gespräch**\n- Geschäftsentwicklung und Ziele besprechen.\n- Offene Maßnahmen aus den letzten Einträgen klären.")
        gespraech = "\n\n".join(zeilen)
    antworten["gespraech"] = openai_copilot.CopilotReply(
        content=gespraech, configured=bool(settings.openai_api_key), vermittler_nr=4251 if partner else None,
    )

    karte = _karten_analyse(conn)
    antworten["karte"] = openai_copilot.CopilotReply(
        content=(f"**{karte['titel']}**\n\n{karte['anzahl']} Standorte. Je größer die Blase, desto höher der Wert – "
                 "Details beim Darüberfahren." if karte else
                 "**Kartenansicht**\n\nFür die Karte liegen keine Standortdaten vor."),
        configured=bool(settings.openai_api_key), analysen=[karte] if karte else [],
    )
    return (konto["name"] if konto else None), antworten


# =========================================================================== Chat / OpenAI

CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9-]{16,64}$")


def client_id(x_client_id: str | None = Header(None, description="Zufaellige Browser-ID; trennt Chats pro Browser "
                                                                  "(keine Authentifizierung)")) -> str:
    """Chats gehoeren dem Browser, der sie angelegt hat. Ohne gueltige ID kein Zugriff auf Chats."""
    if not x_client_id or not CLIENT_ID_RE.match(x_client_id):
        raise HTTPException(400, "Header X-Client-ID fehlt oder ist ungueltig (16-64 Zeichen, A-Z, 0-9, -).")
    return x_client_id


def _eigener_chat(conn: Conn, conversation_id: str, client: str) -> sqlite3.Row:
    row = conn.execute("SELECT id, titel FROM chat_konversation WHERE id = ? AND client_id = ?",
                       (conversation_id, client)).fetchone()
    if row is None:  # fremde Chats bewusst ebenfalls 404, damit ihre Existenz nicht verraten wird
        raise HTTPException(404, "Chat nicht gefunden")
    return row


@app.get("/api/chat/workspace", tags=["Chat"], summary="Gespeicherte Chatverlaeufe dieses Browsers")
def get_chat_workspace(request: Request, client: str = Depends(client_id), conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    conversations = db.rows_to_dicts(conn.execute(
        f"SELECT {CHAT_KONVERSATION_FIELDS} FROM chat_konversation c WHERE c.client_id = ? "
        "ORDER BY c.aktualisiert_am DESC, c.erstellt_am DESC", (client,)
    ).fetchall())
    messages: dict[str, list[dict[str, Any]]] = {}
    for conversation in conversations:
        rows = conn.execute(
            "SELECT id, rolle, inhalt, metadaten_json, erstellt_am FROM chat_nachricht "
            "WHERE konversation_id = ? ORDER BY id", (conversation["id"],)
        ).fetchall()
        messages[conversation["id"]] = [_chat_message(row) for row in rows]
        # Aktuellen Status der Aenderungsvorschlaege (offen/bestaetigt/verworfen) in die Metadaten spiegeln
        status = dict(conn.execute("SELECT id, status FROM chat_aenderung WHERE konversation_id = ?",
                                   (conversation["id"],)).fetchall())
        # Analysen in der zuletzt gewaehlten Auswahl (Dropdowns) zeigen, nicht im Ursprungszustand
        aktuell = {r["id"]: json.loads(r["analyse_json"]) for r in conn.execute(
            "SELECT id, analyse_json FROM chat_analyse WHERE konversation_id = ?", (conversation["id"],))}
        for message in messages[conversation["id"]]:
            for vorschlag in message["metadata"].get("aenderungsvorschlaege") or []:
                vorschlag["status"] = status.get(vorschlag.get("id"), vorschlag.get("status"))
            if message["metadata"].get("analysen"):
                message["metadata"]["analysen"] = [aktuell.get(a.get("id"), a) for a in message["metadata"]["analysen"]]
    return {
        "conversations": conversations,
        "messages_by_conversation": messages,
        "betreuerkonto": request.app.state.betreuerkonto,
        "openai_configured": bool(settings.openai_api_key),
    }


@app.post("/api/chat/conversations", tags=["Chat"], status_code=201, summary="Neuen Chat anlegen")
def create_chat_conversation(body: ChatKonversationCreate, client: str = Depends(client_id),
                             conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    # Mehrfaches Klicken auf "Neuer Chat" darf keine Liste leerer Unterhaltungen erzeugen.
    empty_conversation = conn.execute(
        "SELECT c.id, c.titel, c.vermittler_nr, c.aktualisiert_am, 'Noch keine Nachrichten' AS vorschau "
        "FROM chat_konversation c WHERE NOT EXISTS ("
        "SELECT 1 FROM chat_nachricht m WHERE m.konversation_id = c.id"
        ") AND c.client_id = ? AND ? = 'Neue Unterhaltung' ORDER BY c.aktualisiert_am DESC, c.erstellt_am DESC LIMIT 1",
        (client, body.titel.strip()),
    ).fetchone()
    if empty_conversation is not None:
        return dict(empty_conversation)

    conversation_id = str(uuid4())
    conn.execute("INSERT INTO chat_konversation (id, titel, client_id) VALUES (?, ?, ?)",
                 (conversation_id, body.titel.strip(), client))
    return _chat_konversation(conn, conversation_id)


@app.delete("/api/chat/conversations/{conversation_id}", tags=["Chat"], status_code=204,
            summary="Chat samt allen Nachrichten endgueltig loeschen")
def delete_chat_conversation(conversation_id: str, client: str = Depends(client_id),
                             conn: Conn = Depends(db.get_conn)) -> Response:
    _eigener_chat(conn, conversation_id, client)
    conn.execute("DELETE FROM chat_nachricht WHERE konversation_id = ?", (conversation_id,))
    conn.execute("DELETE FROM chat_konversation WHERE id = ?", (conversation_id,))
    return Response(status_code=204)


@app.exception_handler(anhaenge.AnhangFehler)
def _anhang_fehler(request: Request, exc: anhaenge.AnhangFehler) -> JSONResponse:
    return _fehler_json(request, exc.status, exc.meldung, exc.code)


def _anhang_kurz(a: dict[str, Any]) -> dict[str, Any]:
    return {"id": a["id"], "name": a["name"], "art": a["art"], "groesse": a["groesse"], "mime": a["mime"]}


def _anhaenge_laden(conn: Conn, conversation_id: str, client: str, ids: list[str]) -> list[dict[str, Any]]:
    """Nur eigene Anhaenge dieses Chats; unbekannte IDs -> 404 (nichts wird still ignoriert)."""
    if not ids:
        return []
    ids = list(dict.fromkeys(ids))
    rows = conn.execute(
        f"SELECT * FROM chat_anhang WHERE konversation_id = ? AND client_id = ? AND id IN ({','.join('?' * len(ids))})",
        [conversation_id, client, *ids]).fetchall()
    gefunden = {r["id"]: dict(r) for r in rows}
    if len(gefunden) != len(ids):
        raise HTTPException(404, "Anhang nicht gefunden – bitte erneut hochladen.")
    return [gefunden[i] for i in ids]


def _mit_frueheren_anhaengen(conn: Conn, row: sqlite3.Row) -> str:
    """Fruehere Nachrichten mit Anhang: Text der Anhaenge mitgeben, damit Rueckfragen dazu funktionieren."""
    meta = _decode_metadata(row["metadaten_json"]) if row["rolle"] == "user" else {}
    ids = [a["id"] for a in meta.get("anhaenge") or []]
    if not ids:
        return row["inhalt"]
    rows = conn.execute(f"SELECT name, art, text FROM chat_anhang WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
    teile = [row["inhalt"]] + [
        f"--- Anhang „{r['name']}“ ---\n{r['text'] if r['art'] == 'text' else '(Bild, wurde in dieser Nachricht gezeigt)'}"
        for r in rows]
    return "\n\n".join(teile)


@app.post("/api/chat/conversations/{conversation_id}/anhaenge", tags=["Chat"], status_code=201,
          summary="Datei fuer die naechste Chat-Nachricht hochladen (PDF, Word, Excel, Text, Bild)")
async def anhang_hochladen(conversation_id: str, datei: UploadFile = File(...), client: str = Depends(client_id),
                           conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """Liest den Inhalt aus und merkt ihn sich; mit der naechsten Nachricht (`anhaenge: [id]`) bekommt ihn die KI."""
    _eigener_chat(conn, conversation_id, client)
    daten = await datei.read(anhaenge.MAX_BYTES + 1)
    name = Path(datei.filename or "anhang").name[:200]
    ausgelesen = anhaenge.auslesen(name, daten)
    anhang_id = uuid4().hex[:12]
    conn.execute(
        "INSERT INTO chat_anhang (id, konversation_id, client_id, name, mime, groesse, art, text, bild_base64, abgeschnitten) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (anhang_id, conversation_id, client, name, ausgelesen.mime, len(daten), ausgelesen.art, ausgelesen.text,
         ausgelesen.bild_base64, int(ausgelesen.abgeschnitten)))
    logger.info("Anhang %s hochgeladen: %s (%s, %d Bytes, %s)", anhang_id, name, ausgelesen.art, len(daten),
                f"{len(ausgelesen.text or '')} Zeichen" if ausgelesen.art == "text" else "Bild")
    return {"id": anhang_id, "name": name, "art": ausgelesen.art, "groesse": len(daten), "mime": ausgelesen.mime,
            "zeichen": len(ausgelesen.text or ""), "abgeschnitten": ausgelesen.abgeschnitten, "hinweis": ausgelesen.hinweis}


@app.post("/api/chat/conversations/{conversation_id}/messages", tags=["Chat"],
          summary="Nachricht speichern und ueber OpenAI mit Datenwerkzeugen beantworten")
def send_chat_message(conversation_id: str, body: ChatNachrichtIn, request: Request, client: str = Depends(client_id),
                      conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    conversation = _eigener_chat(conn, conversation_id, client)

    content = body.inhalt.strip()
    anhaenge_jetzt = _anhaenge_laden(conn, conversation_id, client, body.anhaenge)
    # Der Modellaufruf fuer den ersten Titel laeuft parallel zur Antwort.
    neuer_chat = conversation["titel"] == chat_titel.STANDARD_TITEL and conn.execute(
        "SELECT 1 FROM chat_nachricht WHERE konversation_id = ? LIMIT 1", (conversation_id,),
    ).fetchone() is None
    titel_future = chat_titel.starten(content) if neuer_chat else None
    user_meta = {"anhaenge": [_anhang_kurz(a) for a in anhaenge_jetzt]} if anhaenge_jetzt else None
    conn.execute(
        "INSERT INTO chat_nachricht (konversation_id, rolle, inhalt, metadaten_json) VALUES (?, 'user', ?, ?)",
        (conversation_id, content, json.dumps(user_meta, ensure_ascii=False) if user_meta else None),
    )
    history_rows = conn.execute(
        "SELECT rolle, inhalt, metadaten_json FROM chat_nachricht WHERE konversation_id = ? ORDER BY id DESC LIMIT 16",
        (conversation_id,),
    ).fetchall()
    history = [{"role": row["rolle"], "content": _mit_frueheren_anhaengen(conn, row)} for row in reversed(history_rows)]
    if anhaenge_jetzt:
        history[-1]["content"] = content  # aktuelle Anhaenge (inkl. Bilder) gibt antwort_auf_nachricht selbst mit
    if body.startvorschlag:
        vorbereitet = request.app.state.startvorschlaege[body.startvorschlag]
        reply = openai_copilot.CopilotReply(
            content=vorbereitet.content, configured=vorbereitet.configured, vermittler_nr=vorbereitet.vermittler_nr,
            analysen=[{**analyse, "id": uuid4().hex[:12]} for analyse in vorbereitet.analysen],
        )
    else:
        reply = openai_copilot.antwort_auf_nachricht(conn, history, anhaenge=anhaenge_jetzt)
    # Vermittlernamen klickbar machen ([Name](partner:<nr>) -> Frontend oeffnet die Partnerakte)
    reply.content = vermittler_links.verlinke(
        conn, reply.content, [*reply.erwaehnte_nrs, reply.vermittler_nr, *(k.get("vermittler_nr") for k in reply.kandidaten)])
    partner = _partner_summary(db.get_vermittler_full(conn, reply.vermittler_nr)) if reply.vermittler_nr else None
    # Aenderungsvorschlaege serverseitig ablegen: Bestaetigt wird spaeter nur, was hier gespeichert ist
    # (der Browser kann den Inhalt nicht manipulieren, nur per ID bestaetigen).
    # Analysen ablegen: Grundlage fuer das Neuberechnen ueber die Dropdowns im Tab "Analyse"
    for analyse in reply.analysen:
        conn.execute("INSERT OR REPLACE INTO chat_analyse (id, konversation_id, client_id, analyse_json) VALUES (?, ?, ?, ?)",
                     (analyse["id"], conversation_id, client, json.dumps(analyse, ensure_ascii=False, default=str)))
    vorschlaege = []
    for vorschlag in reply.vorschlaege:
        vorschlag_id = uuid4().hex[:12]
        conn.execute(
            "INSERT INTO chat_aenderung (id, konversation_id, client_id, vermittler_nr, vorschlag_json) VALUES (?, ?, ?, ?, ?)",
            (vorschlag_id, conversation_id, client, vorschlag["vermittler_nr"], json.dumps(vorschlag, ensure_ascii=False)),
        )
        vorschlaege.append({**vorschlag, "id": vorschlag_id, "status": "offen"})
    metadata = {
        "findings": reply.findings,
        "vermittler_nr": reply.vermittler_nr,
        "partner": partner,
        "sources": reply.sources,
        "openai_configured": reply.configured,
        "fehler": reply.fehler,
        "kandidaten": reply.kandidaten,  # Auswahl-Buttons bei mehreren Treffern; bleiben im Verlauf erhalten
        "analysen": reply.analysen,      # SQL + Ergebnis + Diagramm-Angaben fuer den Tab "Analyse"
        "aenderungsvorschlaege": vorschlaege,  # Tab "Aenderungen"; Status kommt beim Laden aus chat_aenderung
        "modell": reply.modell,          # automatisch gewaehltes Modell + Dauer (Anzeige unter der Antwort)
    }
    cursor = conn.execute(
        "INSERT INTO chat_nachricht (konversation_id, rolle, inhalt, metadaten_json) VALUES (?, 'assistant', ?, ?)",
        (conversation_id, reply.content, json.dumps(metadata, ensure_ascii=False)),
    )
    # Startvorschlaege werden im Frontend erst nach 2 s gezeigt.
    ki_titel = chat_titel.abholen(titel_future, 2.0 if body.startvorschlag else chat_titel.WARTEN_S)
    erster_titel = (ki_titel or chat_titel.ersatz(content)) if neuer_chat else None
    title = conn.execute(
        "UPDATE chat_konversation SET titel = CASE WHEN titel = ? THEN COALESCE(?, titel) ELSE titel END, "
        "vermittler_nr = COALESCE(?, vermittler_nr), aktualisiert_am = datetime('now') WHERE id = ? RETURNING titel",
        (chat_titel.STANDARD_TITEL, erster_titel, reply.vermittler_nr, conversation_id),
    ).fetchone()["titel"]
    if titel_future is not None and ki_titel is None and title == erster_titel:
        chat_titel.nachtragen(titel_future, conversation_id, title)
    message = conn.execute(
        "SELECT id, rolle, inhalt, metadaten_json, erstellt_am FROM chat_nachricht WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return {"message": _chat_message(message), "partner": partner, "findings": reply.findings,
            "openai_configured": reply.configured, "fehler": reply.fehler, "kandidaten": reply.kandidaten,
            "analysen": reply.analysen, "aenderungsvorschlaege": vorschlaege, "modell": reply.modell, "titel": title}


@app.post("/api/chat/analysen/{analyse_id}/neu-berechnen", tags=["Chat"],
          summary="Analyse mit anderer Auswahl (Jahr, Top-N, Kennzahl ...) neu berechnen – ohne neue KI-Frage")
def analyse_neu_berechnen(analyse_id: str, body: AnalyseNeuIn, request: Request, client: str = Depends(client_id),
                          conn: Conn = Depends(db.get_conn)) -> Any:
    """Fuehrt das gespeicherte SQL der Analyse read-only mit den gewaehlten, vorher erlaubten Werten aus."""
    row = conn.execute("SELECT analyse_json FROM chat_analyse WHERE id = ? AND client_id = ?", (analyse_id, client)).fetchone()
    if row is None:
        raise HTTPException(404, "Analyse nicht gefunden")
    analyse = json.loads(row["analyse_json"])
    if not analyse.get("parameter"):
        raise HTTPException(409, "Diese Analyse hat keine Auswahlfelder.")
    try:
        neu = analysen.ausfuehren(analyse, body.werte)
    except analysen.AnalyseFehler as exc:
        raise HTTPException(422, str(exc)) from exc
    except db.SqlFehler as exc:
        logger.warning("Analyse %s neu berechnen fehlgeschlagen: %s", analyse_id, exc)
        return _fehler_json(request, 400, f"Die Abfrage konnte nicht ausgefuehrt werden: {exc}", "ANALYSE_SQL")
    conn.execute("UPDATE chat_analyse SET analyse_json = ?, geaendert_am = datetime('now') WHERE id = ?",
                 (json.dumps(neu, ensure_ascii=False, default=str), analyse_id))
    return neu


def _eigener_vorschlag(conn: Conn, vorschlag_id: str, client: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM chat_aenderung WHERE id = ? AND client_id = ?", (vorschlag_id, client)).fetchone()
    if row is None:
        raise HTTPException(404, "Aenderungsvorschlag nicht gefunden")
    if row["status"] != "offen":
        raise HTTPException(409, f"Dieser Vorschlag wurde bereits {row['status']}.")
    return row


@app.post("/api/chat/aenderungen/{vorschlag_id}/bestaetigen", tags=["Chat"],
          summary="Aenderungsvorschlag der KI ausfuehren (nur nach Klick des Nutzers)")
def aenderung_bestaetigen(vorschlag_id: str, request: Request, client: str = Depends(client_id),
                          conn: Conn = Depends(db.get_conn)) -> Any:
    """Prueft, ob sich die Werte seit dem Vorschlag geaendert haben (dann 409, nichts wird ueberschrieben)."""
    row = _eigener_vorschlag(conn, vorschlag_id, client)
    vorschlag = json.loads(row["vorschlag_json"])
    try:
        ergebnis = aenderungen.ausfuehren(conn, vorschlag)
    except aenderungen.AenderungsKonflikt as exc:
        logger.warning("Aenderungsvorschlag %s: Konflikt %s", vorschlag_id, exc.konflikte)
        return _fehler_json(request, 409, exc.konflikte, "AENDERUNG_KONFLIKT",
                            meldung="Die Akte wurde inzwischen geändert – nichts gespeichert. Bitte die KI um einen neuen Vorschlag.")
    conn.execute("UPDATE chat_aenderung SET status = 'bestaetigt', ergebnis_json = ?, entschieden_am = datetime('now') "
                 "WHERE id = ?", (json.dumps(ergebnis, ensure_ascii=False), vorschlag_id))
    logger.info("Aenderungsvorschlag %s fuer VM-%s bestaetigt (%d Aenderungen)",
                vorschlag_id, vorschlag["vermittler_nr"], ergebnis["anzahl"])
    return {"id": vorschlag_id, "status": "bestaetigt", "ergebnis": ergebnis,
            "partner": _partner_summary(db.get_vermittler_full(conn, int(vorschlag["vermittler_nr"])))}


@app.post("/api/chat/aenderungen/{vorschlag_id}/verwerfen", tags=["Chat"], summary="Aenderungsvorschlag verwerfen")
def aenderung_verwerfen(vorschlag_id: str, client: str = Depends(client_id),
                        conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    _eigener_vorschlag(conn, vorschlag_id, client)
    conn.execute("UPDATE chat_aenderung SET status = 'verworfen', entschieden_am = datetime('now') WHERE id = ?",
                 (vorschlag_id,))
    return {"id": vorschlag_id, "status": "verworfen"}


# =========================================================================== Sprache (Amazon Transcribe)

@app.exception_handler(transcribe.TranskriptionsFehler)
def _transkriptions_fehler(request: Request, exc: transcribe.TranskriptionsFehler) -> JSONResponse:
    return _fehler_json(request, exc.status, exc.meldung, exc.code)


@app.post("/api/transkription", tags=["Sprache"],
          summary="Sprachaufnahme (16-bit-PCM, mono) mit Amazon Transcribe in Text umwandeln")
async def transkription(audio: UploadFile = File(..., description="Rohes PCM s16le mono, max. 120 s"),
                        sample_rate: int = Form(16000), sprache: str = Form("de-DE")) -> dict[str, Any]:
    """Der Text wird nur zurueckgegeben, nicht gespeichert – die Oberflaeche setzt ihn ins Eingabefeld."""
    max_bytes = (transcribe.MAX_SEKUNDEN + 1) * 48000 * 2
    pcm = await audio.read(max_bytes + 1)
    if len(pcm) > max_bytes:
        raise transcribe.TranskriptionsFehler("TRANSCRIBE_ZU_LANG", 413, "Die Aufnahme ist zu lang.")
    return await transcribe.transkribieren(pcm, sample_rate, sprache)


# =========================================================================== Obsidian-Gehirn

@app.get("/api/vermittler/{vermittler_nr}/obsidian", tags=["Obsidian"], summary="Obsidian-Referenz + Eintragsliste")
def get_obsidian(vermittler_nr: int, conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    v = _require(conn, vermittler_nr)
    return {**obsidian.reference(vermittler_nr), "vault": str(settings.vault_path),
            "eintraege": [{"datei": e["datei"], **e["frontmatter"]} for e in obsidian.list_entries(vermittler_nr)],
            "anzeigename": v["anzeigename"]}


@app.get("/api/vermittler/{vermittler_nr}/obsidian/inhalt", tags=["Obsidian"],
         summary="Gesamtes Gehirn lesen (Hub + Eintraege)")
def get_obsidian_inhalt(vermittler_nr: int, limit: int | None = Query(None, ge=1),
                        seit: date | None = Query(None, description="Nur Eintraege ab diesem Datum"),
                        format: Literal["json", "text"] = "json", conn: Conn = Depends(db.get_conn)) -> Any:
    """`format=text` liefert ein einzelnes Markdown-Dokument – ideal als LLM-Kontext zum Zusammenfassen."""
    _require(conn, vermittler_nr)
    brain = obsidian.read_brain(vermittler_nr, limit=limit, seit=seit)
    if format == "text":
        return PlainTextResponse(obsidian.brain_as_text(brain), media_type="text/markdown; charset=utf-8")
    return brain


@app.post("/api/vermittler/{vermittler_nr}/obsidian/eintraege", tags=["Obsidian"], status_code=201,
          summary="Information zum Obsidian-Gehirn hinzufuegen")
def add_obsidian_eintrag(vermittler_nr: int, body: EintragIn, conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """Legt eine neue Notiz (Gespraechsprotokoll, Telefonat, Notiz, Massnahme, ...) im Ordner des Vermittlers an,
    verlinkt sie in der Hub-Notiz und protokolliert sie in der Tabelle `obsidian_eintrag`.
    Massnahmen werden als Obsidian-Tasks (`- [ ]`) geschrieben."""
    v = _require(conn, vermittler_nr)
    res = obsidian.add_entry(v, body.model_dump())
    cur = conn.execute(
        "INSERT INTO obsidian_eintrag (vermittler_nr, typ, titel, datum, datei, autor, quelle) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (vermittler_nr, res["typ"], res["titel"], res["datum"], res["datei"], body.autor, body.quelle))
    return {"id": cur.lastrowid, "vermittler_nr": vermittler_nr, **res}


@app.post("/api/vermittler/{vermittler_nr}/dokumente", tags=["Obsidian"], status_code=201,
          summary="Gespaechsnotiz mit Anhang in der Partnerakte ablegen")
async def add_document(
    vermittler_nr: int,
    file: UploadFile = File(...),
    titel: str | None = Form(None),
    inhalt: str | None = Form(None),
    datum: date | None = Form(None),
    teilnehmer: str | None = Form(None),
    massnahmen: str | None = Form(None),
    conn: Conn = Depends(db.get_conn),
) -> dict[str, Any]:
    """Legt einen Anhang lokal ab und verlinkt ihn aus einem Obsidian-Dokumenteintrag."""
    vermittler = _require(conn, vermittler_nr)
    original_name = Path(file.filename or "anhang").name
    suffix = Path(original_name).suffix.lower()
    if suffix not in {".pdf", ".doc", ".docx", ".txt"}:
        raise HTTPException(415, "Erlaubt sind PDF, DOC, DOCX und TXT")
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Die Datei darf maximal 10 MB gross sein")

    folder = settings.upload_path / f"VM-{vermittler_nr}"
    folder.mkdir(parents=True, exist_ok=True)
    saved_name = f"{uuid4().hex}{suffix}"
    destination = folder / saved_name
    destination.write_bytes(content)
    relative_path = destination.relative_to(settings.upload_path.parent).as_posix()
    note_text = (inhalt or "").strip() or "Dokument zur Partnerakte hinzugefuegt."
    note_text += f"\n\n## Anhang\n- `{relative_path}` ({original_name})"
    entry = {
        "typ": "dokument",
        "titel": (titel or original_name).strip(),
        "inhalt": note_text,
        "datum": datum,
        "teilnehmer": [name.strip() for name in (teilnehmer or "").split(",") if name.strip()],
        "massnahmen": [{"beschreibung": step.strip()} for step in (massnahmen or "").splitlines() if step.strip()],
        "tags": ["upload"],
        "autor": "ui",
        "quelle": "upload",
    }
    result = obsidian.add_entry(vermittler, entry)
    cursor = conn.execute(
        "INSERT INTO obsidian_eintrag (vermittler_nr, typ, titel, datum, datei, autor, quelle) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (vermittler_nr, result["typ"], result["titel"], result["datum"], result["datei"], "ui", "upload"),
    )
    return {"id": cursor.lastrowid, "vermittler_nr": vermittler_nr, "upload": relative_path, **result}


@app.put("/api/vermittler/{vermittler_nr}/obsidian/zusammenfassung", tags=["Obsidian"],
         summary="KI-Zusammenfassung in die Hub-Notiz schreiben")
def put_zusammenfassung(vermittler_nr: int, body: ZusammenfassungIn,
                        conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    v = _require(conn, vermittler_nr)
    if not obsidian.abs_path(obsidian.hub_rel(vermittler_nr)).exists():
        obsidian.sync_hub(v)
    obsidian.set_summary(vermittler_nr, body.text, body.quelle)
    return {**obsidian.reference(vermittler_nr), "zusammenfassung": obsidian.read_brain(vermittler_nr)["zusammenfassung"]}


@app.get("/api/vermittler/{vermittler_nr}/obsidian/netz", tags=["Obsidian"],
         summary="Lokaler Obsidian-Graph um einen Vermittler (Knoten + Kanten)")
def get_obsidian_netz(vermittler_nr: int, conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """Hub, Profil mit persoenlichen Infos, Eintraege, Betreuer/Filiale und per Wikilink verbundene Notizen.
    Knoten mit `uri` lassen sich per `obsidian://` in Obsidian oeffnen."""
    v = _require(conn, vermittler_nr)
    _profil_sicherstellen(v)
    return obsidian.netz(v)


@app.get("/api/vermittler/{vermittler_nr}/profil", tags=["Obsidian"],
         summary="Persoenliches Profil (Familie, Haustiere, Urlaub, Hobbys ...) fuer die Gespraechsvorbereitung")
def get_profil(vermittler_nr: int, conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """Liest die Obsidian-Notiz `VM-<nr> Profil.md`, legt sie bei Bedarf an. Auch in Obsidian ergaenzte Zeilen erscheinen."""
    v = _require(conn, vermittler_nr)
    _profil_sicherstellen(v)
    return {"vermittler_nr": vermittler_nr, "anzeigename": v["anzeigename"], **obsidian.read_profil(vermittler_nr)}


@app.post("/api/vermittler/{vermittler_nr}/profil/fakten", tags=["Obsidian"], status_code=201,
          summary="Persoenliche Info zum Vermittler im Obsidian-Profil ablegen")
def add_profil_fakt(vermittler_nr: int, body: ProfilFaktIn, conn: Conn = Depends(db.get_conn)) -> dict[str, Any]:
    """Ohne `kategorie` wird sie per Stichwort erkannt (z. B. "Hund" -> haustiere, "Urlaub" -> reisen)."""
    v = _require(conn, vermittler_nr)
    if not obsidian.abs_path(obsidian.hub_rel(vermittler_nr)).exists():
        obsidian.sync_hub(v)
    return obsidian.add_profil_fakt(v, body.text, body.kategorie, body.datum)


@app.delete("/api/vermittler/{vermittler_nr}/profil/fakten/{fakt_id}", tags=["Obsidian"], status_code=204,
            summary="Persoenliche Info aus dem Profil entfernen")
def delete_profil_fakt(vermittler_nr: int, fakt_id: str, conn: Conn = Depends(db.get_conn)) -> Response:
    _require(conn, vermittler_nr)
    if not re.fullmatch(r"[0-9a-f]{12}", fakt_id) or not obsidian.delete_profil_fakt(vermittler_nr, fakt_id):
        raise HTTPException(404, "Info nicht gefunden (evtl. schon in Obsidian geaendert)")
    return Response(status_code=204)


@app.post("/api/vermittler/{vermittler_nr}/obsidian/sync", tags=["Obsidian"],
          summary="Hub-Notiz aus der Datenbank neu aufbauen")
def sync_obsidian(vermittler_nr: int, conn: Conn = Depends(db.get_conn)) -> dict[str, str]:
    return obsidian.sync_hub(_require(conn, vermittler_nr))


@app.post("/api/obsidian/sync", tags=["Obsidian"], summary="Alle Hub-Notizen neu synchronisieren")
def sync_obsidian_all(conn: Conn = Depends(db.get_conn)) -> dict[str, int]:
    nrs = [r[0] for r in conn.execute("SELECT vermittler_nr FROM vermittler ORDER BY 1")]
    for nr in nrs:
        obsidian.sync_hub(db.get_vermittler_full(conn, nr))
    return {"synchronisiert": len(nrs)}


@app.get("/api/obsidian/suche", tags=["Obsidian"], summary="Volltextsuche ueber alle Vermittler-Notizen")
def search_obsidian(q: str = Query(min_length=2), limit: int = Query(20, ge=1, le=200)) -> list[dict[str, Any]]:
    return obsidian.search(q, limit)


# Die produktive Einzelcontainer-Variante liefert den statischen Next.js-Export
# ueber FastAPI aus. Lokal bleibt `npm run dev` moeglich; die API wird dabei per
# Next.js-Rewrite auf Port 8000 weitergeleitet.
_frontend_out = Path(__file__).resolve().parent.parent / "frontend" / "out"
try:
    from .copilot.router import router as copilot_router
    app.include_router(copilot_router)
except ImportError:
    logger.warning("Der optionale Team-Copilot-Router ist nicht verfügbar.")
if _frontend_out.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_out), html=True), name="frontend")
