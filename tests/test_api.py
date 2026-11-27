import json
from datetime import datetime

import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend import import_excel, obsidian
from backend.config import settings

HEADER = ['Marktgebiet', 'FilialNr', 'Filiale', 'Mitarbeiter_ID', 'Mitarbeiter_AP', 'VPB', 'Betreuung_seit',
          'Betreuung_bis', 'VermittlerNr', 'Name', 'Vorname', 'Titel', 'Sonstiger_Titel', 'Firma_Filiale',
          'Firma_Holding', 'Vermittlertyp', 'Geburtstag', 'Status', 'Abrechnungskreis', 'KNR', 'Adressentyp',
          'Postleitzahl', 'Ort', 'Strasse', 'Anrede', 'eMail', 'Dienstanschluss', 'Dienst_Handy',
          'Privatanschluss', 'Volumen in Euro in 2026', 'Anzahl Darlehen 2026', 'Volumen in Euro in 2025',
          'ANZ_DL_2025', 'Volumen in Euro in 2024', 'Anzahl Darlehen 2024', 'Volumen in Euro in 2023',
          'Anzahl Darlehen 2023', 'Status Vertriebspartner', 'Interessen']
D = datetime
ROWS = [
    ['West', 10, 'Filiale Aachen Region', 'SEB45322', 'B0CA', 'Schumann', D(2007, 7, 14), None, 4251, 'Baumann',
     'Hans', 'Dr.', None, 'Finanzberatung GmbH', 'XYZ Immobilien GMBH', 'Wirtschafts- und Vermögensberater',
     D(1955, 8, 2), 'aktiv', 'Sonstige', 17493, 'Firmenanschrift', '33098', 'Paderborn', 'Wigbertstraße 12',
     'Sehr geehrter Herr', 'abc.aaa@abc.de', '33098/8729421', '0222/2712453', '1234/435333',
     1624000, 7, 10773001, 46, 21242499, 50, 12363900, 30, 'Fokus-Vertriebspartner', 'Sport'],
    ['Nord', 20, 'Filiale Hamburg', 'DHH18392', 'B5AV', 'Petrović', D(2022, 1, 7), None, 40893, 'Otto', 'Martin',
     None, None, 'NordInvest GmbH', None, 'Praxisberater / Niederlassungsberater', D(1962, 3, 16), 'aktiv',
     'Gewerbliche Immobilien', 25220, 'Firmenanschrift', '22767', 'Hamburg', 'Ludwigstraße 119',
     'Sehr geehrter Herr', 'martin.otto@nordinvest.de', '040/346205', None, '040/7224540',
     7933800, 29, 14902000, 46, 0, 0, 13009700, 39, 'Fokus-Vertriebspartner', 'Golf'],
    ['Nord', 20, 'Filiale Hamburg', 'DHH18392', 'B5AV', 'Petrović', D(2019, 1, 1), D(2022, 4, 3), 500, 'Huber',
     'Lars', None, None, 'Steuerberatung Huber e.K.', None, 'Steuerberater', D(1991, 9, 19), 'inaktiv',
     'Sonstige', 37801, 'Firmenanschrift', '20095', 'Hamburg', 'Mönckebergstraße 1', 'Sehr geehrter Herr',
     'l.huber@example.de', '040/1', None, None, 0, 0, 1000000, 2, 500000, 1, 0, 0,
     'Ruhender Vertriebspartner', 'Wein, Musik'],
]


BROWSER_A = {"X-Client-ID": "browser-a-0000000000000001"}
BROWSER_B = {"X-Client-ID": "browser-b-0000000000000002"}


def test_chat_loeschen(client):
    chat_id = client.post("/api/chat/conversations", json={"titel": "Test"}, headers=BROWSER_A).json()["id"]
    andere_id = client.post("/api/chat/conversations", json={"titel": "Bleibt"}, headers=BROWSER_A).json()["id"]

    assert client.delete(f"/api/chat/conversations/{chat_id}", headers=BROWSER_A).status_code == 204
    workspace = client.get("/api/chat/workspace", headers=BROWSER_A).json()
    assert [c["id"] for c in workspace["conversations"]] == [andere_id]
    assert chat_id not in workspace["messages_by_conversation"]
    assert client.delete(f"/api/chat/conversations/{chat_id}", headers=BROWSER_A).status_code == 404


