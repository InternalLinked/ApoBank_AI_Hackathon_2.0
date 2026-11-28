import { useMemo, useState } from "react";
import type { Analysis, ChartUnit } from "@/lib/workspace-contracts";
import { BUNDESLAENDER, KARTE_BREITE, KARTE_HOEHE, projiziere } from "./deutschlandKarte";

/*
 * Deutschlandkarte ohne externe Kartendienste (reines SVG, Umrisse liegen im Repo):
 * je Zeile eine Blase an lat/lon, Fläche ∝ Wert (nicht der Radius – sonst wirkt das Doppelte viermal so groß).
 * Sind die Blasen auf eine Region beschränkt (z. B. PLZ-Filter), zoomt die Karte dorthin.
 */

const LAT_COLUMN = /^(lat|breitengrad)$/i;
const LON_COLUMN = /^(lon|lng|laengengrad)$/i;
const MARK = "#17427f";
const MARK_HOVER = "#0d2857";
const R_MAX = 24;          // Radius der größten Blase bei ganzer Karte (SVG-Einheiten)
const R_MIN = 2.5;
const LABELS = 5;          // die größten Standorte direkt beschriften

type Bubble = { label: string; value: number; x: number; y: number; r: number; rowIndex: number; details: string[] };

/** Hat die Analyse Koordinatenspalten? Sonst kann keine Karte gezeichnet werden. */
export function hasCoordinates(analysis: Analysis): boolean {
  return analysis.columns.some((c) => LAT_COLUMN.test(c)) && analysis.columns.some((c) => LON_COLUMN.test(c));
}

function num(cell: string | number | null): number | null {
  const n = typeof cell === "number" ? cell : typeof cell === "string" && cell.trim() !== "" ? Number(cell) : NaN;
  return Number.isFinite(n) ? n : null;
}

type MapChartProps = {
  analysis: Analysis;
  format: (value: number, unit: ChartUnit, compact?: boolean) => string;
};

export function MapChart({ analysis, format }: MapChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const [pinned, setPinned] = useState<number | null>(null);
  const { columns, rows, chart } = analysis;

  const { bubbles, view, zoom } = useMemo(() => {
    const lat = columns.findIndex((c) => LAT_COLUMN.test(c));
    const lon = columns.findIndex((c) => LON_COLUMN.test(c));
    const xi = columns.indexOf(chart.x);
    const yi = columns.indexOf(chart.y);
    // Weitere Spalten (z. B. Anzahl Vermittler, Top-Vermittler) erscheinen im Tooltip
    const extra = columns.map((c, i) => i).filter((i) => i !== lat && i !== lon && i !== xi && i !== yi);
    const raw = rows.flatMap((row, rowIndex) => {
      const la = num(row[lat]);
      const lo = num(row[lon]);
      const value = num(row[yi]);
      if (la === null || lo === null || value === null || value <= 0) return [];
      const [x, y] = projiziere(lo, la);
      const details = extra.filter((i) => row[i] !== null && row[i] !== "").map((i) => {
        const cell = row[i];
        return `${columns[i]}: ${typeof cell === "number" ? cell.toLocaleString("de-DE") : cell}`;
      });
      return [{ label: row[xi] == null ? "–" : String(row[xi]), value, x, y, rowIndex, details }];
    });

    // Ausschnitt: ganze Karte, außer die Blasen liegen deutlich enger beieinander
    let vx = 0, vy = 0, vw = KARTE_BREITE, vh = KARTE_HOEHE;
    if (raw.length > 0) {
      const pad = 34;
      const minX = Math.min(...raw.map((b) => b.x)), maxX = Math.max(...raw.map((b) => b.x));
      const minY = Math.min(...raw.map((b) => b.y)), maxY = Math.max(...raw.map((b) => b.y));
      const ratio = KARTE_HOEHE / KARTE_BREITE;
      let w = Math.max(maxX - minX + 2 * pad, 150);
      let h = Math.max(maxY - minY + 2 * pad, 150 * ratio);
      if (w / h > 1 / ratio) h = w * ratio; else w = h / ratio;   // Seitenverhältnis der Karte beibehalten
      if (w < KARTE_BREITE * 0.75) {
        vx = Math.max(0, Math.min((minX + maxX) / 2 - w / 2, KARTE_BREITE - w));
        vy = Math.max(0, Math.min((minY + maxY) / 2 - h / 2, KARTE_HOEHE - h));
        vw = w;
        vh = h;
      }
    }
    const zoom = KARTE_BREITE / vw;
    const max = Math.max(...raw.map((b) => b.value), 1);
    // Fläche proportional zum Wert; Radius in Karteneinheiten so, dass die Blasen beim Zoomen gleich groß bleiben
    const bubbles: Bubble[] = raw
      .map((b) => ({ ...b, r: Math.max(R_MIN, Math.sqrt(b.value / max) * R_MAX) / zoom }))
      .sort((a, b) => b.r - a.r); // große zuerst zeichnen, kleine liegen oben und bleiben erreichbar
    return { bubbles, view: { x: vx, y: vy, w: vw, h: vh }, zoom };
  }, [columns, rows, chart.x, chart.y]);

  if (bubbles.length === 0) return null;
  const active = pinned ?? hover;
  const tip = active === null ? null : bubbles[active];
  const labelled = new Set(bubbles.slice(0, LABELS).map((b) => b.rowIndex));
  const stroke = 1 / zoom;

  return (
    <div className="chart-frame chart-map" onMouseLeave={() => setHover(null)}>
      <div className="map-stage">
      <svg viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} role="img"
        aria-label={`${analysis.title}: Deutschlandkarte mit ${bubbles.length} Standorten`}>
        <g className="map-laender">
          {BUNDESLAENDER.map((land) => (
            <path key={land.name} d={land.pfad} strokeWidth={stroke}><title>{land.name}</title></path>
          ))}
        </g>
        {bubbles.map((b, i) => (
          <circle key={`${b.label}-${b.rowIndex}`} cx={b.x} cy={b.y} r={b.r} tabIndex={0}
            className={`map-bubble ${active === i ? "is-active" : ""}`} fill={active === i ? MARK_HOVER : MARK}
            stroke="#fff" strokeWidth={stroke}
            aria-label={`${b.label}: ${format(b.value, chart.unit)}`}
            onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}
            onClick={() => setPinned((current) => (current === i ? null : i))} />
        ))}
        {bubbles.filter((b) => labelled.has(b.rowIndex)).map((b) => (
          <text key={`l-${b.rowIndex}`} x={b.x} y={b.y - b.r - 3 / zoom} textAnchor="middle" className="map-label"
            style={{ fontSize: `${11 / zoom}px`, strokeWidth: `${3 / zoom}px` }}>{b.label}</text>
        ))}
      </svg>
      {tip && (
        <div className="chart-tooltip map-tooltip" role="status"
          style={{ left: `${((tip.x - view.x) / view.w) * 100}%`, top: `${((tip.y - view.y) / view.h) * 100}%` }}>
          <span>{tip.label}</span>
          <strong>{format(tip.value, chart.unit)}</strong>
          {tip.details.map((line) => <small key={line}>{line}</small>)}
        </div>
      )}
      </div>
      <p className="chart-note">
        Blasenfläche entspricht dem Wert · {pinned !== null ? "Klick erneut zum Lösen" : "Klick hält die Details fest"} ·
        Karte: © GeoBasis-DE / BKG, PLZ-Koordinaten: GeoNames (CC BY 4.0)
      </p>
    </div>
  );
}
