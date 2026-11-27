"""SYNTHETISCHER Demo-Datensatz im Excel-Format des Team-Imports (39 Spalten) – für Tests, Demo und Bedrock-Tests.

Alle Personen, Firmen, Adressen und Zahlen sind erfunden (Vermittlernummern 900000+, E-Mails @beispiel.invalid).
Er stellt typische Sonderfälle nach: Namensdubletten, aktive Vermittler ohne Geschäft, Wachstum ab null,
unterjähriges Jahr 2026, fehlende Interessen/Diensthandys, gesperrter Vermittler in der Spitze, Gleichstand.

Aufruf (nutzt APOBANK_DB_PATH / APOBANK_VAULT_PATH aus .env bzw. Standardpfade):
  .venv\\Scripts\\python -m backend.copilot.demo_daten --neu
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime
from pathlib import Path

from .einstellungen import lade_dotenv

lade_dotenv()

import openpyxl  # noqa: E402

from .. import db, import_excel, obsidian  # noqa: E402
from ..config import settings  # noqa: E402

HEADER = ['Marktgebiet', 'FilialNr', 'Filiale', 'Mitarbeiter_ID', 'Mitarbeiter_AP', 'VPB', 'Betreuung_seit',
          'Betreuung_bis', 'VermittlerNr', 'Name', 'Vorname', 'Titel', 'Sonstiger_Titel', 'Firma_Filiale',
          'Firma_Holding', 'Vermittlertyp', 'Geburtstag', 'Status', 'Abrechnungskreis', 'KNR', 'Adressentyp',
          'Postleitzahl', 'Ort', 'Strasse', 'Anrede', 'eMail', 'Dienstanschluss', 'Dienst_Handy',
          'Privatanschluss', 'Volumen in Euro in 2026', 'Anzahl Darlehen 2026', 'Volumen in Euro in 2025',
          'ANZ_DL_2025', 'Volumen in Euro in 2024', 'Anzahl Darlehen 2024', 'Volumen in Euro in 2023',
          'Anzahl Darlehen 2023', 'Status Vertriebspartner', 'Interessen']
MARKTGEBIETE = {"Nord": (901, "Filiale Nord (synthetisch)"), "Ost": (902, "Filiale Ost (synthetisch)"),
                "Süd": (903, "Filiale Süd (synthetisch)"), "West": (904, "Filiale West (synthetisch)"),
                "Mitte": (905, "Filiale Mitte (synthetisch)")}
VORNAMEN = ("Anna", "Thomas", "Michael", "Sandra", "Stefan", "Katrin", "Andreas", "Laura", "Markus", "Nina",
            "Tobias", "Claudia", "Florian", "Petra", "Daniel", "Sabine", "Jan", "Miriam", "Oliver", "Lena")
NACHNAMEN = ("Schneider", "Fischer", "Weber", "Meyer", "Becker", "Schulz", "Hoffmann", "Koch", "Richter", "Klein",
             "Wolf", "Neumann", "Schwarz", "Zimmermann", "Braun", "Hartmann", "Krause", "Lange", "Werner", "Frank")
INTERESSEN = ("Golf", "Segeln", "Praxisgründung", "Apothekengründung", "Digitalisierung", "Immobilien")
PARTNERSTATUS = ("Fokus-Vertriebspartner", "Standard-Vertriebspartner", "Potenzial-Vertriebspartner")
D = datetime


def _zeile(nr, vorname, name, mg, status, vol, anz, *, firma=None, seit=D(2020, 1, 1), handy=True, interessen=None,
           email=None, partner="Standard-Vertriebspartner"):
    filial_nr, filiale = MARKTGEBIETE[mg]
    v26, v25, v24, v23 = vol
    a26, a25, a24, a23 = anz
    return [mg, filial_nr, filiale, f"SYN-{mg[:2].upper()}", "SY", f"Team {mg} (synthetisch)", seit, None, nr, name,
            vorname, None, None, firma or f"{name} Finanzberatung (synthetisch)", None, "Finanzierungsvermittler", None,
            status, "Sonstige", 800000 + nr % 100000, "Firmenanschrift", "00000", f"Musterstadt {mg}", "Musterweg 1",
            None, email or f"vm{nr}@beispiel.invalid", "000 0000000", "0000 0000000" if handy else None, None,
            v26, a26, v25, a25, v24, a24, v23, a23, partner, interessen]


def zeilen(seed: int = 42, zufaellige: int = 60) -> list[list]:
    rnd = random.Random(seed)
    z = [
        _zeile(900001, "Alexander", "Müller", "Nord", "aktiv", (1_100_000, 1_900_000, 1_500_000, 1_200_000),
               (7, 12, 10, 8), firma="Müller Finanzberatung GmbH (synthetisch)", seit=D(2019, 5, 1),
               interessen="Apothekengründung, Golf", partner="Fokus-Vertriebspartner"),
        _zeile(900002, "Alexander", "Müller", "Süd", "aktiv", (300_000, 700_000, 650_000, 600_000), (2, 5, 5, 4),
               firma="AM Praxisfinanz (synthetisch)", seit=D(2021, 2, 1), interessen="Praxisgründung"),
        _zeile(900003, "Julia", "Schmidt", "West", "aktiv", (100_000, 300_000, 250_000, 200_000), (1, 3, 2, 2)),
        _zeile(900004, "Julia", "Schmidt", "Ost", "inaktiv", (0, 0, 250_000, 200_000), (0, 0, 2, 2)),
        _zeile(900005, "Julia", "Schmidt", "Mitte", "aktiv", (100_000, 300_000, 250_000, 200_000), (1, 3, 2, 2)),
        _zeile(900006, "Peter", "Lindner", "West", "aktiv", (0, 0, 0, 0), (0, 0, 0, 0), handy=False),
        _zeile(900007, "Sophie", "Brandt", "Ost", "aktiv", (150_000, 400_000, 0, 0), (1, 3, 0, 0), seit=D(2024, 3, 1),
               interessen="Immobilien"),
        _zeile(900008, "Martin", "Vogel", "Nord", "aktiv", (800_000, 1_700_000, 1_100_000, 900_000), (5, 11, 7, 6)),
        _zeile(900009, "Eva", "Roth", "Ost", "aktiv", (900_000, 1_700_000, 1_300_000, 1_000_000), (6, 11, 9, 7)),
        _zeile(900010, "Karl", "Seidel", "West", "gesperrt", (0, 1_800_000, 1_600_000, 1_400_000), (0, 12, 10, 9)),
        _zeile(900011, "Jürgen", "Köhler", "Mitte", "aktiv", (400_000, 610_000, 520_000, 500_000), (3, 5, 4, 4),
               email="kontakt@beispiel.invalid"),
        _zeile(900012, "Lena", "Wirth", "Mitte", "inaktiv", (0, 0, 0, 100_000), (0, 0, 0, 1), email="kontakt@beispiel.invalid"),
    ]
    for i in range(zufaellige):
        mg = rnd.choice(list(MARKTGEBIETE))
        status = rnd.choices(("aktiv", "inaktiv", "gesperrt"), weights=(85, 12, 3))[0]
        basis = rnd.randrange(0, 1_000_001, 10_000) if rnd.random() > 0.15 else 0
        vol = [0 if basis == 0 else min(1_490_000, int(basis * rnd.uniform(0.7, 1.4)) // 1000 * 1000) for _ in range(4)]
        vol[0] = vol[0] * 3 // 4 // 1000 * 1000  # 2026 unterjährig
        anz = [0 if v == 0 else max(1, v // 150_000) for v in vol]
        z.append(_zeile(900100 + i, rnd.choice(VORNAMEN), rnd.choice(NACHNAMEN), mg, status, tuple(vol), tuple(anz),
                        seit=D(rnd.randint(2015, 2025), rnd.randint(1, 12), 1), handy=rnd.random() > 0.15,
                        interessen=", ".join(rnd.sample(INTERESSEN, rnd.randint(1, 2))) if rnd.random() > 0.15 else None,
                        partner=rnd.choice(PARTNERSTATUS)))
    return z


def schreibe_excel(pfad: Path, seed: int = 42) -> Path:
    wb = openpyxl.Workbook()
    wb.active.title = "Synthetisch"
    wb.active.append(HEADER)
    for z in zeilen(seed):
        wb.active.append(z)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    wb.save(pfad)
    return pfad


def demo_gespraech(conn) -> None:
    """Ein früheres Gespräch mit Maßnahmen für die Demo-Persona 900001 (über die Team-Funktion add_entry)."""
    v = db.get_vermittler_full(conn, 900001)
    res = obsidian.add_entry(v, {
        "typ": "gespraech", "titel": "Jahresgespräch 2026", "datum": date(2026, 10, 15),
        "teilnehmer": ["Alexander Müller", "Team Nord"],
        "inhalt": "Stabiles Geschäft 2025. Interesse an Apothekengründungen in der Region.\n\n"
                  "**Vereinbart:** Infoabend Existenzgründung im Januar; Konditionsblatt 2026 zusenden.\n\n"
                  "**Für das nächste Gespräch:** Nach Rückmeldung zum Infoabend fragen.\n\n_Synthetische Demodaten._",
        "massnahmen": [
            {"beschreibung": "Unterlagen zur Praxisfinanzierung nachreichen", "verantwortlich": "Vermittler",
             "faellig_am": date(2026, 11, 10)},
            {"beschreibung": "Konditionsblatt 2026 zusenden", "verantwortlich": "Team Nord", "faellig_am": date(2026, 12, 5)},
            {"beschreibung": "Infoabend Existenzgründung organisieren (geplant)", "verantwortlich": "Team Nord",
             "faellig_am": date(2027, 1, 20)}],
        "tags": ["demo"], "autor": "Demo-Daten", "quelle": "synthetisch"})
    conn.execute("INSERT INTO obsidian_eintrag (vermittler_nr, typ, titel, datum, datei, autor, quelle) "
                 "VALUES (900001, ?, ?, ?, ?, 'Demo-Daten', 'synthetisch')",
                 (res["typ"], res["titel"], res["datum"], res["datei"]))
    conn.commit()


def erzeuge(excel_pfad: Path, reset: bool = True) -> dict:
    schreibe_excel(excel_pfad)
    ergebnis = import_excel.run(excel_pfad, reset=reset)
    conn = db.connect()
    try:
        demo_gespraech(conn)
    finally:
        conn.close()
    return ergebnis


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--neu", action="store_true", help="Datenbank zurücksetzen (Vault-Ordner vorher selbst leeren)")
    ap.add_argument("--excel", type=Path, default=Path("data/demo_synthetisch.xlsx"))
    args = ap.parse_args(argv)
    if Path(settings.db_path).exists() and not args.neu:
        print(f"{settings.db_path} existiert. Mit --neu neu aufbauen.")
        return 1
    res = erzeuge(args.excel, reset=args.neu)
    print(f"Synthetische Demo-Daten: {res} | DB {settings.db_path} | Vault {settings.vault_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