def test_mehrdeutiger_name_liefert_auswahl_buttons(client, monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)  # Datenbank-Fallback, kein OpenAI-Aufruf
    for vorname in ("Anna", "Bernd"):
        assert client.post("/api/vermittler", json={"vorname": vorname, "name": "Scholzmann",
                                                    "titel": "Dr." if vorname == "Anna" else None}).status_code == 201
    chat_id = client.post("/api/chat/conversations", json={"titel": "t"}, headers=BROWSER_A).json()["id"]

    r = client.post(f"/api/chat/conversations/{chat_id}/messages", json={"inhalt": "Scholzmann"}, headers=BROWSER_A)
    assert r.status_code == 200, r.text
    kandidaten = r.json()["kandidaten"]
    assert [k["name"] for k in kandidaten] == ["Dr. Anna Scholzmann", "Bernd Scholzmann"]
    assert all(isinstance(k["vermittler_nr"], int) for k in kandidaten)

    # Bleibt im Verlauf erhalten, damit die Buttons nach dem Neuladen wieder erscheinen
    verlauf = client.get("/api/chat/workspace", headers=BROWSER_A).json()["messages_by_conversation"][chat_id]
    assert verlauf[-1]["metadata"]["kandidaten"] == kandidaten

    # Eindeutiger Treffer: keine Buttons, direkt die Partnerakte
    r = client.post(f"/api/chat/conversations/{chat_id}/messages", json={"inhalt": "Bernd Scholzmann"}, headers=BROWSER_A)
    assert r.json()["kandidaten"] == [] and r.json()["partner"]["name"].endswith("Scholzmann")


class _FakeCall:
    type = "function_call"

    def __init__(self, name, arguments, call_id):
        self.name, self.arguments, self.call_id = name, json.dumps(arguments), call_id


class _FakeResponse:
    def __init__(self, output=(), text=""):
        self.output, self.output_text = list(output), text


class _FakeOpenAI:
    """Spielt Analyse-Agent und Chat-Agent nach – ohne Netz, deterministisch."""
    SQL = ("SELECT TRIM(COALESCE(v.titel || ' ', '') || v.vorname || ' ' || v.name) AS vermittler, g.volumen_eur "
           "FROM v_vermittler v JOIN geschaeftszahlen g ON g.vermittler_nr = v.vermittler_nr "
           "WHERE g.jahr = 2025 AND g.sparte = 'gesamt' ORDER BY g.volumen_eur DESC LIMIT 10")

    def __init__(self, **_):
        self.responses = self

    def create(self, model, instructions, tools, input, **_):
        from backend import openai_copilot
        schon_tool = any(isinstance(i, dict) and i.get("type") == "function_call_output" for i in input)
        if instructions == openai_copilot.ANALYSE_INSTRUCTIONS:
            if schon_tool:
                return _FakeResponse(text="KEINE")
            return _FakeResponse([_FakeCall("sql_analyse", {"titel": "Top 10 Vermittler 2025", "sql": self.SQL,
                                                              "diagramm": {"typ": "balken", "x": "vermittler", "y": "volumen_eur", "einheit": "eur"}}, "a1")])
        if not schon_tool:
            return _FakeResponse([_FakeCall("vorbereitete_analyse", {}, "c1")])
        ergebnis = json.loads(next(i["output"] for i in input if isinstance(i, dict) and i.get("call_id") == "c1"))
        top = ergebnis["zeilen"][0]
        return _FakeResponse(text=f"Top-Vermittler 2025 ist {top[0]} mit {top[1]} EUR.")


def test_analyse_agent_bereitet_sql_vor_und_chat_nutzt_es(client, monkeypatch):
    import openai

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)
    chat_id = client.post("/api/chat/conversations", json={"titel": "t"}, headers=BROWSER_A).json()["id"]

    r = client.post(f"/api/chat/conversations/{chat_id}/messages", json={"inhalt": "Wer ist der Top-Vermittler?"},
                    headers=BROWSER_A)
    assert r.status_code == 200, r.text
    body = r.json()
    [analyse] = body["analysen"]
    assert analyse["sql"] == _FakeOpenAI.SQL and analyse["vorbereitet"] is True
    assert analyse["spalten"] == ["vermittler", "volumen_eur"]
    # Testdaten 2025: Otto 14.902.000 > Baumann 10.773.001 > Huber 1.000.000 – Zahl kommt aus SQL, nicht geraten
    assert analyse["zeilen"][0] == ["Martin Otto", 14902000]
    assert body["message"]["content"] == "Top-Vermittler 2025 ist Martin Otto mit 14902000 EUR."

    # SQL ist mit der Nachricht gespeichert (Zwischenspeicher fuer den Analyse-Tab)
    verlauf = client.get("/api/chat/workspace", headers=BROWSER_A).json()["messages_by_conversation"][chat_id]
    assert verlauf[-1]["metadata"]["analysen"][0]["sql"] == _FakeOpenAI.SQL


def test_sql_analyse_ist_read_only(client):
    from backend import openai_copilot

    for boese in ("DELETE FROM vermittler", "PRAGMA table_info(vermittler)", "SELECT 1; DROP TABLE vermittler",
                  "ATTACH 'x.db' AS x", "UPDATE vermittler SET name = 'x'"):
        antwort, analyse = openai_copilot._sql_analyse({"titel": "x", "sql": boese,
                                                        "diagramm": {"typ": "tabelle", "x": "", "y": "", "einheit": "keine"}})
        assert analyse is None and "fehler" in antwort, boese
    assert client.get("/api/vermittler/4251").status_code == 200  # Daten unangetastet


