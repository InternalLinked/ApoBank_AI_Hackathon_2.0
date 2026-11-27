# AGENTS.md – Leitfaden für KI-Agenten

Dieses Dokument erklärt anderen Agenten (Coding-Agenten **und** Laufzeit-Agenten, die die API nutzen),
wie das Projekt aufgebaut ist, wie man es benutzt und wie man es erweitert.

---

## 1. Worum geht es?

Hackathon-Use-Case **„Vermittler-Copilot“ der apoBank** (CGI AI-Thon 2.0).
Die apoBank arbeitet mit ~3.000 Vermittlern (selbstständige Handelsvertreter) zusammen. Infos zu
Vermittlern, Geschäftszahlen und Gesprächen liegen verteilt in Excel. Ziel: ein agentischer Chatbot,
der Stammdaten, Geschäftszahlen und Gesprächsprotokolle in einer zentralen **Vermittlerakte** bündelt.

MVP-Anforderungen (aus der Aufgabenstellung) und wo sie umgesetzt sind:

| Anforderung | Umsetzung |
|---|---|
| Vermittler in Datenbank speichern | SQLite `data/apobank.db` |
| Stammdaten + Kontaktdaten | Tabellen `vermittler`, `kontakt`, `betreuer`, `filiale` |
| Geschäftszahlen (Kreditvolumen) | Tabelle `geschaeftszahlen` |
| Gesprächsprotokolle / Notizen hochladen | `POST /api/vermittler/{nr}/obsidian/eintraege` → Obsidian-Notiz |
| KI-Analyse von Protokollen | Kontext via `GET /api/vermittler/{nr}/kontext`, Ergebnis via `PUT …/obsidian/zusammenfassung` |
| Chatbasierte Suche/Abfrage | Such-/Filter-Endpunkte, read-only SQL, Volltextsuche |
| Neue Vermittler/Notizen per Chat anlegen | `POST /api/vermittler`, `POST …/obsidian/eintraege` |
| Optional: Vertriebsanalysen | `/api/analytics/ranking`, `/wachstum`, `/ueberblick` |

Ausbaustufen laut Aufgabe: Phase 2 semantische Suche, Phase 3 Maßnahmen-Erkennung,
Phase 4 Besuchsvorbereitung / Next-Best-Action. **Noch nicht umgesetzt** – siehe Abschnitt 9.

> **Hinweis:** Es ist bewusst **kein LLM im Backend** eingebaut. Das Backend ist die Daten- und
> Werkzeugschicht; das Denken/Zusammenfassen macht der aufrufende Agent.

---

## 2. Projektstruktur

```
ApoBank_AI_Hackathon_2.0/
├── backend/
│   ├── config.py         Pfade/Settings (per Env-Variable überschreibbar)
│   ├── schema.sql        Komplettes DB-Schema inkl. View v_vermittler
│   ├── db.py             Verbindungen, init_db, get_vermittler_full()
│   ├── import_excel.py   Excel → SQLite + Obsidian-Hubs (CLI)
│   ├── obsidian.py       Alles rund um das Obsidian-„Gehirn“ (Dateisystem)
│   ├── schemas.py        Pydantic-Request-Modelle
│   └── main.py           FastAPI-App mit allen Endpunkten
├── tests/test_api.py     pytest, läuft auf temporärer DB + temporärem Vault
├── data/
│   ├── Musterliste_apoBank.xlsx   Quelldaten (synthetisch, 1.001 Vermittler; NICHT im Repo – manuell ablegen)
│   └── apobank.db                 generiert (gitignored)
├── vault/                Obsidian-Vault, generiert (gitignored)
├── requirements.txt
├── README.md             Kurzanleitung für Menschen
└── AGENTS.md             dieses Dokument
```

---

## 3. Setup & Befehle

Windows, Python 3.15, virtuelle Umgebung in `.venv`.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m backend.import_excel --reset      # DB + Vault neu aufbauen
.venv\Scripts\python -m uvicorn backend.main:app --reload # Server auf :8000
.venv\Scripts\python -m pytest -q                         # Tests (müssen grün bleiben)
```

Import-Optionen: `--excel <pfad>`, `--reset` (löscht nur die DB, **nicht** den Vault), `--no-vault`.

Umgebungsvariablen (`backend/config.py`):

| Variable | Standard |
|---|---|
| `APOBANK_DB_PATH` | `data/apobank.db` |
| `APOBANK_EXCEL_PATH` | `data/Musterliste_apoBank.xlsx` |
| `APOBANK_VAULT_PATH` | `vault/` |
| `APOBANK_VAULT_NAME` | `vault` (Name in `obsidian://`-Links = Ordnername des Vaults in Obsidian) |

