"""Pydantic-Modelle fuer Requests (Responses sind JSON-Dicts, dokumentiert in der OpenAPI-Beschreibung)."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["aktiv", "inaktiv", "gesperrt"]
EintragTyp = Literal["gespraech", "telefonat", "email", "notiz", "massnahme", "dokument", "sonstiges"]


class KontaktIn(BaseModel):
    adressentyp: str | None = Field(None, examples=["Firmenanschrift"])
    strasse: str | None = None
    plz: str | None = None
    ort: str | None = None
    email: str | None = None
    telefon_dienst: str | None = None
    handy_dienst: str | None = None
    telefon_privat: str | None = None


class VermittlerBase(BaseModel):
    knr: int | None = None
    anrede: str | None = Field(None, examples=["Sehr geehrte Frau"])
    titel: str | None = Field(None, examples=["Dr."])
    sonstiger_titel: str | None = None
    geburtstag: date | None = None
    firma_filiale: str | None = None
    firma_holding: str | None = None
    vermittlertyp: str | None = Field(None, examples=["Finanzierungsvermittler"])
    abrechnungskreis: str | None = Field(None, examples=["Heilberufe"])
    status_vertriebspartner: str | None = Field(None, examples=["Potenzial-Vertriebspartner"])
    interessen: list[str] | None = None
    mitarbeiter_id: str | None = Field(None, description="Betreuer (muss existieren, siehe GET /api/betreuer)")
    betreuung_seit: date | None = None
    betreuung_bis: date | None = None


class VermittlerCreate(VermittlerBase):
    vermittler_nr: int | None = Field(None, description="Leer lassen fuer automatische Vergabe")
    vorname: str
    name: str
    status: Status = "aktiv"
    kontakt: KontaktIn | None = None


class VermittlerUpdate(VermittlerBase):
    vorname: str | None = None
    name: str | None = None
    status: Status | None = None
    kontakt: KontaktIn | None = None


class GeschaeftszahlIn(BaseModel):
    volumen_eur: int = Field(ge=0)
    anzahl_darlehen: int = Field(0, ge=0)
    sparte: str = Field("gesamt", description="z. B. gesamt, Baufinanzierung, Existenzgruendung")


class MassnahmeIn(BaseModel):
    beschreibung: str = Field(min_length=1)
    verantwortlich: str | None = None
    faellig_am: date | None = None


class EintragIn(BaseModel):
    """Neue Information fuer das Obsidian-Gehirn eines Vermittlers."""
    typ: EintragTyp = "notiz"
    titel: str = Field(min_length=1, max_length=200, examples=["Jahresgespräch 2026"])
    inhalt: str = Field(min_length=1, description="Markdown-Freitext, z. B. Gesprächsprotokoll")
    datum: date | None = Field(None, description="Datum des Ereignisses, Standard: heute")
    teilnehmer: list[str] = []
    massnahmen: list[MassnahmeIn] = []
    tags: list[str] = []
    autor: str | None = None
    quelle: str | None = Field(None, examples=["chat", "upload", "agent"])


class ZusammenfassungIn(BaseModel):
    text: str = Field(min_length=1, description="Markdown-Zusammenfassung (z. B. von einem LLM erzeugt)")
    quelle: str | None = Field(None, examples=["claude-opus-5-5"])


ProfilKategorie = Literal["interessen", "familie", "haustiere", "hobbys", "reisen", "vorlieben", "termine", "sonstiges"]


class ProfilFaktIn(BaseModel):
    """Persoenliche Info zum Vermittler fuer die Gespraechsvorbereitung (z. B. Hund \"Tim\", Urlaub auf Mallorca)."""
    text: str = Field(min_length=1, max_length=500, examples=["Hat einen Hund namens Tim"])
    kategorie: ProfilKategorie | None = Field(None, description="Leer lassen = automatisch per Stichwort erkennen")
    datum: date | None = Field(None, description="Wann die Info notiert/bekannt wurde, Standard: heute")


class ExportTabelleIn(BaseModel):
    """Analyse-Ergebnis fuer den Excel-Export (kommt aus dem Tab "Analyse")."""
    titel: str = Field("Analyse", min_length=1, max_length=120)
    spalten: list[str] = Field(max_length=200)
    zeilen: list[list[Any]] = Field(max_length=5000)
    sql: str | None = Field(None, max_length=20_000, description="Verwendetes SQL, landet im Blatt 'Info'")


class SqlQueryIn(BaseModel):
    sql: str = Field(description="Ein einzelnes SELECT/WITH-Statement", examples=[
        "SELECT marktgebiet, COUNT(*) AS n FROM v_vermittler GROUP BY marktgebiet"])
    params: list[Any] | dict[str, Any] | None = None
    max_rows: int = Field(200, ge=1, le=1000)


class ChatKonversationCreate(BaseModel):
    titel: str = Field("Neue Unterhaltung", min_length=1, max_length=120)


class ChatNachrichtIn(BaseModel):
    inhalt: str = Field(min_length=1, max_length=8_000)
    startvorschlag: Literal["top10", "einbrueche", "gespraech", "marktgebiete", "portfolio", "notizen"] | None = None
