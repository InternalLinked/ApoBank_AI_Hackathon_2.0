# KI-Copilot (`backend/copilot`)

Agentenschicht für den Vermittler-Copiloten. Baut auf dem bestehenden Backend auf (Schema, `backend.db`, Obsidian-Gehirn)
und **ändert keine bestehenden Dateien**.

```
Frontend ──HTTP──► /api/copilot/chat ──► Agent (Werkzeugschleife) ──► Werkzeuge ──► SQLite (v_vermittler, geschaeftszahlen)
                                            │                              └──────► Obsidian-Gehirn (Einträge, Maßnahmen)
                                            └─► LLM-Schnittstelle: Amazon Bedrock (Converse-API) | Offline-Modell (fake)
Speichern: Entwurf ──► Nutzer klickt „Bestätigen“ ──► /api/copilot/entwuerfe/{id}/bestaetigen ──► Team-Funktionen
           (add_obsidian_eintrag, update_vermittler, create_vermittler)
```

## Grundregeln

- **Das Modell steuert, SQL rechnet.** Zahlen kommen nur aus parametrisierten Abfragen über eine schreibgeschützte Verbindung.
  Es gibt kein freies SQL des Modells und keine Lösch-Werkzeuge.
- **Rückfragen statt Raten:**
  - Namensdubletten führen zu einer Kandidatenauswahl mit Nummer, Firma und Marktgebiet.
  - Bei „die besten …“ fragt der Agent nach Kennzahl und Jahr.
  - Bei „aus 2024“ fragt er, ob Betreuungsbeginn, im Jahr betreut oder Geschäft im Jahr gemeint ist.
- **Sonderfälle**, die das Backend nicht abdeckt:
  - Umlaute und Tippfehler in Namen
  - Gleichstände im Ranking und Statushinweise (z. B. gesperrt)
  - unterjährige Jahre werden gekennzeichnet
  - Wachstum ab null wird als „neu“ ausgewiesen
- **Speichern nur nach Bestätigung.** Werkzeuge erzeugen Entwürfe. Die Bestätigung ist ein HTTP-Aufruf der Oberfläche und
  kein Werkzeug des Modells. Ein Entwurf wird nie doppelt gespeichert.
- **Dauerhaftes Gedächtnis.** Bestätigte Notizen landen als Obsidian-Eintrag mit Maßnahmen-Tasks im Team-Gehirn.
  Sie sind nach einem Neustart und in neuen Sitzungen abrufbar.
- **Notizanalyse ohne Werkzeugzugriff.** Anweisungen im Notiztext werden nicht befolgt, sondern als Auffälligkeit gemeldet.
- **Austauschbar.** Das Modell wird über `LLM_PROVIDER` gewählt. Ein weiterer Anbieter braucht nur einen Adapter in `llm/`.

## Starten

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m backend.copilot.demo_daten --neu      # synthetische Demo-Daten (900000+), Vault vorher leeren
.venv\Scripts\python -m uvicorn backend.copilot.app:app --reload   # Team-API + /api/copilot/*
.venv\Scripts\python -m backend.copilot.cli                    # oder: Chat im Terminal (Backup)
.venv\Scripts\python -m pytest -q                               # alle Tests (Team + Copilot)
```

Konfiguration per Umgebung oder lokaler `.env` (nie committen):

| Variable | Bedeutung |
|---|---|
| `LLM_PROVIDER` | `fake` (Standard, offline) oder `bedrock` |
| `LLM_MODEL_ID` | z. B. `us.anthropic.claude-sonnet-5-5`; verfügbare IDs mit `python -m backend.copilot.bedrock_check` ermitteln |
| `AWS_REGION` | Workshop-Sandbox: `us-west-2` oder `us-east-1` |
| `COPILOT_DATENQUELLE` | `synthetisch` oder `kundendatei` (Standard). Mit `kundendatei` + Bedrock + Nicht-EU-Region startet der Agent nur mit `FREIGABE_KUNDENDATEN_US=ja` |
| `APOBANK_DB_PATH`, `APOBANK_VAULT_PATH` | wie im Team-Backend |

AWS-Zugangsdaten nur über die Standardkette des SDK, z. B. `AWS_SHARED_CREDENTIALS_FILE` mit einer Datei
**außerhalb** des Repositorys. Niemals Schlüssel in Code, `.env` oder Commits.

## HTTP-Schnittstelle

| Methode | Pfad | Body | Antwort |
|---|---|---|---|
| POST | `/api/copilot/chat` | `{"nachricht": "...", "sitzung_id": null}` | `{sitzung_id, antwort, ergebnisse[], aktiver_vermittler, offene_entwuerfe[], fehler, modell}` |
| POST | `/api/copilot/entwuerfe/{id}/bestaetigen` | `{"sitzung_id": "...", "nutzer": "Name"}` | `{status: gespeichert \| bereits gespeichert \| abgelehnt, ...}` |
| POST | `/api/copilot/entwuerfe/{id}/verwerfen` | `{"sitzung_id": "..."}` | `{status: verworfen}` |
| POST | `/api/copilot/sitzungen` | – | `{sitzung_id}` (neue Sitzung, leeres Kurzzeitgedächtnis) |
| GET | `/api/copilot/status` | – | Modell, Region, Datenquelle (keine Geheimnisse) |

**Ergebnisformat** (`ergebnisse[]`, je Werkzeugaufruf eins):

```json
{"art": "tabelle | kandidaten | akte | entwurf | rueckfrage | hinweis | fehler",
 "titel": "…", "spalten": ["…"], "zeilen": [["…"]],
 "abschnitte": [{"titel": "Geschäftszahlen", "spalten": [], "zeilen": [], "diagramm": {"typ": "linie", "x": "Jahr", "y": "Kreditvolumen (EUR)"}}],
 "entwurf": {"entwurf_id": "E-…", "typ": "gespraechsnotiz | vermittler", "daten": {}, "abgleich": []},
 "hinweise": ["Gleichstand: Platz 3 teilen sich 2 Vermittler."],
 "quelle": {"werkzeug": "ranking", "parameter": {}, "datenstand": "…", "datensaetze": [900001]}}