API-Doku zur Laufzeit: `http://127.0.0.1:8000/docs`, Maschinen-lesbar: `/openapi.json`
(kann 1:1 als Tool-Definition für einen Agenten dienen).

---

## 4. Datenmodell

```
filiale (filial_nr PK, name, marktgebiet)
   ▲
betreuer (mitarbeiter_id PK, kuerzel, name, filial_nr FK)
   ▲
vermittler (vermittler_nr PK, knr UNIQUE, …, mitarbeiter_id FK, obsidian_pfad, obsidian_uri)
   ├── kontakt (vermittler_nr PK/FK, 1:1)
   ├── geschaeftszahlen (vermittler_nr, jahr, sparte) PK
   └── obsidian_eintrag (id PK, vermittler_nr FK, …)
```

### Mapping Excel → DB

| Excel-Spalte | DB |
|---|---|
| Marktgebiet, FilialNr, Filiale | `filiale.marktgebiet`, `.filial_nr`, `.name` |
| Mitarbeiter_ID, Mitarbeiter_AP, VPB | `betreuer.mitarbeiter_id`, `.kuerzel`, `.name` |
| VermittlerNr, KNR | `vermittler.vermittler_nr`, `.knr` |
| Name, Vorname, Titel, Sonstiger_Titel, Anrede, Geburtstag | `vermittler.*` |
| Firma_Filiale, Firma_Holding, Vermittlertyp | `vermittler.*` |
| Status, Abrechnungskreis, Status Vertriebspartner, Interessen | `vermittler.status`, `.abrechnungskreis`, `.status_vertriebspartner`, `.interessen` |
| Betreuung_seit, Betreuung_bis | `vermittler.betreuung_seit`, `.betreuung_bis` |
| Adressentyp, Strasse, Postleitzahl, Ort | `kontakt.adressentyp`, `.strasse`, `.plz`, `.ort` |
| eMail, Dienstanschluss, Dienst_Handy, Privatanschluss | `kontakt.email`, `.telefon_dienst`, `.handy_dienst`, `.telefon_privat` |
| `Volumen in Euro in JJJJ`, `Anzahl Darlehen JJJJ` / `ANZ_DL_JJJJ` | `geschaeftszahlen(jahr=JJJJ, sparte='gesamt')` |

Jahres-Spalten werden per Regex erkannt (`import_excel.py`: `VOLUMEN_RE`, `ANZAHL_RE`) – neue Jahre
in der Excel werden also automatisch importiert.

### Wichtige Werte / Fakten zu den Daten

- 1.001 Vermittler, 30 Filialen, 93 Betreuer, 5 Marktgebiete (Nord, Ost, Süd, West, Mitte), Jahre 2023–2026.
- `status` ∈ `aktiv | inaktiv | gesperrt` (CHECK-Constraint).
- `status_vertriebspartner` z. B. Fokus-, Standard-, Potenzial-, Ruhender Vertriebspartner.
- `interessen` ist ein **kommagetrennter String** in der DB; die API liefert/nimmt eine Liste.
- Datumswerte sind ISO-Strings (`YYYY-MM-DD`).
- **2026 ist unterjährig** – Wachstumsvergleiche besser zwischen abgeschlossenen Jahren.
- `sparte` ist aktuell immer `gesamt`. Alle Abfragen/Analysen filtern auf `sparte = 'gesamt'`.
  Werden Sparten (Baufinanzierung, Existenzgründung, …) ergänzt, muss weiterhin eine `gesamt`-Zeile
  gepflegt werden – sonst fehlen die Werte in Listen und Analysen.
- `v_vermittler` (View) = Vermittler + Kontakt + Betreuer + Filiale flach; erste Wahl für SQL-Abfragen.

---

## 5. API-Referenz (für Laufzeit-Agenten)

Basis: `http://127.0.0.1:8000`. Alle Antworten JSON (außer `format=text`).

