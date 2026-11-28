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
    # Namen aus der DB werden klickbar (oeffnen die Partnerakte)
    assert body["message"]["content"] == "Top-Vermittler 2025 ist [Martin Otto](partner:40893) mit 14902000 EUR."

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
    # Im Obsidian-Gehirn steht die neue Information selbst – keine "Aenderung wurde gemacht"-Notiz
    assert not client.get("/api/vermittler/4251/obsidian").json()["eintraege"]
    hub = client.get("/api/vermittler/4251/obsidian/inhalt?format=text").text
    assert "h.baumann@neu.de" in hub and "abc.aaa@abc.de" not in hub
    netz = client.get("/api/vermittler/4251/obsidian/netz").json()
    assert not any("Änderung" in k["label"] for k in netz["knoten"])
    assert any("Segeln" in k["label"] for k in netz["knoten"])  # neues Interesse als Knoten im Netz

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
    monkeypatch.setattr(settings, "betreuerkonto_id", "SEB45322")
    from backend import chat_titel
    monkeypatch.setattr(chat_titel, "_ki_titel", lambda frage: None)  # Titel-Bot nie echt aufrufen (Fakes zaehlen Aufrufe)
    import_excel.run(xlsx)
    from backend.main import app
    with TestClient(app) as c:
        yield c


def test_titel_bot_vergibt_titel_parallel_und_traegt_spaet_nach(client, monkeypatch):
    import threading
    import time

    from backend import chat_titel, openai_copilot

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai_copilot, "antwort_auf_nachricht",
                        lambda conn, history, anhaenge=None: openai_copilot.CopilotReply(content="Antwort", configured=True))
    # schneller Bot: Titel kommt mit der Antwort
    monkeypatch.setattr(chat_titel, "_ki_titel", lambda frage: chat_titel.bereinigen('Titel: „Top-Vermittler Süd 2025“.'))
    chat_id = client.post("/api/chat/conversations", json={}, headers=BROWSER_A).json()["id"]
    r = client.post(f"/api/chat/conversations/{chat_id}/messages", json={"inhalt": "wer sind die besten im süden 2025?"},
                    headers=BROWSER_A).json()
    assert r["titel"] == "Top-Vermittler Süd 2025"
    # Folgenachricht: Titel bleibt, kein neuer Bot-Aufruf
    monkeypatch.setattr(chat_titel, "_ki_titel", lambda frage: pytest.fail("nur der erste Austausch bekommt einen Titel"))
    assert client.post(f"/api/chat/conversations/{chat_id}/messages", json={"inhalt": "und 2024?"},
                       headers=BROWSER_A).json()["titel"] == "Top-Vermittler Süd 2025"

    # langsamer Bot: Antwort wartet nicht, erst Ersatztitel, KI-Titel wird nachgetragen
    freigabe = threading.Event()
    monkeypatch.setattr(chat_titel, "_ki_titel",
                        lambda frage: "Gespräch mit Dr. Hans Baumann" if freigabe.wait(5) else None)
    neuer_chat_id = client.post("/api/chat/conversations", json={}, headers=BROWSER_A).json()["id"]
    assert neuer_chat_id != chat_id
    chat_id = neuer_chat_id
    start = time.monotonic()
    r = client.post(f"/api/chat/conversations/{chat_id}/messages", json={"inhalt": "ich rede heute mit Dr. Hans Baumann"},
                    headers=BROWSER_A).json()
    dauer = time.monotonic() - start
    freigabe.set()
    assert dauer < 3 and r["titel"] == "ich rede heute mit Dr. Hans Baumann"
    for _ in range(40):
        workspace = client.get("/api/chat/workspace", headers=BROWSER_A).json()
        titel = {c["id"]: c["titel"] for c in workspace["conversations"]}.get(chat_id)
        if titel == "Gespräch mit Dr. Hans Baumann":
            break
        time.sleep(0.1)
    assert titel == "Gespräch mit Dr. Hans Baumann"