```

## Anbindung im Frontend (`frontend/lib/workspace-contracts.ts`)

Ein HTTP-Adapter neben `mock-workspace-api.ts` implementiert `WorkspaceApi`:

| `WorkspaceApi` | Copilot-Endpunkt | Abbildung |
|---|---|---|
| `sendMessage(conversationId, content)` | `POST /api/copilot/chat` | `conversationId` ↔ `sitzung_id`; `antwort` → `ChatMessage.content`; `ergebnisse[].quelle` → `source`; Tabellen, Akte und Kandidaten im Chat darstellen (neues optionales Feld z. B. `results?: CopilotErgebnis[]`) |
| `confirmFindings(conversationId, ids)` | `POST /api/copilot/entwuerfe/{id}/bestaetigen` | Entwurfsfelder (`ergebnisse[art=entwurf].zeilen`) → `ExtractedFinding` (Gruppen: `partner` = Stammdaten/Interessen, `business` = Zahlen/Ziele, `next-step` = Maßnahmen/Wiedervorlage) |
| `createEntry(input)` | Text an `POST /api/copilot/chat` (Notiz oder Vermittler) → Entwurf → Bestätigung | oder direkt die Team-Endpunkte `POST /api/vermittler` bzw. `…/obsidian/eintraege` |
| `loadWorkspace()` | `GET /api/vermittler/{nr}/kontext` (Team) bzw. Akte über den Chat | – |

Wichtig für die Demo: Bestätigen nur per Klick des Nutzers, nie automatisch.

## Dateien

| Datei | Inhalt |
|---|---|
| `werkzeuge.py` | 9 Werkzeuge (Suche, aktiver Vermittler, Akte, Ranking, Filter, Maßnahmen, Gespräche, Notiz-Entwurf, Vermittler-Entwurf) |
| `agent.py` | Systemprompt + Werkzeugschleife, Kurzzeitkontext je Sitzung |
| `notizen.py` | Notizanalyse (separater Modellaufruf ohne Werkzeuge), Validierung, Zuordnung, Abgleich mit DB |
| `entwuerfe.py` | Freigabe über die Team-Funktionen (`add_obsidian_eintrag`, `update_vermittler`, `create_vermittler`) |
| `router.py`, `app.py` | FastAPI-Endpunkte; `app.py` hängt sie an `backend.main.app`, ohne `main.py` zu ändern |
| `llm/` | `base.py` (neutrales Format), `bedrock.py` (Converse-API), `fake.py` (offline, deterministisch) |
| `demo_daten.py` | synthetischer Datensatz im 39-Spalten-Excel-Format des Imports |
| `cli.py`, `bedrock_check.py` | Terminal-Chat; Prüfung von Identität, Modellen und Profilen (gibt keine Schlüssel aus) |

## Bekannte Grenzen und Vorschläge (Abstimmung nötig)

- Maßnahmenstatus: Im Gehirn gibt es nur `[ ]` und `[x]`. „Geplant“ wird als Textsuffix „(geplant)“ markiert.
  Vorschlag: ein Feld `status` bzw. eine Tabelle `massnahme` im Schema.
- Zielvorschläge und Quartalsmeilensteine stehen bisher nur als Text im Eintrag, gekennzeichnet als „NICHT genehmigt“.
  Vorschlag: Tabelle `zielplanung` mit Status `vorgeschlagen`/`genehmigt`.
- Sitzungen liegen im Speicher des Servers. Bei mehreren Instanzen bräuchte es einen gemeinsamen Speicher.