### Orientierung
| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/schema` | Tabellen, Views, Spalten, Beispiel-SQL |
| GET | `/api/werte` | Gültige Filterwerte (Marktgebiete, Filialen, Status, Typen, Jahre, Eintragstypen) |
| POST | `/api/sql/query` | `{"sql": "...", "params": [...], "max_rows": 200}` – nur ein SELECT/WITH |

Read-only-SQL ist doppelt abgesichert: DB im `mode=ro` geöffnet + SQLite-Authorizer (nur SELECT/READ/
FUNCTION). PRAGMA, ATTACH, Schreibbefehle und Mehrfach-Statements → HTTP 400. Timeout 5 s.

### Vermittler
| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/vermittler` | Suchen/Filtern/Iterieren (s. u.) |
| GET | `/api/vermittler/{nr}` | Vollprofil (verschachtelt: kontakt, betreuung, geschaeftszahlen, obsidian) |
| GET | `/api/vermittler/{nr}/kontext` | Profil + Zusammenfassung + alle Einträge + `kontext_text` für LLM |
| POST | `/api/vermittler` | Anlegen (Pflicht: `vorname`, `name`; `vermittler_nr` leer = automatisch) |
| PATCH | `/api/vermittler/{nr}` | Teilupdate inkl. `kontakt` |
| GET | `/api/vermittler/{nr}/geschaeftszahlen` | Zahlen aller Jahre |
| PUT | `/api/vermittler/{nr}/geschaeftszahlen/{jahr}` | Upsert `{volumen_eur, anzahl_darlehen, sparte}` |
| GET | `/api/filialen`, `/api/betreuer` | Stammdaten der Bank (mit Anzahl Vermittler) |

`GET /api/vermittler` – Parameter:
`q` (Freitext; mehrere Wörter = UND), `marktgebiet`, `filial_nr`, `filiale`, `mitarbeiter_id`,
`betreuer`, `status`, `vermittlertyp`, `status_vertriebspartner`, `abrechnungskreis`, `ort`,
`plz` (Präfix), `interesse`, `jahr` (für Kennzahlen, Standard: neuestes), `min_volumen`, `max_volumen`,
`sort` (`vermittler_nr|name|ort|firma|volumen|anzahl_darlehen|betreuung_seit|geaendert_am`),
`order` (`asc|desc`), `limit` (1–500, Std. 50), `offset`.

Antwort: `{total, limit, offset, next_offset, jahr_kennzahlen, items[]}`.

**Iterieren über alle Datensätze:**
```python
offset = 0
while offset is not None:
    page = GET("/api/vermittler", limit=200, offset=offset, **filter)
    for item in page["items"]:
        ...                     # item = kompakter Datensatz, Details via /api/vermittler/{nr}
    offset = page["next_offset"]
```

### Analysen
| Pfad | Beispiel |
|---|---|
| `GET /api/analytics/ranking` | `?gruppe=vermittler&marktgebiet=Nord&jahr=2025&limit=10` – beste Vermittler einer Region |
| `GET /api/analytics/wachstum` | `?von_jahr=2024&bis_jahr=2025&gruppe=filiale&sortierung=prozent&min_basis_eur=500000` |
| `GET /api/analytics/ueberblick` | `?marktgebiet=Süd` – Summen je Jahr, Verteilungen |

`gruppe` ∈ `vermittler | filiale | marktgebiet | betreuer | vermittlertyp | status_vertriebspartner | abrechnungskreis`.
Filter: `marktgebiet`, `filial_nr`, `mitarbeiter_id`, `status`.

### Obsidian-Gehirn
| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/vermittler/{nr}/obsidian` | Pfad, `obsidian://`-URI, Liste der Einträge (nur Metadaten) |
| GET | `/api/vermittler/{nr}/obsidian/inhalt` | Hub + Einträge; `?format=text` = ein Markdown-Dokument; `?limit=`, `?seit=YYYY-MM-DD` |
| POST | `/api/vermittler/{nr}/obsidian/eintraege` | **Neue Information hinzufügen** |
| PUT | `/api/vermittler/{nr}/obsidian/zusammenfassung` | `{text, quelle}` – KI-Zusammenfassung in Hub schreiben |
| POST | `/api/vermittler/{nr}/obsidian/sync` | Hub aus DB neu aufbauen |
| POST | `/api/obsidian/sync` | Alle Hubs neu aufbauen |
| GET | `/api/obsidian/suche?q=` | Volltextsuche über alle Notizen (Einträge vor Hubs) |

Body für `POST …/eintraege`:
```json
{
  "typ": "gespraech",
  "titel": "Jahresgespräch 2026",
  "inhalt": "Markdown-Freitext …",
  "datum": "2026-11-20",
  "teilnehmer": ["Schumann", "Dr. Baumann"],
  "massnahmen": [{"beschreibung": "Konditionen schicken", "verantwortlich": "Schumann", "faellig_am": "2026-12-01"}],
  "tags": ["Praxisgründung"],
  "autor": "agent",
  "quelle": "chat"
}
```
`typ` ∈ `gespraech | telefonat | email | notiz | massnahme | dokument | sonstiges` (Std. `notiz`).
Nur `titel` und `inhalt` sind Pflicht; `datum` Standard = heute.