def test_titel_bereinigen():
    from backend import chat_titel

    assert chat_titel.bereinigen("\n**Rückgang Filiale Köln**.\nzweite Zeile") == "Rückgang Filiale Köln"
    assert chat_titel.bereinigen("  ") is None and chat_titel.bereinigen(None) is None
    lang = chat_titel.bereinigen("Sehr ausführlicher Titel über viele verschiedene Themen und noch mehr")
    assert len(lang) <= chat_titel.MAX_LAENGE and lang.endswith("…")



def test_startvorschlaege_sind_vorberechnet_und_top10_ist_kontobezogen(client, monkeypatch):
    from backend import openai_copilot

    def unerwarteter_modellaufruf(*args):
        pytest.fail("Startvorschlaege brauchen keinen Modellaufruf")

    monkeypatch.setattr(openai_copilot, "antwort_auf_nachricht", unerwarteter_modellaufruf)
    workspace = client.get("/api/chat/workspace", headers=BROWSER_A)
    assert workspace.json()["betreuerkonto"] == "Schumann"
    chat_id = client.post("/api/chat/conversations", json={"titel": "Start"}, headers=BROWSER_A).json()["id"]
    url = f"/api/chat/conversations/{chat_id}/messages"

    # Startantworten verwenden den Datenstand beim Start, auch nach einer Aktenaenderung.
    assert client.put("/api/vermittler/4251/geschaeftszahlen/2025",
                      json={"volumen_eur": 1, "anzahl_darlehen": 1}).status_code == 200
    for key in ("top10", "einbrueche", "gespraech", "marktgebiete", "portfolio", "karte"):
        response = client.post(url, json={"inhalt": key, "startvorschlag": key}, headers=BROWSER_A)
        assert response.status_code == 200
        if key == "top10":
            [analyse] = response.json()["analysen"]
            assert analyse["zeilen"] == [[4251, "Hans Baumann", 10773001]]
            assert analyse["titel"] == "Meine Top 10 nach Kreditvolumen 2025"
            assert [p["name"] for p in analyse["parameter"]] == ["jahr", "limit", "kennzahl", "sortierung"]
            neu = client.post(f"/api/chat/analysen/{analyse['id']}/neu-berechnen",
                              json={"werte": {"kennzahl": "anzahl", "sortierung": "asc", "limit": "5"}}, headers=BROWSER_A)
            assert neu.status_code == 200, neu.text
            assert neu.json()["diagramm"]["einheit"] == "anzahl" and neu.json()["titel"] == "Meine Top 5 nach Anzahl Darlehen 2025"
            # Betreuerkonto ist fest gebunden und nicht von aussen waehlbar
            assert client.post(f"/api/chat/analysen/{analyse['id']}/neu-berechnen",
                               json={"werte": {"konto": "MGK76244"}}, headers=BROWSER_A).status_code == 422
        if key == "karte":
            [analyse] = response.json()["analysen"]
            assert analyse["diagramm"]["typ"] == "karte"
            assert analyse["spalten"] == ["Ort", "lat", "lon", "Anzahl Vermittler", "Top-Vermittler", "Wert"]
            assert all(47 < z[1] < 55.1 and 5.8 < z[2] < 15.1 for z in analyse["zeilen"])   # alles in Deutschland
            assert [p["name"] for p in analyse["parameter"]] == ["jahr", "kennzahl", "plz_region"]
            alle_orte = {z[0] for z in analyse["zeilen"]}
            neu = client.post(f"/api/chat/analysen/{analyse['id']}/neu-berechnen",
                              json={"werte": {"plz_region": "p3", "kennzahl": "anzahl"}}, headers=BROWSER_A)
            assert neu.status_code == 200, neu.text
            assert neu.json()["titel"] == "Anzahl Darlehen 2025 nach Standort – PLZ 3 · Hannover, Kassel"
            region = {z[0] for z in neu.json()["zeilen"]}
            assert "Paderborn" in region and region < alle_orte   # 33xxx gehoert zu PLZ 3, andere fallen weg


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
    # Nur die Interessen aus der DB-Spalte (Testdaten: "Sport") sind anfangs im Profil
    assert [(f["kategorie"], f["text"]) for f in client.get("/api/vermittler/4251/profil").json()["fakten"]] == [("interessen", "Sport")]

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