def test_transkription_prueft_audio_und_liefert_text(client, monkeypatch):
    from backend import transcribe

    aufrufe = []

    async def fake_stream(pcm, sample_rate, sprache):  # ersetzt nur den AWS-Aufruf, Pruefung laeuft echt
        dauer = transcribe.pruefe_audio(pcm, sample_rate, sprache)
        aufrufe.append((len(pcm), sample_rate, sprache))
        return {"text": "Termin mit Herrn Weber am Montag", "dauer_s": round(dauer, 1), "verarbeitung_ms": 5}

    monkeypatch.setattr(transcribe, "transkribieren", fake_stream)
    eine_sekunde = b"\x00\x00" * 16000

    r = client.post("/api/transkription", files={"audio": ("a.pcm", eine_sekunde)}, data={"sample_rate": "16000"})
    assert r.status_code == 200, r.text
    assert r.json() == {"text": "Termin mit Herrn Weber am Montag", "dauer_s": 1.0, "verarbeitung_ms": 5}
    assert aufrufe == [(32000, 16000, "de-DE")]

    faelle = [
        (b"\x00\x00" * 100, {}, 422, "TRANSCRIBE_ZU_KURZ"),
        (b"\x00" * 32001, {}, 422, "TRANSCRIBE_FORMAT"),                 # ungerade Byte-Zahl = kein 16-bit-PCM
        (eine_sekunde, {"sprache": "xx-XX"}, 422, "TRANSCRIBE_SPRACHE"),
        (eine_sekunde, {"sample_rate": "1000"}, 422, "TRANSCRIBE_FORMAT"),
        (b"\x00\x00" * 16000 * 122, {}, 413, "TRANSCRIBE_ZU_LANG"),
    ]
    for audio, daten, status, code in faelle:
        r = client.post("/api/transkription", files={"audio": ("a.pcm", audio)}, data=daten)
        assert (r.status_code, r.json()["fehler_code"]) == (status, code), (code, r.text)


def test_transkription_fehlende_rechte_werden_verstaendlich(client, monkeypatch):
    from backend import transcribe

    class AccessDeniedException(Exception):
        pass

    assert transcribe._uebersetze(AccessDeniedException("User is not authorized")).code == "TRANSCRIBE_RECHTE"
    assert transcribe._uebersetze(RuntimeError("AWS_ERROR_AUTH_SIGNING_NO_CREDENTIALS")).code == "TRANSCRIBE_RECHTE"
    assert transcribe._uebersetze(ValueError("kaputt")).code == "TRANSCRIBE_FEHLER"


class _FakeAenderungsOpenAI(_FakeOpenAI):
    """Chat-Agent schlaegt Aenderungen vor; der parallele Analyse-Agent haelt keine Abfrage fuer noetig."""
    AENDERUNGEN = [
        {"art": "kontakt", "feld": "email", "jahr": 0, "fakt_id": "", "wert": "h.baumann@neu.de"},
        {"art": "stammdaten", "feld": "interessen", "jahr": 0, "fakt_id": "", "wert": "Sport, Segeln"},
        {"art": "geschaeftszahlen", "feld": "volumen_eur", "jahr": 2025, "fakt_id": "", "wert": "11.000.000"},
        {"art": "stammdaten", "feld": "obsidian_pfad", "jahr": 0, "fakt_id": "", "wert": "../../etc"},  # nicht erlaubt
    ]

    def create(self, model, instructions, tools, input, **_):
        from backend import openai_copilot
        if instructions == openai_copilot.ANALYSE_INSTRUCTIONS:
            return _FakeResponse(text="KEINE")
        if not any(isinstance(i, dict) and i.get("type") == "function_call_output" for i in input):
            return _FakeResponse([_FakeCall("aenderung_vorschlagen", {
                "vermittler_nr": 4251, "begruendung": "Laut Nutzer", "aenderungen": self.AENDERUNGEN}, "c1")])
        return _FakeResponse(text="Ich habe 3 Änderungen vorgeschlagen – bitte im Tab Änderungen bestätigen.")


def _vorschlag_anfordern(client, monkeypatch):
    import openai

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai, "OpenAI", _FakeAenderungsOpenAI)
    chat_id = client.post("/api/chat/conversations", json={"titel": "t"}, headers=BROWSER_A).json()["id"]
    r = client.post(f"/api/chat/conversations/{chat_id}/messages", json={"inhalt": "Aendere bitte ..."}, headers=BROWSER_A)
    assert r.status_code == 200, r.text
    [vorschlag] = r.json()["aenderungsvorschlaege"]
    return chat_id, vorschlag


