"""Erzeugt die Geodaten fuer die Kartenansicht aus offenen Quellen (einmalig, Ergebnis liegt im Repo).

Quellen (siehe README.md in diesem Ordner):
  - PLZ-Koordinaten: GeoNames, https://download.geonames.org/export/zip/DE.zip  (CC BY 4.0)
  - Bundeslaender:   geoBoundaries DEU ADM1 (simplified), Quelle BKG             (dl-de/by-2.0)

Aufruf:  python -m backend.geodaten.erzeugen <DE.txt> <geoBoundaries-DEU-ADM1_simplified.geojson>
Schreibt backend/geodaten/plz_koordinaten.csv und frontend/components/workspace/deutschlandKarte.ts.
Es werden keine Kundendaten verwendet oder versendet.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HIER = Path(__file__).resolve().parent
TS_ZIEL = HIER.parents[1] / "frontend" / "components" / "workspace" / "deutschlandKarte.ts"

# Projektion – muss zu projiziere() in deutschlandKarte.ts passen (wird mit ausgegeben)
LON0, LAT0 = 5.6, 55.2
SKALA = 62.0
KOS = math.cos(math.radians(51.2))
TOLERANZ = 0.7          # Douglas-Peucker in SVG-Pixeln
MIN_FLAECHE = 4.0       # kleinere Inseln weglassen (px²)


def projiziere(lon: float, lat: float) -> tuple[float, float]:
    return (lon - LON0) * KOS * SKALA, (LAT0 - lat) * SKALA


def _dp(punkte: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    if len(punkte) < 3:
        return punkte
    (x1, y1), (x2, y2) = punkte[0], punkte[-1]
    dx, dy = x2 - x1, y2 - y1
    laenge = math.hypot(dx, dy) or 1e-9
    index, maximum = 0, -1.0
    for i in range(1, len(punkte) - 1):
        px, py = punkte[i]
        d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / laenge
        if d > maximum:
            index, maximum = i, d
    if maximum <= tol:
        return [punkte[0], punkte[-1]]
    return _dp(punkte[: index + 1], tol)[:-1] + _dp(punkte[index:], tol)


def _flaeche(ring: list[tuple[float, float]]) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))) / 2


def _pfad(geometrie: dict) -> str:
    polygone = geometrie["coordinates"] if geometrie["type"] == "MultiPolygon" else [geometrie["coordinates"]]
    teile = []
    for polygon in polygone:
        for ring in polygon[:1]:  # nur Aussenring – Loecher sind bei Bundeslaendern Stadtstaaten, die eigene Flaechen haben
            punkte = [projiziere(lon, lat) for lon, lat in ring]
            if _flaeche(punkte) < MIN_FLAECHE:
                continue
            # Ring in zwei Haelften vereinfachen, damit Anfang und Ende erhalten bleiben
            mitte = len(punkte) // 2
            einfach = _dp(punkte[: mitte + 1], TOLERANZ)[:-1] + _dp(punkte[mitte:], TOLERANZ)
            if len(einfach) >= 4:
                teile.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in einfach[:-1]) + "Z")
    return "".join(teile)


def plz_tabelle(geonames: Path) -> None:
    orte: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
    with geonames.open(encoding="utf-8") as datei:
        for zeile in csv.reader(datei, delimiter="\t"):
            orte[zeile[1]].append((zeile[2], float(zeile[9]), float(zeile[10])))
    with (HIER / "plz_koordinaten.csv").open("w", encoding="utf-8", newline="") as ziel:
        schreiber = csv.writer(ziel, delimiter=";")
        schreiber.writerow(["plz", "ort", "lat", "lon"])
        for plz in sorted(orte):
            eintraege = orte[plz]
            lat = sum(e[1] for e in eintraege) / len(eintraege)
            lon = sum(e[2] for e in eintraege) / len(eintraege)
            schreiber.writerow([plz, eintraege[0][0], f"{lat:.4f}", f"{lon:.4f}"])


def karte(geojson: Path) -> None:
    daten = json.loads(geojson.read_text(encoding="utf-8"))
    laender = sorted(((f["properties"]["shapeName"], _pfad(f["geometry"])) for f in daten["features"]))
    alle = [p for _, p in laender]
    xs = [float(t.split(",")[0]) for p in alle for t in p.replace("M", "L").replace("Z", "").split("L") if t]
    ys = [float(t.split(",")[1]) for p in alle for t in p.replace("M", "L").replace("Z", "").split("L") if t]
    breite, hoehe = math.ceil(max(xs)) + 4, math.ceil(max(ys)) + 4
    zeilen = [
        "// Automatisch erzeugt von backend/geodaten/erzeugen.py – nicht von Hand bearbeiten.",
        "// Bundeslaender: © GeoBasis-DE / BKG (via geoBoundaries), Datenlizenz Deutschland – Namensnennung 2.0",
        "",
        f"export const KARTE_BREITE = {breite};",
        f"export const KARTE_HOEHE = {hoehe};",
        "",
        "/** Laengen-/Breitengrad -> SVG-Koordinaten (gleiche Projektion wie die Umrisse) */",
        "export function projiziere(lon: number, lat: number): [number, number] {",
        f"  return [(lon - {LON0}) * {KOS:.6f} * {SKALA}, ({LAT0} - lat) * {SKALA}];",
        "}",
        "",
        "export const BUNDESLAENDER: { name: string; pfad: string }[] = [",
        *[f"  {{ name: {json.dumps(name, ensure_ascii=False)}, pfad: \"{pfad}\" }}," for name, pfad in laender],
        "];",
        "",
    ]
    TS_ZIEL.write_text("\n".join(zeilen), encoding="utf-8")


if __name__ == "__main__":
    plz_tabelle(Path(sys.argv[1]))
    karte(Path(sys.argv[2]))
    print("plz_koordinaten.csv und deutschlandKarte.ts geschrieben")