def test_obsidian_netz_backlinks_ueber_index(client):
    """Netz liest den Vault nicht mehr pro Aufruf: neue Backlinks muessen trotzdem sofort erscheinen."""
    andere = [i["vermittler_nr"] for i in client.get("/api/vermittler", params={"limit": 5}).json()["items"]
              if i["vermittler_nr"] != 4251][:2]
    vorher = {k["id"] for k in client.get("/api/vermittler/4251/obsidian/netz").json()["knoten"]}  # Index steht
    assert f"VM-{andere[0]}" not in vorher
    client.post(f"/api/vermittler/{andere[0]}/obsidian/eintraege", json={"titel": "Tipp", "inhalt": "Kennt [[VM-4251|Hans]]."})
    client.post(f"/api/vermittler/{andere[1]}/obsidian/eintraege", json={"titel": "Ohne Bezug", "inhalt": "[[VM-42510]] ist jemand anderes."})
    nachher = {k["id"]: k for k in client.get("/api/vermittler/4251/obsidian/netz").json()["knoten"]}
    assert nachher[f"VM-{andere[0]}"]["detail"] == "erwähnt diesen Vermittler"
    assert f"VM-{andere[1]}" not in nachher  # VM-42510 ist kein Link auf VM-4251


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
    assert profil == {"Sport": "interessen", "Hat einen Hund namens Tim": "haustiere", "War im Oktober auf Mallorca": "reisen"}
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
    assert [f["text"] for f in client.get("/api/vermittler/4251/profil").json()["fakten"]] == ["Sport"]

    assert client.post(f"/api/chat/aenderungen/{vorschlag['id']}/bestaetigen", headers=BROWSER_A).status_code == 200
    assert sorted(f["text"] for f in client.get("/api/vermittler/4251/profil").json()["fakten"]) == [
        "Hat einen Hund namens Tim", "Sport"]
    notizen = client.get("/api/vermittler/4251/obsidian/inhalt").json()["eintraege"]
    assert any("- [ ] Konditionen schicken" in e["inhalt"] for e in notizen)


def _xlsx(r):
    import io

    import openpyxl
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml")
    assert r.headers["content-disposition"].startswith("attachment;")
    return openpyxl.load_workbook(io.BytesIO(r.content))


def test_excel_export_analyse(client):
    r = client.post("/api/export/tabelle", json={
        "titel": "Top 3 Vermittler 2025", "spalten": ["vermittler", "volumen_eur"],
        "zeilen": [["Martin Otto", 14902000], ["=HYPERLINK(\"http://boese\")", 1]], "sql": "SELECT 1"})
    wb = _xlsx(r)
    ws = wb["Analyse"]
    assert [c.value for c in ws[1]] == ["vermittler", "volumen_eur"]
    assert ws["A2"].value == "Martin Otto" and ws["B2"].value == 14902000 and "€" in ws["B2"].number_format
    assert ws["A3"].data_type == "s"  # Formel-Einschleusung: bleibt Text
    assert wb["Info"]["B5"].value == "SELECT 1"
    assert client.post("/api/export/tabelle", json={"titel": "x", "spalten": ["a"], "zeilen": [[1, 2]]}).status_code == 422


def test_excel_export_partnerakte(client):
    wb = _xlsx(client.get("/api/vermittler/4251/export.xlsx"))
    assert wb.sheetnames == ["Partnerprofil", "Geschäftszahlen", "Persönliches Profil", "Notizen"]
    felder = {row[0].value: row[1].value for row in wb["Partnerprofil"].iter_rows(min_row=2)}
    assert felder["Vermittlernummer"] == 4251 and felder["E-Mail"] == "abc.aaa@abc.de" and "Sport" in felder["Interessen"]
    jahre = [row[0].value for row in wb["Geschäftszahlen"].iter_rows(min_row=2)]
    assert jahre == [2023, 2024, 2025, 2026]
    assert client.get("/api/vermittler/999999/export.xlsx").status_code == 404


