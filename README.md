# apoBank Vermittler-Copilot – Backend

SQLite-Datenbank + FastAPI-Backend, über das ein KI-Agent die Vermittler aus der
`Musterliste_apoBank.xlsx` abfragen, iterieren und analysieren kann. Jeder Vermittler
bekommt ein eigenes **Obsidian-„Gehirn“**, in das über die API Wissen geschrieben wird
(Gesprächsprotokolle, Notizen, Maßnahmen, KI-Zusammenfassungen).

## Setup

`Musterliste_apoBank.xlsx` (Hackathon-Daten, nicht im Repo) nach `data/` kopieren, dann:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m backend.import_excel --reset     # Excel -> data/apobank.db + vault/
.venv\Scripts\python -m uvicorn backend.main:app --reload
```

- Swagger-UI: http://127.0.0.1:8000/docs
- OpenAPI: http://127.0.0.1:8000/openapi.json (direkt als Tool-Definition für Agenten nutzbar)
- Obsidian: Ordner `vault/` in Obsidian als Vault öffnen
- Tests: `.venv\Scripts\python -m pytest`

Pfade lassen sich per Umgebungsvariable ändern: `APOBANK_DB_PATH`, `APOBANK_EXCEL_PATH`,
`APOBANK_VAULT_PATH`, `APOBANK_VAULT_NAME` (Name für die `obsidian://`-Links, Standard `vault`).

## Datenmodell (`backend/schema.sql`)

