-- Datenmodell Vermittler-Copilot (SQLite)
-- Quelle der Erstbefuellung: Musterliste_apoBank.xlsx (eine Zeile = ein Vermittler)

PRAGMA foreign_keys = ON;

-- Filialen der apoBank inkl. Marktgebiet (Nord, Ost, Sued, West, Mitte)
CREATE TABLE IF NOT EXISTS filiale (
    filial_nr    INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    marktgebiet  TEXT NOT NULL
);

-- Betreuer (Vertriebsmitarbeiter der Bank), einer Filiale zugeordnet
CREATE TABLE IF NOT EXISTS betreuer (
    mitarbeiter_id  TEXT PRIMARY KEY,              -- Excel: Mitarbeiter_ID
    kuerzel         TEXT,                          -- Excel: Mitarbeiter_AP
    name            TEXT NOT NULL,                 -- Excel: VPB
    filial_nr       INTEGER NOT NULL REFERENCES filiale(filial_nr)
);

-- Vermittler-Stammdaten (externe Handelsvertreter)
CREATE TABLE IF NOT EXISTS vermittler (
    vermittler_nr            INTEGER PRIMARY KEY,  -- Excel: VermittlerNr
    knr                      INTEGER UNIQUE,       -- Kundennummer
    anrede                   TEXT,
    titel                    TEXT,
    sonstiger_titel          TEXT,
    vorname                  TEXT NOT NULL,
    name                     TEXT NOT NULL,
    geburtstag               TEXT,                 -- ISO-Datum
    firma_filiale            TEXT,
    firma_holding            TEXT,
    vermittlertyp            TEXT,
    status                   TEXT NOT NULL DEFAULT 'aktiv'
                             CHECK (status IN ('aktiv', 'inaktiv', 'gesperrt')),
    abrechnungskreis         TEXT,
    status_vertriebspartner  TEXT,                 -- Fokus/Standard/Potenzial/Ruhend/...
    interessen               TEXT,                 -- kommagetrennt
    mitarbeiter_id           TEXT REFERENCES betreuer(mitarbeiter_id),
    betreuung_seit           TEXT,
    betreuung_bis            TEXT,
    obsidian_pfad            TEXT UNIQUE,          -- Pfad der Hub-Notiz relativ zum Vault
    obsidian_uri             TEXT,                 -- obsidian://open?... Deeplink
    erstellt_am              TEXT NOT NULL DEFAULT (datetime('now')),
    geaendert_am             TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Kontaktdaten / Anschrift (1:1 zum Vermittler)
CREATE TABLE IF NOT EXISTS kontakt (
    vermittler_nr   INTEGER PRIMARY KEY REFERENCES vermittler(vermittler_nr) ON DELETE CASCADE,
    adressentyp     TEXT,
    strasse         TEXT,
    plz             TEXT,
    ort             TEXT,
    email           TEXT,
    telefon_dienst  TEXT,
    handy_dienst    TEXT,
    telefon_privat  TEXT
);

-- Geschaeftszahlen je Vermittler, Jahr und Sparte.
-- Die Excel liefert nur Gesamtwerte (sparte = 'gesamt'); weitere Sparten
-- (Baufinanzierung, Existenzgruendung, ...) koennen ohne Schemaaenderung ergaenzt werden.
CREATE TABLE IF NOT EXISTS geschaeftszahlen (
    vermittler_nr    INTEGER NOT NULL REFERENCES vermittler(vermittler_nr) ON DELETE CASCADE,
    jahr             INTEGER NOT NULL,
    sparte           TEXT NOT NULL DEFAULT 'gesamt',
    volumen_eur      INTEGER NOT NULL DEFAULT 0,
    anzahl_darlehen  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (vermittler_nr, jahr, sparte)
);

-- Protokoll aller ueber die API ins Obsidian-"Gehirn" geschriebenen Eintraege
CREATE TABLE IF NOT EXISTS obsidian_eintrag (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    vermittler_nr  INTEGER NOT NULL REFERENCES vermittler(vermittler_nr) ON DELETE CASCADE,
    typ            TEXT NOT NULL,
    titel          TEXT NOT NULL,
    datum          TEXT NOT NULL,
    datei          TEXT NOT NULL UNIQUE,           -- Pfad relativ zum Vault
    autor          TEXT,
    quelle         TEXT,
    erstellt_am    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Persistente Chatverlaeufe fuer die Arbeitsoberflaeche. KI-Antworten koennen
-- Metadaten wie erkannte Angaben und den aktuell betrachteten Vermittler tragen.
CREATE TABLE IF NOT EXISTS chat_konversation (
    id              TEXT PRIMARY KEY,
    titel           TEXT NOT NULL DEFAULT 'Neue Unterhaltung',
    vermittler_nr   INTEGER REFERENCES vermittler(vermittler_nr) ON DELETE SET NULL,
    erstellt_am     TEXT NOT NULL DEFAULT (datetime('now')),
    aktualisiert_am TEXT NOT NULL DEFAULT (datetime('now')),
    -- Zufaellige ID des Browsers (Header X-Client-ID). Trennt nur die Ansicht, ist KEINE Authentifizierung.
    -- Bestehende DBs ergaenzt db.init_db; Altchats ohne client_id sind fuer niemanden sichtbar.
    client_id       TEXT
);

CREATE TABLE IF NOT EXISTS chat_nachricht (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    konversation_id    TEXT NOT NULL REFERENCES chat_konversation(id) ON DELETE CASCADE,
    rolle              TEXT NOT NULL CHECK (rolle IN ('user', 'assistant')),
    inhalt             TEXT NOT NULL,
    metadaten_json     TEXT,
    erstellt_am        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Anhaenge im Chat (PDF/Word/Excel/Text -> ausgelesener Text, Bilder -> base64). Gehen mit der naechsten
-- Nachricht an die KI; gebunden an Chat + Browser-ID. Werden mit dem Chat geloescht.
CREATE TABLE IF NOT EXISTS chat_anhang (
    id                 TEXT PRIMARY KEY,
    konversation_id    TEXT NOT NULL REFERENCES chat_konversation(id) ON DELETE CASCADE,
    client_id          TEXT,
    name               TEXT NOT NULL,
    mime               TEXT NOT NULL,
    groesse            INTEGER NOT NULL,
    art                TEXT NOT NULL CHECK (art IN ('text', 'bild')),
    text               TEXT,
    bild_base64        TEXT,
    abgeschnitten      INTEGER NOT NULL DEFAULT 0,
    erstellt_am        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Analysen aus dem Chat (SQL, Auswahlfelder, aktuelles Ergebnis). Ermoeglicht das Neuberechnen ueber die
-- Dropdowns im Tab "Analyse" ohne neue KI-Frage; die aktuelle Auswahl bleibt beim Neuladen erhalten.
CREATE TABLE IF NOT EXISTS chat_analyse (
    id                 TEXT PRIMARY KEY,
    konversation_id    TEXT NOT NULL REFERENCES chat_konversation(id) ON DELETE CASCADE,
    client_id          TEXT,
    analyse_json       TEXT NOT NULL,
    erstellt_am        TEXT NOT NULL DEFAULT (datetime('now')),
    geaendert_am       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Aenderungsvorschlaege der KI (Stammdaten, Kontakt, Geschaeftszahlen, Profil). Werden erst nach
-- Klick auf "Bestaetigen" im Tab "Aenderungen" ausgefuehrt; gebunden an Chat + Browser-ID.
CREATE TABLE IF NOT EXISTS chat_aenderung (
    id                 TEXT PRIMARY KEY,
    konversation_id    TEXT NOT NULL REFERENCES chat_konversation(id) ON DELETE CASCADE,
    client_id          TEXT,
    vermittler_nr      INTEGER NOT NULL,
    vorschlag_json     TEXT NOT NULL,                  -- {vermittler, begruendung, aenderungen: [{alt, neu, ...}]}
    status             TEXT NOT NULL DEFAULT 'offen' CHECK (status IN ('offen', 'bestaetigt', 'verworfen')),
    ergebnis_json      TEXT,
    erstellt_am        TEXT NOT NULL DEFAULT (datetime('now')),
    entschieden_am     TEXT
);

CREATE INDEX IF NOT EXISTS idx_vermittler_name     ON vermittler(name, vorname);
CREATE INDEX IF NOT EXISTS idx_vermittler_betreuer ON vermittler(mitarbeiter_id);
CREATE INDEX IF NOT EXISTS idx_vermittler_status   ON vermittler(status);
CREATE INDEX IF NOT EXISTS idx_kontakt_ort         ON kontakt(ort);
CREATE INDEX IF NOT EXISTS idx_gz_jahr             ON geschaeftszahlen(jahr, sparte);
CREATE INDEX IF NOT EXISTS idx_eintrag_vermittler  ON obsidian_eintrag(vermittler_nr, datum);
CREATE INDEX IF NOT EXISTS idx_chat_nachricht_konversation ON chat_nachricht(konversation_id, id);

-- Flache Sicht fuer Agenten: Vermittler + Kontakt + Betreuer + Filiale
CREATE VIEW IF NOT EXISTS v_vermittler AS
SELECT
    v.vermittler_nr, v.knr, v.anrede, v.titel, v.sonstiger_titel, v.vorname, v.name,
    v.geburtstag, v.firma_filiale, v.firma_holding, v.vermittlertyp, v.status,
    v.abrechnungskreis, v.status_vertriebspartner, v.interessen,
    v.mitarbeiter_id, v.betreuung_seit, v.betreuung_bis,
    v.obsidian_pfad, v.obsidian_uri, v.erstellt_am, v.geaendert_am,
    k.adressentyp, k.strasse, k.plz, k.ort, k.email,
    k.telefon_dienst, k.handy_dienst, k.telefon_privat,
    b.kuerzel AS betreuer_kuerzel, b.name AS betreuer_name,
    f.filial_nr, f.name AS filiale, f.marktgebiet
FROM vermittler v
LEFT JOIN kontakt  k ON k.vermittler_nr = v.vermittler_nr
LEFT JOIN betreuer b ON b.mitarbeiter_id = v.mitarbeiter_id
LEFT JOIN filiale  f ON f.filial_nr = b.filial_nr;