def _docx(text: str) -> bytes:
    import io
    import zipfile
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as zf:
        zf.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    return puffer.getvalue()


def _xlsx_bytes() -> bytes:
    import io
    wb = openpyxl.Workbook()
    wb.active.append(["Vermittler", "Volumen"])
    wb.active.append(["Weber", 1200000])
    puffer = io.BytesIO()
    wb.save(puffer)
    return puffer.getvalue()


PNG_1PX = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def test_anhaenge_hochladen_und_pruefen(client):
    chat_id = client.post("/api/chat/conversations", json={"titel": "t"}, headers=BROWSER_A).json()["id"]
    url = f"/api/chat/conversations/{chat_id}/anhaenge"
    for name, daten, art, enthaelt in [
        ("protokoll.txt", "Gespräch mit Weber: Praxisgründung 2027".encode("utf-8"), "text", "Praxisgründung"),
        ("protokoll.docx", _docx("Konditionen schicken bis Freitag"), "text", "Konditionen schicken"),
        ("zahlen.xlsx", _xlsx_bytes(), "text", "Weber;1200000"),
        ("notiz.png", PNG_1PX, "bild", None),
    ]:
        r = client.post(url, files={"datei": (name, daten)}, headers=BROWSER_A)
        assert r.status_code == 201, (name, r.text)
        assert r.json()["art"] == art and r.json()["name"] == name
    text = client.post("/api/sql/query", json={"sql": "SELECT text FROM chat_anhang WHERE name = 'zahlen.xlsx'"}).json()
    assert "Weber;1200000" in text["zeilen"][0][0]

    # Abgelehnt: falscher Typ, leer, fremder Browser
    assert client.post(url, files={"datei": ("virus.exe", b"MZ")}, headers=BROWSER_A).json()["fehler_code"] == "ANHANG_TYP"
    assert client.post(url, files={"datei": ("leer.txt", b"")}, headers=BROWSER_A).json()["fehler_code"] == "ANHANG_LEER"
    assert client.post(url, files={"datei": ("a.txt", b"x")}, headers=BROWSER_B).status_code == 404
    # Unbekannte Anhang-ID beim Senden -> 404, nichts wird still ignoriert
    r = client.post(f"/api/chat/conversations/{chat_id}/messages", json={"inhalt": "x", "anhaenge": ["gibtsnicht"]},
                    headers=BROWSER_A)
    assert r.status_code == 404


class _FakeAnhangOpenAI(_FakeOpenAI):
    gesehen: list = []

    def create(self, model, instructions, tools, input, **_):
        if instructions == SYSTEM_INSTRUCTIONS_REF[0]:
            _FakeAnhangOpenAI.gesehen.append(input[-1])
        return _FakeResponse(text="Zusammenfassung: Weber plant eine Praxisgründung.")


SYSTEM_INSTRUCTIONS_REF: list = []


def test_anhang_geht_mit_der_nachricht_an_die_ki(client, monkeypatch):
    import openai

    from backend import openai_copilot
    SYSTEM_INSTRUCTIONS_REF[:] = [openai_copilot.SYSTEM_INSTRUCTIONS]
    _FakeAnhangOpenAI.gesehen = []
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai, "OpenAI", _FakeAnhangOpenAI)
    chat_id = client.post("/api/chat/conversations", json={"titel": "t"}, headers=BROWSER_A).json()["id"]
    url = f"/api/chat/conversations/{chat_id}/anhaenge"
    text_id = client.post(url, files={"datei": ("p.txt", "Weber plant Praxisgründung".encode())}, headers=BROWSER_A).json()["id"]
    bild_id = client.post(url, files={"datei": ("n.png", PNG_1PX)}, headers=BROWSER_A).json()["id"]

    r = client.post(f"/api/chat/conversations/{chat_id}/messages",
                    json={"inhalt": "Fasse zusammen", "anhaenge": [text_id, bild_id]}, headers=BROWSER_A)
    assert r.status_code == 200, r.text
    [letzte] = _FakeAnhangOpenAI.gesehen
    teile = letzte["content"]
    assert teile[0]["type"] == "input_text" and "Weber plant Praxisgründung" in teile[0]["text"]
    assert teile[1]["type"] == "input_image" and teile[1]["image_url"].startswith("data:image/png;base64,")
    # Anhaenge stehen in der gespeicherten Nutzernachricht (fuer die Anzeige als Chip)
    verlauf = client.get("/api/chat/workspace", headers=BROWSER_A).json()["messages_by_conversation"][chat_id]
    assert [a["name"] for a in verlauf[0]["metadata"]["anhaenge"]] == ["p.txt", "n.png"]


