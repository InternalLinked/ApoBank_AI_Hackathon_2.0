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


def test_chat_loeschen(client):
    chat_id = client.post("/api/chat/conversations", json={"titel": "Test"}).json()["id"]
    andere_id = client.post("/api/chat/conversations", json={"titel": "Bleibt"}).json()["id"]

    assert client.delete(f"/api/chat/conversations/{chat_id}").status_code == 204
    workspace = client.get("/api/chat/workspace").json()
    assert [c["id"] for c in workspace["conversations"]] == [andere_id]
    assert chat_id not in workspace["messages_by_conversation"]
    assert client.delete(f"/api/chat/conversations/{chat_id}").status_code == 404


def test_fehlerformat_mit_code_und_request_id(client):
    r = client.get("/api/vermittler/999999")
    body = r.json()
    assert r.status_code == 404
    assert body["fehler_code"] == "NICHT_GEFUNDEN" and body["detail"]
    assert body["request_id"] and r.headers["X-Request-ID"] == body["request_id"]

    r = client.post("/api/chat/conversations", json={"titel": ""})
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