def test_ki_aenderungen_erst_nach_bestaetigung(client, monkeypatch):
    chat_id, vorschlag = _vorschlag_anfordern(client, monkeypatch)
    assert vorschlag["status"] == "offen"
    felder = {(a["bereich"], a["label"]): (a["alt"], a["neu"]) for a in vorschlag["aenderungen"]}
    assert felder == {
        ("Kontakt", "E-Mail"): ("abc.aaa@abc.de", "h.baumann@neu.de"),
        ("Stammdaten", "Interessen/Hobbys"): ("Sport", "Sport, Segeln"),
        ("Geschäftszahlen", "Kreditvolumen (EUR) 2025"): (10773001, 11000000),
    }  # obsidian_pfad wurde abgelehnt (Whitelist)

    # Vor der Bestaetigung ist nichts geaendert
    v = client.get("/api/vermittler/4251").json()
    assert v["kontakt"]["email"] == "abc.aaa@abc.de"

    # Fremder Browser darf nicht bestaetigen
    assert client.post(f"/api/chat/aenderungen/{vorschlag['id']}/bestaetigen", headers=BROWSER_B).status_code == 404

    r = client.post(f"/api/chat/aenderungen/{vorschlag['id']}/bestaetigen", headers=BROWSER_A)
    assert r.status_code == 200, r.text
    v = client.get("/api/vermittler/4251").json()
    assert v["kontakt"]["email"] == "h.baumann@neu.de" and v["interessen"] == ["Sport", "Segeln"]
    assert next(g for g in v["geschaeftszahlen"] if g["jahr"] == 2025)["volumen_eur"] == 11_000_000
    # Protokollnotiz im Obsidian-Gehirn
    assert any("Änderungen aus dem Chat bestätigt" in e.get("titel", "")
               for e in client.get("/api/vermittler/4251/obsidian").json()["eintraege"])

    # Kein zweites Bestaetigen; Status im Verlauf ist "bestaetigt"
    assert client.post(f"/api/chat/aenderungen/{vorschlag['id']}/bestaetigen", headers=BROWSER_A).status_code == 409
    verlauf = client.get("/api/chat/workspace", headers=BROWSER_A).json()["messages_by_conversation"][chat_id]
    assert verlauf[-1]["metadata"]["aenderungsvorschlaege"][0]["status"] == "bestaetigt"


def test_ki_aenderung_konflikt_und_verwerfen(client, monkeypatch):
    _, vorschlag = _vorschlag_anfordern(client, monkeypatch)
    # Jemand aendert die E-Mail, nachdem der Vorschlag erstellt wurde
    client.patch("/api/vermittler/4251", json={"kontakt": {"email": "zwischendurch@x.de"}})
    r = client.post(f"/api/chat/aenderungen/{vorschlag['id']}/bestaetigen", headers=BROWSER_A)
    assert r.status_code == 409 and r.json()["fehler_code"] == "AENDERUNG_KONFLIKT"
    v = client.get("/api/vermittler/4251").json()
    assert v["kontakt"]["email"] == "zwischendurch@x.de" and v["interessen"] == ["Sport"]  # nichts ueberschrieben

    _, vorschlag2 = _vorschlag_anfordern(client, monkeypatch)
    assert client.post(f"/api/chat/aenderungen/{vorschlag2['id']}/verwerfen", headers=BROWSER_A).json()["status"] == "verworfen"
    assert client.get("/api/vermittler/4251").json()["kontakt"]["email"] == "zwischendurch@x.de"


def test_chats_sind_pro_browser_getrennt(client):
    chat_a = client.post("/api/chat/conversations", json={"titel": "Von A"}, headers=BROWSER_A).json()["id"]
    chat_b = client.post("/api/chat/conversations", json={"titel": "Von B"}, headers=BROWSER_B).json()["id"]

    assert [c["id"] for c in client.get("/api/chat/workspace", headers=BROWSER_A).json()["conversations"]] == [chat_a]
    assert [c["id"] for c in client.get("/api/chat/workspace", headers=BROWSER_B).json()["conversations"]] == [chat_b]

    # Fremde Chats: weder schreiben noch loeschen, und 404 statt 403 (Existenz wird nicht verraten)
    assert client.post(f"/api/chat/conversations/{chat_a}/messages", json={"inhalt": "hi"},
                       headers=BROWSER_B).status_code == 404
    assert client.delete(f"/api/chat/conversations/{chat_a}", headers=BROWSER_B).status_code == 404
    assert client.get("/api/chat/workspace", headers=BROWSER_A).json()["conversations"][0]["id"] == chat_a

    for headers in ({}, {"X-Client-ID": "zu-kurz"}, {"X-Client-ID": "x" * 16 + "' OR 1=1"}):
        r = client.get("/api/chat/workspace", headers=headers)
        assert r.status_code == 400 and r.json()["fehler_code"] == "UNGUELTIGE_ANFRAGE"