def test_partnerakte_fuer_ki_enthaelt_letzte_gespraeche_und_offene_massnahmen(client):
    from backend import db, openai_copilot
    client.post("/api/vermittler/4251/obsidian/eintraege", json={
        "typ": "gespraech", "titel": "Jahresgespräch 2026", "datum": "2026-11-20",
        "inhalt": "Plant zweite Praxis in Bielefeld, braucht Finanzierung bis Q2.",
        "massnahmen": [{"beschreibung": "Konditionen schicken", "verantwortlich": "Schumann", "faellig_am": "2026-12-01"}]})
    conn = db.connect()
    try:
        akte, *_ = openai_copilot._execute_tool(conn, "hole_partnerakte", {"vermittler_nr": 4251})
    finally:
        conn.close()
    [gespraech] = akte["letzte_gespraeche"]
    assert gespraech["titel"] == "Jahresgespräch 2026" and "zweite Praxis in Bielefeld" in gespraech["inhalt"]
    assert akte["anzahl_eintraege_gesamt"] == 1
    assert akte["offene_massnahmen"] == [{"massnahme": "Konditionen schicken", "verantwortlich": "Schumann",
                                          "faellig_am": "2026-12-01", "aus_notiz": "Jahresgespräch 2026",
                                          "notiert_am": "2026-11-20"}]


def test_vermittlersuche_mit_titel_und_namensgleichen(client):
    from backend import db, openai_copilot
    assert client.post("/api/vermittler", json={"vorname": "Susanne", "name": "Baumann", "anrede": "Sehr geehrte Frau"}).status_code == 201
    conn = db.connect()
    try:
        def treffer(q):
            return [(i["vorname"], i["name"]) for i in openai_copilot._search_vermittler(conn, q)["items"]]
        assert treffer("Dr. Hans Baumann") == [("Hans", "Baumann")]          # Titel steht nicht im Namen
        assert treffer("Prof. Dr. med. Hans Baumann") == [("Hans", "Baumann")]
        assert treffer("Herrn Dr. Baumann") == [("Hans", "Baumann")]         # Titel/Anrede als Filter
        assert treffer("Frau Baumann") == [("Susanne", "Baumann")]
        assert sorted(treffer("Baumann")) == [("Hans", "Baumann"), ("Susanne", "Baumann")]  # echt mehrdeutig
    finally:
        conn.close()


