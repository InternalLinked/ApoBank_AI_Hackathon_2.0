# Geodaten für die Kartenansicht

Offene Daten, einmalig aufbereitet mit `erzeugen.py` (keine Kundendaten, kein externer Dienst zur Laufzeit).

| Datei | Inhalt | Quelle / Lizenz |
|---|---|---|
| `plz_koordinaten.csv` | PLZ → Ort, Mittelpunkt (lat/lon) | [GeoNames](https://download.geonames.org/export/zip/) – CC BY 4.0 |
| `frontend/components/workspace/deutschlandKarte.ts` | Bundesländer als SVG-Pfade | © GeoBasis-DE / BKG, über [geoBoundaries](https://www.geoboundaries.org) – Datenlizenz Deutschland – Namensnennung 2.0 |

`db.init_db` lädt die CSV in die Tabelle `plz_koordinaten`, falls sie leer ist.

Neu erzeugen:

```powershell
# DE.zip von GeoNames entpacken, geoBoundaries-DEU-ADM1_simplified.geojson herunterladen
.venv\Scripts\python -m backend.geodaten.erzeugen <DE.txt> <geoBoundaries-DEU-ADM1_simplified.geojson>
```