def test_fehlerformat_mit_code_und_request_id(client):
    r = client.get("/api/vermittler/999999")
    body = r.json()
    assert r.status_code == 404
    assert body["fehler_code"] == "NICHT_GEFUNDEN" and body["detail"]
    assert body["request_id"] and r.headers["X-Request-ID"] == body["request_id"]

    r = client.post("/api/chat/conversations", json={"titel": ""}, headers=BROWSER_A)
    body = r.json()
    assert r.status_code == 422 and body["fehler_code"] == "VALIDIERUNG"
    assert isinstance(body["detail"], list) and "titel" in body["meldung"]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    xlsx = tmp_path / "liste.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(HEADER)
    for r in ROWS:
        wb.active.append(r)
    wb.save(xlsx)
    monkeypatch.setattr(settings, "db_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "vault_path", tmp_path / "vault")
    monkeypatch.setattr(settings, "upload_path", tmp_path / "uploads")
    monkeypatch.setattr(settings, "openai_api_key", None)
    import_excel.run(xlsx)
    from backend.main import app
    with TestClient(app) as c:
        yield c


def test_import_creates_db_and_vault(client):
    r = client.get("/api/vermittler/4251").json()
    assert r["anzeigename"] == "Dr. Hans Baumann"
    assert r["betreuung"]["marktgebiet"] == "West"
    assert [z["jahr"] for z in r["geschaeftszahlen"]] == [2026, 2025, 2024, 2023]
    assert r["obsidian"]["pfad"] == "Vermittler/VM-4251/VM-4251.md"
    assert r["obsidian"]["uri"].startswith("obsidian://open?vault=")
    assert (settings.vault_path / r["obsidian"]["pfad"]).exists()


def test_iterate_all_pages(client):
    seen, offset = [], 0
    while offset is not None:
        page = client.get("/api/vermittler", params={"limit": 2, "offset": offset}).json()
        seen += [i["vermittler_nr"] for i in page["items"]]
        offset = page["next_offset"]
    assert seen == [500, 4251, 40893]


def test_filters_and_search(client):
    assert client.get("/api/vermittler", params={"q": "hans baumann"}).json()["total"] == 1
    r = client.get("/api/vermittler", params={"marktgebiet": "Nord", "sort": "volumen", "order": "desc",
                                              "jahr": 2025}).json()
    assert [i["vermittler_nr"] for i in r["items"]] == [40893, 500]
    assert client.get("/api/vermittler", params={"interesse": "Musik"}).json()["items"][0]["vermittler_nr"] == 500


def test_analytics(client):
    r = client.get("/api/analytics/ranking", params={"gruppe": "marktgebiet", "jahr": 2025}).json()
    assert r["items"][0] == {**r["items"][0], "marktgebiet": "Nord", "volumen_eur": 15902000}
    w = client.get("/api/analytics/wachstum", params={"von_jahr": 2024, "bis_jahr": 2025}).json()
    assert w["items"][0]["vermittler_nr"] == 40893  # 0 -> 14.9 Mio
    assert client.get("/api/analytics/ueberblick").json()["anzahl_vermittler"] == 3


def test_sql_readonly(client):
    ok = client.post("/api/sql/query", json={"sql": "SELECT COUNT(*) AS n FROM v_vermittler"}).json()
    assert ok["zeilen"] == [[3]]
    for bad in ("DELETE FROM vermittler", "UPDATE vermittler SET name='x'", "PRAGMA table_info(vermittler)",
                "ATTACH DATABASE 'x.db' AS x", "SELECT 1; DELETE FROM vermittler"):
        assert client.post("/api/sql/query", json={"sql": bad}).status_code == 400, bad
    assert client.get("/api/vermittler/4251").status_code == 200


def test_create_update_vermittler(client):
    r = client.post("/api/vermittler", json={
        "vorname": "Anna", "name": "Neu", "mitarbeiter_id": "DHH18392", "vermittlertyp": "Immobilienmakler",
        "interessen": ["Segeln"], "kontakt": {"ort": "Hamburg", "email": "anna@example.de"}})
    assert r.status_code == 201, r.text
    nr = r.json()["vermittler_nr"]
    assert nr == 40894 and r.json()["betreuung"]["filiale"] == "Filiale Hamburg"
    assert (settings.vault_path / r.json()["obsidian"]["pfad"]).exists()

    r = client.patch(f"/api/vermittler/{nr}", json={"status": "gesperrt", "kontakt": {"plz": "20095"}})
    assert r.json()["status"] == "gesperrt" and r.json()["kontakt"]["ort"] == "Hamburg"
    assert client.post("/api/vermittler", json={"vorname": "x", "name": "y", "mitarbeiter_id": "NOPE"}).status_code == 422

    r = client.put(f"/api/vermittler/{nr}/geschaeftszahlen/2026", json={"volumen_eur": 250000, "anzahl_darlehen": 1})
    assert r.json()[0]["volumen_eur"] == 250000
    hub = (settings.vault_path / obsidian.hub_rel(nr)).read_text(encoding="utf-8")
    assert "250.000 €" in hub and "gesperrt" in hub


def test_obsidian_entry_roundtrip(client):
    hub_path = settings.vault_path / obsidian.hub_rel(4251)
    hub_path.write_text(hub_path.read_text(encoding="utf-8") + "Manuelle Notiz bleibt erhalten.\n", encoding="utf-8")

    r = client.post("/api/vermittler/4251/obsidian/eintraege", json={
        "typ": "gespraech", "titel": "Jahresgespräch 2026", "datum": "2026-11-20",
        "inhalt": "Interesse an Praxisfinanzierung für zwei Zahnärzte in Paderborn.",
        "teilnehmer": ["Schumann", "Dr. Baumann"], "tags": ["Praxisgründung"],
        "massnahmen": [{"beschreibung": "Konditionen schicken", "verantwortlich": "Schumann",
                        "faellig_am": "2026-12-01"}], "quelle": "chat"})
    assert r.status_code == 201, r.text
    entry = r.json()
    note = (settings.vault_path / entry["datei"]).read_text(encoding="utf-8")
    assert "- [ ] Konditionen schicken 👤 Schumann 📅 2026-12-01" in note
    assert '"[[VM-4251]]"' in note

    hub = hub_path.read_text(encoding="utf-8")
    assert entry["datei"][:-3] in hub and "Manuelle Notiz bleibt erhalten." in hub

    # Sync ueberschreibt freie Notizen nicht, Eintragsliste bleibt
    client.post("/api/vermittler/4251/obsidian/sync")
    hub = hub_path.read_text(encoding="utf-8")
    assert "Manuelle Notiz bleibt erhalten." in hub and entry["datei"][:-3] in hub

    lst = client.get("/api/vermittler/4251/obsidian").json()
    assert lst["eintraege"][0]["titel"] == "Jahresgespräch 2026"

    text = client.get("/api/vermittler/4251/obsidian/inhalt", params={"format": "text"}).text
    assert "Praxisfinanzierung" in text and "=== HUB:" in text

    s = client.put("/api/vermittler/4251/obsidian/zusammenfassung",
                   json={"text": "Fokuspartner mit Praxisgründungs-Pipeline.", "quelle": "test"}).json()
    assert s["zusammenfassung"].startswith("Fokuspartner")

    ctx = client.get("/api/vermittler/4251/kontext").json()
    assert ctx["eintraege"][0]["typ"] == "gespraech" and ctx["zusammenfassung"].startswith("Fokuspartner")

    hits = client.get("/api/obsidian/suche", params={"q": "zahnärzte"}).json()
    assert hits[0]["vermittler_nr"] == 4251 and not hits[0]["ist_hub"]

    rows = client.post("/api/sql/query", json={"sql": "SELECT typ, titel FROM obsidian_eintrag"}).json()["zeilen"]
    assert rows == [["gespraech", "Jahresgespräch 2026"]]


def test_reimport_preserves_brain(client, tmp_path):
    client.post("/api/vermittler/4251/obsidian/eintraege", json={"titel": "Notiz", "inhalt": "x"})
    xlsx = tmp_path / "liste.xlsx"
    import_excel.run(xlsx)
    assert len(client.get("/api/vermittler/4251/obsidian").json()["eintraege"]) == 1


def test_404(client):
    assert client.get("/api/vermittler/999999").status_code == 404
    assert client.post("/api/vermittler/999999/obsidian/eintraege",
                       json={"titel": "t", "inhalt": "x"}).status_code == 404


def test_chat_database_fallback_opens_partnerakte_without_openai(client):
    conversation = client.post("/api/chat/conversations", json={"titel": "Neue Unterhaltung"}, headers=BROWSER_A).json()
    reply = client.post(
        f"/api/chat/conversations/{conversation['id']}/messages",
        json={"inhalt": "Zeig mir die Partnerakte von Hans Baumann"}, headers=BROWSER_A,
    )
    assert reply.status_code == 200, reply.text
    payload = reply.json()
    assert payload["openai_configured"] is False
    assert payload["partner"]["vermittler_nr"] == 4251
    assert payload["message"]["metadata"]["sources"] == ["Partnerdatenbank"]
    assert client.get("/api/health").json()["vermittler_count"] == 3


def test_creating_chat_twice_reuses_empty_conversation(client):
    first = client.post("/api/chat/conversations", json={"titel": "Neue Unterhaltung"}, headers=BROWSER_A).json()
    second = client.post("/api/chat/conversations", json={"titel": "Neue Unterhaltung"}, headers=BROWSER_A).json()
    assert second["id"] == first["id"]
    workspace = client.get("/api/chat/workspace", headers=BROWSER_A).json()
    assert len(workspace["conversations"]) == 1


def test_document_upload_persists_participants_and_next_steps(client):
    response = client.post(
        "/api/vermittler/4251/dokumente",
        data={
            "titel": "Gespräch mit Anhang",
            "inhalt": "Besprochene Konditionen.",
            "datum": "2026-11-27",
            "teilnehmer": "Dr. Baumann, Schumann",
            "massnahmen": "Konditionen senden\nTermin abstimmen",
        },
        files={"file": ("gespraech.txt", b"Interne Gespraechsnotiz", "text/plain")},
    )
    assert response.status_code == 201, response.text
    note = (settings.vault_path / response.json()["datei"]).read_text(encoding="utf-8")
    assert "**Teilnehmer:** Dr. Baumann, Schumann" in note
    assert "- [ ] Konditionen senden" in note and "- [ ] Termin abstimmen" in note


def test_persoenliches_profil(client):
    # Import legt fuer jeden Vermittler eine Profil-Notiz an und verlinkt sie im Hub
    profil_path = settings.vault_path / obsidian.profil_rel(4251)
    assert profil_path.exists()
    hub = (settings.vault_path / obsidian.hub_rel(4251)).read_text(encoding="utf-8")
    assert "![[VM-4251 Profil]]" in hub
    assert client.get("/api/vermittler/4251/profil").json()["fakten"] == []

    # Kategorie wird per Stichwort erkannt oder explizit gesetzt
    hund = client.post("/api/vermittler/4251/profil/fakten", json={"text": "Hat einen Hund namens Tim"})
    assert hund.status_code == 201, hund.text
    assert hund.json()["kategorie"] == "haustiere"
    client.post("/api/vermittler/4251/profil/fakten",
                json={"text": "War im Oktober auf Mallorca im Urlaub", "datum": "2026-10-20"})
    client.post("/api/vermittler/4251/profil/fakten", json={"text": "Mag Gespräche am Vormittag", "kategorie": "vorlieben"})

    # Auch von Hand in Obsidian ergaenzte Zeilen werden gelesen
    text = profil_path.read_text(encoding="utf-8").replace("## Familie\n", "## Familie\n- Tochter Lena studiert Medizin\n")
    profil_path.write_text(text, encoding="utf-8")

    profil = client.get("/api/vermittler/4251/profil").json()
    nach_kat = {f["text"]: (f["kategorie"], f["datum"]) for f in profil["fakten"]}
    assert nach_kat["Hat einen Hund namens Tim"][0] == "haustiere"
    assert nach_kat["War im Oktober auf Mallorca im Urlaub"] == ("reisen", "2026-10-20")
    assert nach_kat["Mag Gespräche am Vormittag"][0] == "vorlieben"
    assert nach_kat["Tochter Lena studiert Medizin"] == ("familie", None)
    assert profil["uri"].startswith("obsidian://open?vault=") and "Profil" in profil["uri"]

    # Kontext fuer die KI enthaelt das Profil; Re-Sync ueberschreibt es nicht
    assert "Hund namens Tim" in client.get("/api/vermittler/4251/kontext").json()["kontext_text"]
    client.post("/api/vermittler/4251/obsidian/sync")
    assert "Tochter Lena" in profil_path.read_text(encoding="utf-8")

    # Loeschen einzelner Infos
    fid = hund.json()["id"]
    assert client.delete(f"/api/vermittler/4251/profil/fakten/{fid}").status_code == 204
    assert client.delete(f"/api/vermittler/4251/profil/fakten/{fid}").status_code == 404
    assert "Hund" not in profil_path.read_text(encoding="utf-8")
    assert client.post("/api/vermittler/999999/profil/fakten", json={"text": "x"}).status_code == 404


def test_obsidian_netz(client):
    client.post("/api/vermittler/4251/profil/fakten", json={"text": "Hat einen Hund namens Tim"})
    client.post("/api/vermittler/4251/obsidian/eintraege", json={"titel": "Jahresgespräch", "inhalt": "Siehe auch [[VM-500]]."})
    client.post("/api/vermittler/500/obsidian/eintraege", json={"titel": "Empfehlung", "inhalt": "Kennt [[VM-4251]] gut."})

    netz = client.get("/api/vermittler/4251/obsidian/netz").json()
    knoten = {k["id"]: k for k in netz["knoten"]}
    assert netz["zentrum"] == "VM-4251" and knoten["VM-4251"]["typ"] == "vermittler"
    assert knoten["VM-4251 Profil"]["typ"] == "profil"
    assert any(k["typ"] == "fakt" and "Tim" in k["label"] for k in knoten.values())
    assert any(k["typ"] == "eintrag" and k["label"] == "Jahresgespräch" for k in knoten.values())
    assert knoten["VM-500"]["typ"] == "vermittler-link"  # Wikilink bzw. Backlink
    assert any(k["typ"] == "betreuer" for k in knoten.values()) and any(k["typ"] == "filiale" for k in knoten.values())
    ids = set(knoten)
    assert all(e["von"] in ids and e["nach"] in ids for e in netz["kanten"])
    assert client.get("/api/vermittler/999999/obsidian/netz").status_code == 404


def test_copilot_speichert_direkt_im_obsidian(client):
    from backend import db, openai_copilot
    conn = db.connect()
    try:
        output, nr, findings, quelle = openai_copilot._execute_tool(conn, "im_obsidian_speichern", {
            "vermittler_nr": 4251, "angaben": [
                {"gruppe": "persoenlich", "label": "Haustiere", "wert": "Hat einen Hund namens Tim", "quelle": "Chat"},
                {"gruppe": "persoenlich", "label": "Reisen & Urlaub", "wert": "War im Oktober auf Mallorca", "quelle": "Chat"},
                {"gruppe": "business", "label": "Interesse", "wert": "Praxisfinanzierung 2027", "quelle": "Chat"},
                {"gruppe": "next-step", "label": "Aufgabe", "wert": "Konditionen schicken", "quelle": "Chat"},
            ]})
        conn.commit()
    finally:
        conn.close()
    assert output["status"] == "gespeichert" and nr == 4251 and quelle == "Obsidian"
    assert all(f["status"] == "confirmed" for f in findings) and len(findings) == 4

    profil = {f["text"]: f["kategorie"] for f in client.get("/api/vermittler/4251/profil").json()["fakten"]}
    assert profil == {"Hat einen Hund namens Tim": "haustiere", "War im Oktober auf Mallorca": "reisen"}
    eintraege = client.get("/api/vermittler/4251/obsidian/inhalt").json()["eintraege"]
    notiz = next(e for e in eintraege if e["frontmatter"]["quelle"] == "chat")
    assert "Praxisfinanzierung 2027" in notiz["inhalt"] and "- [ ] Konditionen schicken" in notiz["inhalt"]
    rows = client.post("/api/sql/query", json={"sql": "SELECT autor FROM obsidian_eintrag WHERE vermittler_nr = 4251"}).json()
    assert ["copilot"] in rows["zeilen"]


class _FakeNeueInfoOpenAI(_FakeOpenAI):
    """Chat-Agent will eine neue Profil-Info und eine Notiz speichern – es darf nur ein Vorschlag entstehen."""

    def create(self, model, instructions, tools, input, **_):
        if not any(isinstance(i, dict) and i.get("type") == "function_call_output" for i in input):
            return _FakeResponse([_FakeCall("im_obsidian_speichern", {"vermittler_nr": 4251, "angaben": [
                {"gruppe": "persoenlich", "label": "Haustiere", "wert": "Hat einen Hund namens Tim", "quelle": "Chat"},
                {"gruppe": "next-step", "label": "Aufgabe", "wert": "Konditionen schicken", "quelle": "Chat"},
            ]}, "c1")])
        return _FakeResponse(text="Zur Bestätigung vorbereitet.")


def test_neue_infos_werden_erst_nach_bestaetigung_gespeichert(client, monkeypatch):
    import openai

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai, "OpenAI", _FakeNeueInfoOpenAI)
    chat_id = client.post("/api/chat/conversations", json={"titel": "t"}, headers=BROWSER_A).json()["id"]
    r = client.post(f"/api/chat/conversations/{chat_id}/messages",
                    json={"inhalt": "Herr Baumann hat einen Hund namens Tim, ich schicke ihm die Konditionen"},
                    headers=BROWSER_A)
    [vorschlag] = r.json()["aenderungsvorschlaege"]
    assert [(a["art"], a["alt"], a["neu"]) for a in vorschlag["aenderungen"]] == [
        ("profil_fakt_neu", None, "Hat einen Hund namens Tim"), ("notiz_neu", None, "Konditionen schicken")]
    assert client.get("/api/vermittler/4251/profil").json()["fakten"] == []  # noch nichts gespeichert

    assert client.post(f"/api/chat/aenderungen/{vorschlag['id']}/bestaetigen", headers=BROWSER_A).status_code == 200
    assert [f["text"] for f in client.get("/api/vermittler/4251/profil").json()["fakten"]] == ["Hat einen Hund namens Tim"]
    notizen = client.get("/api/vermittler/4251/obsidian/inhalt").json()["eintraege"]
    assert any("- [ ] Konditionen schicken" in e["inhalt"] for e in notizen)