class _FakeParameterOpenAI(_FakeOpenAI):
    SQL = ("SELECT v.vermittler_nr, TRIM(COALESCE(v.titel || ' ', '') || v.vorname || ' ' || v.name) AS vermittler, "
           "SUM(CASE :kennzahl WHEN 'anzahl' THEN g.anzahl_darlehen ELSE g.volumen_eur END) AS wert "
           "FROM v_vermittler v JOIN geschaeftszahlen g ON g.vermittler_nr = v.vermittler_nr "
           "WHERE g.sparte = 'gesamt' AND (:jahr = 'gesamt' OR g.jahr = :jahr) "
           "GROUP BY v.vermittler_nr ORDER BY wert DESC LIMIT :limit")
    PARAMETER = [
        {"name": "jahr", "label": "Jahr", "standard": "2025", "optionen": [
            {"wert": "2024", "label": "2024", "einheit": ""}, {"wert": "2025", "label": "2025", "einheit": ""},
            {"wert": "gesamt", "label": "alle Jahre", "einheit": ""}]},
        {"name": "limit", "label": "Anzahl", "standard": "2", "optionen": [
            {"wert": "1", "label": "Top 1", "einheit": ""}, {"wert": "2", "label": "Top 2", "einheit": ""}]},
        {"name": "kennzahl", "label": "Kennzahl", "standard": "volumen", "optionen": [
            {"wert": "volumen", "label": "Volumen", "einheit": "eur"}, {"wert": "anzahl", "label": "Anzahl Darlehen", "einheit": "anzahl"}]},
        {"name": "gibtsnicht", "label": "x", "standard": "a", "optionen": [  # kommt im SQL nicht vor -> verworfen
            {"wert": "a", "label": "a", "einheit": ""}, {"wert": "b", "label": "b", "einheit": ""}]},
    ]

    def create(self, model, instructions, tools, input, **_):
        from backend import openai_copilot
        schon = any(isinstance(i, dict) and i.get("type") == "function_call_output" for i in input)
        if instructions == openai_copilot.ANALYSE_INSTRUCTIONS or schon:
            return _FakeResponse(text="KEINE" if instructions == openai_copilot.ANALYSE_INSTRUCTIONS else "Fertig.")
        return _FakeResponse([_FakeCall("sql_analyse", {
            "titel": "Top {limit} nach {kennzahl} ({jahr})", "sql": self.SQL, "parameter": self.PARAMETER,
            "diagramm": {"typ": "balken", "x": "vermittler", "y": "wert", "einheit": "eur"}}, "c1")])


def test_analyse_auswahlfelder_berechnen_neu_ohne_ki(client, monkeypatch):
    import openai

    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai, "OpenAI", _FakeParameterOpenAI)
    chat_id = client.post("/api/chat/conversations", json={"titel": "t"}, headers=BROWSER_A).json()["id"]
    r = client.post(f"/api/chat/conversations/{chat_id}/messages", json={"inhalt": "Wer ist Top-Vermittler?"}, headers=BROWSER_A)
    [analyse] = r.json()["analysen"]
    assert [p["name"] for p in analyse["parameter"]] == ["jahr", "limit", "kennzahl"]   # wirkungsloses Feld verworfen
    assert analyse["titel"] == "Top Top 2 nach Volumen (2025)" and analyse["werte"] == {"jahr": "2025", "limit": "2", "kennzahl": "volumen"}
    assert [z[1] for z in analyse["zeilen"]] == ["Martin Otto", "Dr. Hans Baumann"] and analyse["spalten"][0] == "vermittler_nr"

    url = f"/api/chat/analysen/{analyse['id']}/neu-berechnen"
    neu = client.post(url, json={"werte": {"jahr": "2024", "limit": "1"}}, headers=BROWSER_A)
    assert neu.status_code == 200, neu.text
    assert neu.json()["zeilen"] == [[4251, "Dr. Hans Baumann", 21242499]]               # 2024 fuehrt Baumann
    anzahl = client.post(url, json={"werte": {"kennzahl": "anzahl"}}, headers=BROWSER_A).json()
    assert anzahl["diagramm"]["einheit"] == "anzahl" and anzahl["werte"]["jahr"] == "2024"  # Auswahl bleibt erhalten

    # Nur erlaubte Werte, nur eigener Browser
    assert client.post(url, json={"werte": {"jahr": "1999"}}, headers=BROWSER_A).status_code == 422
    assert client.post(url, json={"werte": {"limit": "1; DROP TABLE vermittler"}}, headers=BROWSER_A).status_code == 422
    assert client.post(url, json={"werte": {"jahr": "2024"}}, headers=BROWSER_B).status_code == 404
    # Nach dem Neuladen steht die zuletzt gewaehlte Auswahl im Verlauf
    verlauf = client.get("/api/chat/workspace", headers=BROWSER_A).json()["messages_by_conversation"][chat_id]
    assert verlauf[-1]["metadata"]["analysen"][0]["werte"]["kennzahl"] == "anzahl"


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