| Tabelle | Inhalt |
|---|---|
| `filiale` | Filial-Nr., Name, Marktgebiet |
| `betreuer` | Mitarbeiter-ID, Kürzel (AP), Name (VPB), Filiale |
| `vermittler` | Stammdaten, Status, Betreuer, Betreuungszeitraum, **`obsidian_pfad` / `obsidian_uri`** |
| `kontakt` | Anschrift, E-Mail, Telefone (1:1) |
| `geschaeftszahlen` | Volumen (EUR) + Anzahl Darlehen je Vermittler/Jahr/**Sparte** (Excel liefert `gesamt`; Baufinanzierung etc. ergänzbar) |
| `obsidian_eintrag` | Protokoll aller über die API geschriebenen Gehirn-Einträge |
| `v_vermittler` (View) | Alles flach in einer Zeile – bequem für Agenten-SQL |

## Obsidian-Gehirn

```
vault/Vermittler/VM-4251/
├── VM-4251.md          Hub-Notiz: Frontmatter, KI-Zusammenfassung, Stammdaten, Eintragsliste, Freie Notizen
└── Eintraege/
    └── 2026-11-20_143005_gespraech_jahresgespraech-2026.md
```

- Bereiche zwischen `<!-- BEGIN:x -->` / `<!-- END:x -->` verwaltet das Backend; alles andere
  (z. B. „Freie Notizen“) bleibt bei Syncs und Re-Importen erhalten.
- Einträge verlinken per `[[VM-4251]]` zurück → Backlinks/Graph in Obsidian funktionieren.
- Maßnahmen werden als Obsidian-Tasks geschrieben: `- [ ] Konditionen schicken 👤 Schumann 📅 2026-12-01`.
- Auch manuell in `Eintraege/` angelegte Notizen werden von der API gelesen.

## Endpunkte (Auszug)

| Zweck | Endpunkt |
|---|---|
| Schema / gültige Filterwerte | `GET /api/schema`, `GET /api/werte` |
| Read-only SQL (nur SELECT/WITH) | `POST /api/sql/query` |
| Suchen, filtern, **iterieren** | `GET /api/vermittler?q=&marktgebiet=&status=&sort=volumen&limit=&offset=` → `next_offset` |
| Profil | `GET /api/vermittler/{nr}` |
| Profil + Gehirn als LLM-Kontext | `GET /api/vermittler/{nr}/kontext` |
| Anlegen / ändern | `POST /api/vermittler`, `PATCH /api/vermittler/{nr}` |
| Geschäftszahlen setzen | `PUT /api/vermittler/{nr}/geschaeftszahlen/{jahr}` |
| Analysen | `GET /api/analytics/ranking`, `/wachstum`, `/ueberblick` |
| **Info zum Gehirn hinzufügen** | `POST /api/vermittler/{nr}/obsidian/eintraege` |
| Gehirn lesen | `GET /api/vermittler/{nr}/obsidian/inhalt?format=text` |
| KI-Zusammenfassung speichern | `PUT /api/vermittler/{nr}/obsidian/zusammenfassung` |
| Volltextsuche in allen Notizen | `GET /api/obsidian/suche?q=` |

Beispiel – Gesprächsprotokoll hinzufügen:

```json
POST /api/vermittler/4251/obsidian/eintraege
{
  "typ": "gespraech",
  "titel": "Jahresgespräch 2026",
  "datum": "2026-11-20",
  "teilnehmer": ["Schumann", "Dr. Baumann"],
  "inhalt": "Interesse an Praxisfinanzierung für zwei Zahnärzte in Paderborn …",
  "massnahmen": [{"beschreibung": "Konditionen schicken", "verantwortlich": "Schumann", "faellig_am": "2026-12-01"}],
  "tags": ["Praxisgründung"],
  "quelle": "chat"
}
```

Typen: `gespraech`, `telefonat`, `email`, `notiz`, `massnahme`, `dokument`, `sonstiges`.

Hinweis: Die Werte für 2026 sind unterjährig; Wachstumsvergleiche besser zwischen abgeschlossenen Jahren.

## Weboberfläche und Copilot

Die Next.js-Oberfläche liegt in `frontend/`: links stehen persistente Chatverläufe, mittig der Copilot und rechts die Partnerakte mit manueller Eingabe. Im lokalen Entwicklungsmodus ruft sie FastAPI auf Port 8000 auf; im Container spricht sie über die gleiche Origin mit `/api`. Der produktive Container liefert den statischen Frontend-Export direkt über FastAPI aus.

### Lokal starten

Terminal 1:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m backend.import_excel --reset
.venv/bin/python -m uvicorn backend.main:app --reload
```

Terminal 2:

```bash
cd frontend
npm ci
npm run dev
```

Danach läuft die Oberfläche auf http://127.0.0.1:3000. Neue Vermittler, Gesprächsnotizen, Anhänge und bestätigte Angaben werden über das Backend in SQLite und dem Obsidian-Vault gespeichert.

### OpenAI konfigurieren

Der API-Key bleibt ausschließlich im Backend. Kopiere `.env.example` nach `.env` und setze den Schlüssel als Umgebungsvariable, bevor der FastAPI-Server startet:

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-5-mini"
```

Der Copilot nutzt die OpenAI Responses API mit ausschließlich lesenden Werkzeugen für Vermittlersuche, Partnerakten, Gesprächsnotizen und Portfolioübersicht. Konkrete Angaben aus einer Nachricht werden nur als Vorschlag angezeigt; erst der Button **„Angaben übernehmen“** speichert sie als Notiz. Ohne Key bleibt die Oberfläche nutzbar und zeigt die erforderliche Konfiguration an.

### AWS / Deployment

`Dockerfile` baut das Next.js-Frontend und startet FastAPI auf Port 80. `buildspec.yml` kann dieses Image wie bisher in ECR veröffentlichen. Für ECS müssen `/app/data` und `/app/vault` persistent gemountet werden, zum Beispiel über EFS; SQLite und hochgeladene Dokumente gehen sonst bei einem Task-Neustart verloren. Schlüssel wie `OPENAI_API_KEY` gehören in ECS Secrets oder Parameter Store, nie in GitHub oder das Docker-Image.

### Lokal mit Docker

Für die gemeinsame lokale Vorschau verwende `docker compose up --build`. Die Compose-Konfiguration bindet `./data` und `./vault` persistent in den Container ein. Liegt beim ersten Start eine Quelldatei unter `data/Musterliste_apoBank.xlsx`, wird sie automatisch in `data/apobank.db` importiert. Eine vorhandene `data/apobank.db` hat immer Vorrang und wird nicht überschrieben.

Wird die Excel-Datei erst nach dem ersten Start bereitgestellt, importiert sie ein Teammitglied bewusst mit:

```bash
docker compose exec apobank-copilot python -m backend.import_excel --excel /app/data/Musterliste_apoBank.xlsx --reset
```

Die Quelldatei und die erzeugte SQLite-Datenbank bleiben aufgrund ihrer Sensibilität außerhalb von Git.