Fehlercodes: 404 Vermittler unbekannt, 409 Konflikt (doppelte Nr./KNR), 422 Validierung
(z. B. unbekannte `mitarbeiter_id`), 400 ungültiges SQL.

---

## 6. Typische Agenten-Workflows

**„Fasse Vermittler X zusammen“**
1. Vermittler finden: `GET /api/vermittler?q=Baumann Paderborn`
2. `GET /api/vermittler/{nr}/kontext` → `kontext_text` ans LLM geben
3. Ergebnis speichern: `PUT /api/vermittler/{nr}/obsidian/zusammenfassung`

**„Ich hatte gerade ein Gespräch mit X …“ (Protokoll per Chat)**
1. Vermittler identifizieren (bei mehreren Treffern beim Nutzer nachfragen)
2. Aus dem Freitext `titel`, `teilnehmer`, `massnahmen` extrahieren
3. **Vor dem Schreiben Bestätigung des Nutzers einholen** (Vorgabe der Aufgabe: „nach Bestätigung hochgeladen“)
4. `POST /api/vermittler/{nr}/obsidian/eintraege`

**„Bereite meinen Termin mit X vor“**
`GET …/kontext` + `GET /api/analytics/wachstum?gruppe=vermittler&…` für Einordnung; offene Maßnahmen
stehen als `- [ ]` in den Einträgen (`offene_massnahmen` im Frontmatter).

**Analysefragen („beste Vermittler im Süden 2025“)**
Erst die Analytics-Endpunkte probieren; für alles Speziellere `GET /api/schema` lesen und
`POST /api/sql/query` mit `v_vermittler` + `geschaeftszahlen` nutzen.

**Alle Vermittler abarbeiten (Batch)**
Pagination wie in Abschnitt 5; pro Vermittler `kontext` holen, verarbeiten, Ergebnis zurückschreiben.

---

## 7. Obsidian-Konventionen (wichtig, nicht brechen!)

```
vault/
└── Vermittler/
    └── VM-<vermittler_nr>/
        ├── VM-<vermittler_nr>.md        Hub-Notiz
        └── Eintraege/
            └── <YYYY-MM-DD>_<HHMMSS>_<typ>_<slug>.md
```

- **Ein** Vault für alle, **ein** Ordner pro Vermittler. Der Dateiname `VM-<nr>` ist vault-weit eindeutig,
  dadurch funktioniert `[[VM-4251]]` überall.
- In der DB: `vermittler.obsidian_pfad` = `Vermittler/VM-<nr>/VM-<nr>.md` (relativ zum Vault),
  `vermittler.obsidian_uri` = `obsidian://open?vault=<name>&file=…`.