def test_vermittlernamen_werden_verlinkt(client):
    from backend import db, vermittler_links
    conn = db.connect()
    try:
        text = ("**Dr. Hans Baumann** ist Top-Partner. Bereits verlinkt: [Dr. Hans Baumann](obsidian://x), "
                "`Dr. Hans Baumann` bleibt Code. Unbekannt: Max Mustermann.")
        out = vermittler_links.verlinke(conn, text)
        # Mehrdeutigkeit: zwei Vermittler gleichen Namens -> nur mit Werkzeug-Hinweis verlinken
        conn.execute("INSERT INTO vermittler (vermittler_nr, vorname, name, status) VALUES (777001, 'Hans', 'Baumann', 'aktiv')")
        conn.execute("INSERT INTO vermittler (vermittler_nr, vorname, name, status) VALUES (777002, 'Hans', 'Baumann', 'aktiv')")
        mehrdeutig = vermittler_links.verlinke(conn, "Hans Baumann")
        eindeutig = vermittler_links.verlinke(conn, "Hans Baumann", [777002])
        conn.rollback()
    finally:
        conn.close()
    assert "**[Dr. Hans Baumann](partner:4251)**" in out
    assert "[Dr. Hans Baumann](obsidian://x)" in out and "`Dr. Hans Baumann`" in out
    assert "Max Mustermann" in out and "partner:" not in out.split("Unbekannt:")[1]
    assert mehrdeutig == "Hans Baumann"
    assert eindeutig == "[Hans Baumann](partner:777002)"
    assert vermittler_links.nummern_in({"items": [{"vermittler_nr": 5}], "spalten": ["vermittler_nr", "x"],
                                         "zeilen": [[6, 1]]}) == {5, 6}


def test_chat_antwort_enthaelt_partner_links(client):
    conversation = client.post("/api/chat/conversations", json={"titel": "Neue Unterhaltung"}, headers=BROWSER_A).json()
    reply = client.post(f"/api/chat/conversations/{conversation['id']}/messages",
                        json={"inhalt": "Zeig mir die Partnerakte von Hans Baumann"}, headers=BROWSER_A).json()
    assert "[Dr. Hans Baumann](partner:4251)" in reply["message"]["content"]


def test_interessen_aus_db_im_obsidian_profil(client):
    from backend import obsidian
    # Import hat die DB-Interessen ins Profil uebernommen (oben unter "## Interessen")
    profil_path = settings.vault_path / obsidian.profil_rel(4251)
    text = profil_path.read_text(encoding="utf-8")
    assert text.index("## Interessen") < text.index("## Familie") and "- Sport" in text
    assert client.get("/api/vermittler/4251").json()["interessen_profil"] == ["Sport"]

    # Per Chat/API ergaenzte Interessen erscheinen zusaetzlich, Stichwort-Erkennung inklusive
    r = client.post("/api/vermittler/4251/profil/fakten", json={"text": "Interessiert sich für Praxisgründung"})
    assert r.json()["kategorie"] == "interessen"
    client.post("/api/vermittler/4251/profil/fakten", json={"text": "Golf", "kategorie": "interessen"})
    assert client.get("/api/vermittler/4251").json()["interessen_profil"] == [
        "Sport", "Interessiert sich für Praxisgründung", "Golf"]

    # Neue Interessen in der DB werden ergaenzt, ohne Doppelte; im Profil Geloeschtes bleibt geloescht
    client.patch("/api/vermittler/4251", json={"interessen": ["Sport", "Golf", "Segeln"]})
    assert client.get("/api/vermittler/4251").json()["interessen_profil"] == [
        "Sport", "Interessiert sich für Praxisgründung", "Golf", "Segeln"]
    text = profil_path.read_text(encoding="utf-8")
    assert text.count("- Sport") == 1 and text.count("Golf") == 1

    # Alte Profile ohne "## Interessen" bekommen die Ueberschrift oben eingefuegt
    alt = text.split("## Interessen")[0] + "## Familie" + text.split("## Familie")[1]
    profil_path.write_text(alt, encoding="utf-8")
    assert client.get("/api/vermittler/4251").json()["interessen_profil"] == ["Sport", "Golf", "Segeln"]
    neu = profil_path.read_text(encoding="utf-8")
    assert neu.index("## Interessen") < neu.index("## Familie")