def test_copilot_speichert_nichts_bei_unbekanntem_vermittler(client):
    from backend import db, openai_copilot
    conn = db.connect()
    try:
        output, nr, findings, _ = openai_copilot._execute_tool(conn, "im_obsidian_speichern", {
            "vermittler_nr": 999999, "angaben": [{"gruppe": "persoenlich", "label": "x", "wert": "y", "quelle": "c"}]})
    finally:
        conn.close()
    assert "fehler" in output and nr is None and findings == []


def test_copilot_werkzeuge_liefern_links(client):
    from backend import db, openai_copilot
    conn = db.connect()
    try:
        akte, nr, _, _ = openai_copilot._execute_tool(conn, "hole_partnerakte", {"vermittler_nr": 4251})
        gespeichert, *_ = openai_copilot._execute_tool(conn, "im_obsidian_speichern", {"vermittler_nr": 4251, "angaben": [
            {"gruppe": "persoenlich", "label": "Haustiere", "wert": "Hat einen Hund namens Tim", "quelle": "Chat"}]})
    finally:
        conn.close()
    assert nr == 4251
    assert akte["links"]["obsidian_akte"].startswith("obsidian://open?vault=")
    assert "Profil" in akte["links"]["persoenliches_profil"]
    assert all(e["uri"].startswith("obsidian://") for e in gespeichert["gespeichert"])
    assert gespeichert["akte_link"].startswith("obsidian://")