- **Hub-Notiz** enthält verwaltete Blöcke:
  ```
  <!-- BEGIN:zusammenfassung --> … <!-- END:zusammenfassung -->   ← PUT …/zusammenfassung
  <!-- BEGIN:stammdaten -->      … <!-- END:stammdaten -->        ← aus DB bei jedem Sync
  <!-- BEGIN:eintraege -->       … <!-- END:eintraege -->         ← aus Dateien in Eintraege/
  ```
  Alles **außerhalb** der Blöcke (v. a. „## Freie Notizen“) wird nie überschrieben.
  Das **Frontmatter** des Hubs wird dagegen bei jedem Sync komplett neu geschrieben.
- **Eintrags-Notizen**: Frontmatter (`typ`, `titel`, `datum`, `vermittler_nr`, `vermittler: "[[VM-nr]]"`,
  `teilnehmer`, `autor`, `quelle`, `offene_massnahmen`, `tags`, `erstellt_am`), dann `## Inhalt`
  und ggf. `## Maßnahmen` als Tasks: `- [ ] Text 👤 Person 📅 YYYY-MM-DD` (Obsidian-Tasks-Format).
- Frontmatter-Werte werden als **JSON** geschrieben (gültiges YAML, kein PyYAML nötig) und von
  `obsidian.parse_frontmatter` auch so gelesen. Beim manuellen Anlegen von Einträgen dieselbe Form nutzen.
- **Quelle der Wahrheit**: Für die Eintragsliste ist das **Dateisystem** maßgeblich (auch manuell
  in `Eintraege/` angelegte Notizen werden gelesen). Die Tabelle `obsidian_eintrag` protokolliert nur
  API-Schreibvorgänge (praktisch für SQL-Auswertungen, aber nicht vollständig).
- Alle Pfade laufen über `obsidian.abs_path()`, das Path-Traversal aus dem Vault heraus verhindert.
- Re-Import (`import_excel`) aktualisiert nur verwaltete Blöcke – Einträge und freie Notizen bleiben.

---

## 8. Regeln für Coding-Agenten

- Nach jeder Änderung `.venv\Scripts\python -m pytest -q` ausführen; Tests nutzen `tmp_path` und
  patchen `settings` – **nie** gegen `data/apobank.db` oder `vault/` testen.
- Schemaänderungen in `backend/schema.sql` (nur `CREATE … IF NOT EXISTS`; es gibt keine Migrationen –
  bei inkompatiblen Änderungen `import_excel --reset`). Die View `v_vermittler` bei neuen Spalten mitpflegen
  (View vorher droppen, da `IF NOT EXISTS` sie sonst nicht ersetzt).
- SQL immer parametrisiert. Dynamische Spaltennamen nur aus Whitelists (`SORT_COLUMNS`, `GRUPPEN`).
- Nach jeder Änderung an Vermittler-Daten `obsidian.sync_hub(db.get_vermittler_full(conn, nr))`
  aufrufen, damit der Hub aktuell bleibt.
- Verwaltete Blöcke nur über `_replace_block` ändern; Text außerhalb nie anfassen.
- Neuer Eintragstyp → `EintragTyp` in `schemas.py` **und** `EINTRAG_TYPEN` in `obsidian.py` ergänzen.
- Neue Endpunkte mit `summary`/Docstring versehen – das landet in `/openapi.json` und ist damit
  die Tool-Beschreibung für Laufzeit-Agenten.
- Sprache: Fachbegriffe, Feldnamen und API auf Deutsch (ohne Umlaute in Bezeichnern).
- Datenschutz: Die Daten sind synthetisch, aber wie echte Kundendaten behandeln – keine Inhalte an
  externe Dienste senden, ohne dass der Nutzer zustimmt.

---

## 9. Offene Punkte / nächste Ausbaustufen

| Phase | Idee | Anknüpfungspunkt |
|---|---|---|
| 1 | Chat-Frontend / Agent mit Tool-Use auf Basis von `/openapi.json` | neues Modul, z. B. `agent/` |
| 1 | Upload von Dateien (PDF/DOCX-Protokolle) | neuer Endpunkt → Text extrahieren → `obsidian.add_entry` |
| 2 | Semantische Suche über Notizen | `obsidian.search` durch Embeddings + Vektorindex ersetzen |
| 3 | Maßnahmen automatisch erkennen, Wiedervorlagen | LLM füllt `massnahmen`; offene Tasks aus Einträgen parsen, Endpunkt `GET /api/massnahmen` |
| 4 | Besuchsvorbereitung, Potenzial-/Risikoanalyse, Next-Best-Action | Kombination aus `kontext` + `analytics`; Kriterien definieren |
| – | Zielerreichung der Geschäftsplanung | braucht Plandaten → Tabelle `planzahlen(vermittler_nr|filial_nr, jahr, sparte, ziel_eur)` |
| – | Authentifizierung | aktuell keine; vor jedem nicht-lokalen Betrieb ergänzen |
| – | Löschen von Vermittlern | bewusst nicht implementiert |

---

## 10. KI-Copilot (`backend/copilot/`)

Die Agenten- und LLM-Schicht aus Abschnitt 9, Phase 1, liegt als eigenständiges Modul in `backend/copilot/`.
Es ändert keine bestehenden Dateien. Details und die Frontend-Anbindung stehen in `backend/copilot/README.md`.

- Start inkl. Chat-Endpunkten: `.venv\Scripts\python -m uvicorn backend.copilot.app:app --reload`
  (Team-API + `/api/copilot/*`)
- Synthetische Demo-Daten: `.venv\Scripts\python -m backend.copilot.demo_daten --neu`
- Modell austauschbar über `LLM_PROVIDER` (`fake` offline | `bedrock`), `LLM_MODEL_ID`, `AWS_REGION` (Sandbox: us-west-2/us-east-1).
- Regeln:
  - Das Modell rechnet nicht, alle Zahlen kommen aus SQL.
  - Bei Mehrdeutigkeit fragt der Agent nach.
  - Geschrieben wird nur über Entwürfe und den Endpunkt `…/entwuerfe/{id}/bestaetigen`, den ausschließlich die Oberfläche
    nach einem Klick des Nutzers aufruft.
  - Die Schreib-Endpunkte des Backends nie direkt als Modellwerkzeuge freigeben.
- Zugangsdaten nie ins Repo.
  - AWS nur über die SDK-Standardkette mit einer Datei außerhalb des Repos.
  - Daten aus der Kundendatei gehen nur mit Freigabe an Modelle außerhalb der EU (`COPILOT_DATENQUELLE`, `FREIGABE_KUNDENDATEN_US`).
