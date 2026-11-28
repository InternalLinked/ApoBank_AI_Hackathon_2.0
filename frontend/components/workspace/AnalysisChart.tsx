import { useMemo, useState } from "react";
import type { Analysis, ChartUnit } from "@/lib/workspace-contracts";

/*
 * Diagramm ohne externe Bibliothek (reines SVG):
 * - balken: horizontale Balken – Rankings/Vergleiche, lange Namen bleiben lesbar
 * - linie:  Verlauf über Kategorien (z. B. Jahre), 2px-Linie, Punkte mit Ring, Fadenkreuz beim Hovern
 * Eine Datenreihe in einer Farbe → keine Legende, der Titel benennt die Reihe.
 * Werte stehen im Tooltip; direkt beschriftet wird nur der größte Wert.
 */

const W = 640;
const MARK = "#17427f";
const MARK_HOVER = "#0d2857";
const GRID = "#e6ebf2";
const AXIS_TEXT = "#6b7a88";
const MAX_BARS = 25;

export type Point = { label: string; value: number; rowIndex: number };

export function formatValue(value: number, unit: ChartUnit, compact = false): string {
  if (unit === "eur") {
    if (compact && Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toLocaleString("de-DE", { maximumFractionDigits: 1 })} Mio. €`;
    if (compact && Math.abs(value) >= 1_000) return `${(value / 1_000).toLocaleString("de-DE", { maximumFractionDigits: 0 })} Tsd. €`;
    return value.toLocaleString("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
  }
  if (unit === "prozent") return `${value.toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`;
  return value.toLocaleString("de-DE", { maximumFractionDigits: unit === "anzahl" ? 0 : 2 });
}

export function toNumber(cell: string | number | null): number | null {
  if (typeof cell === "number") return Number.isFinite(cell) ? cell : null;
  if (typeof cell === "string" && cell.trim() !== "" && Number.isFinite(Number(cell))) return Number(cell);
  return null;
}

/** Datenpunkte aus Spalte x/y; null, wenn keine Grafik sinnvoll ist (dann zeigt das Panel die Tabelle). */
export function chartPoints(analysis: Analysis): Point[] | null {
  if (analysis.chart.type === "tabelle") return null;
  const xi = analysis.columns.indexOf(analysis.chart.x);
  const yi = analysis.columns.indexOf(analysis.chart.y);
  if (xi < 0 || yi < 0 || xi === yi) return null;
  const points = analysis.rows
    .map((row, rowIndex) => ({ label: row[xi] == null ? "–" : String(row[xi]), value: toNumber(row[yi]), rowIndex }))
    .filter((point): point is Point => point.value !== null);
  return points.length > 0 ? points : null;
}

/** „Schöne“ Achsenteilung (1/2/5 × 10^n) inkl. 0 */
function niceTicks(min: number, max: number, count = 4): number[] {
  const lo = Math.min(0, min);
  const hi = Math.max(0, max);
  if (lo === hi) return [0, 1];
  const raw = (hi - lo) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((f) => f * magnitude).find((s) => s >= raw) ?? raw;
  const ticks: number[] = [];
  for (let t = Math.floor(lo / step) * step; t <= hi + step * 0.001; t += step) ticks.push(Number(t.toPrecision(12)));
  if (ticks[ticks.length - 1] < hi) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** Balken mit abgerundetem Datenende (4px), Basislinie bleibt eckig */
function barPath(x0: number, x1: number, y: number, h: number): string {
  const r = Math.min(4, Math.abs(x1 - x0) / 2, h / 2);
  if (x1 >= x0) {
    return `M${x0},${y} H${x1 - r} Q${x1},${y} ${x1},${y + r} V${y + h - r} Q${x1},${y + h} ${x1 - r},${y + h} H${x0} Z`;
  }
  return `M${x0},${y} H${x1 + r} Q${x1},${y} ${x1},${y + r} V${y + h - r} Q${x1},${y + h} ${x1 + r},${y + h} H${x0} Z`;
}

type TooltipState = { left: number; top: number; label: string; value: string; hint?: string } | null;

function Tooltip({ tip }: { tip: TooltipState }) {
  if (!tip) return null;
  return (
    <div className="chart-tooltip" style={{ left: `${tip.left}%`, top: `${tip.top}%` }} role="status">
      <span>{tip.label}</span>
      <strong>{tip.value}</strong>
      {tip.hint && <em>{tip.hint}</em>}
    </div>
  );
}

type SelectProps = {
  /** Klick/Enter auf einen Balken (z. B. Partnerakte öffnen); ohne → nicht klickbar */
  onSelect?: (point: Point) => void;
  /** Hinweis im Tooltip, z. B. „Klicken öffnet die Partnerakte“ */
  selectHint?: string;
};

function BarChart({ points, unit, title, onSelect, selectHint }: { points: Point[]; unit: ChartUnit; title: string } & SelectProps) {
  const [hover, setHover] = useState<number | null>(null);
  const shown = points.slice(0, MAX_BARS);
  const labelChars = Math.min(28, Math.max(...shown.map((p) => p.label.length)));
  const labelW = Math.min(210, labelChars * 6.4 + 14);
  const rowH = 30;
  const barH = 18;
  const top = 6;
  const axisH = 26;
  const H = top + shown.length * rowH + axisH;
  const ticks = niceTicks(Math.min(...shown.map((p) => p.value)), Math.max(...shown.map((p) => p.value)));
  const lo = ticks[0];
  const hi = ticks[ticks.length - 1];
  const plotL = labelW;
  const plotR = W - 70; // Platz für die Direktbeschriftung des größten Werts
  const sx = (v: number) => plotL + ((v - lo) / (hi - lo)) * (plotR - plotL);
  const maxIndex = shown.reduce((best, p, i) => (p.value > shown[best].value ? i : best), 0);
  const tip: TooltipState = hover === null ? null : {
    left: (Math.max(sx(shown[hover].value), sx(0)) / W) * 100,
    top: ((top + hover * rowH + rowH / 2) / H) * 100,
    label: shown[hover].label,
    value: formatValue(shown[hover].value, unit),
    hint: onSelect ? selectHint : undefined,
  };

  return (
    <div className={onSelect ? "chart-frame is-selectable" : "chart-frame"}>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: Balkendiagramm mit ${shown.length} Einträgen`} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={sx(t)} x2={sx(t)} y1={top} y2={H - axisH} stroke={GRID} strokeWidth={1} />
            <text x={sx(t)} y={H - 8} textAnchor="middle" className="chart-axis-text" fill={AXIS_TEXT}>{formatValue(t, unit, true)}</text>
          </g>
        ))}
        {shown.map((p, i) => {
          const y = top + i * rowH + (rowH - barH) / 2;
          const x0 = sx(0);
          const x1 = sx(p.value);
          return (
            <g key={`${p.label}-${i}`}>
              <text x={labelW - 10} y={y + barH / 2} textAnchor="end" dominantBaseline="central" className="chart-label-text">
                <title>{p.label}</title>
                {truncate(p.label, 28)}
              </text>
              <path d={barPath(x0, x1, y, barH)} fill={hover === i ? MARK_HOVER : MARK} />
              {i === maxIndex && (
                <text x={Math.max(x0, x1) + 6} y={y + barH / 2} dominantBaseline="central" className="chart-value-text">{formatValue(p.value, unit, true)}</text>
              )}
              {/* Trefferfläche größer als der Balken: ganze Zeile */}
              <rect x={0} y={top + i * rowH} width={W} height={rowH} fill="transparent" onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0}
                aria-label={`${p.label}: ${formatValue(p.value, unit)}${onSelect && selectHint ? ` – ${selectHint}` : ""}`}
                role={onSelect ? "button" : undefined}
                className={onSelect ? "chart-hit is-clickable" : "chart-hit"}
                onClick={onSelect ? () => onSelect(p) : undefined}
                onKeyDown={onSelect ? (event) => {
                  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(p); }
                } : undefined} />
            </g>
          );
        })}
        <line x1={sx(0)} x2={sx(0)} y1={top} y2={H - axisH} stroke="#b9c4d2" strokeWidth={1} />
      </svg>
      <Tooltip tip={tip} />
      {points.length > MAX_BARS && <p className="chart-note">Es werden die ersten {MAX_BARS} von {points.length} Zeilen gezeigt – alle stehen in der Tabelle.</p>}
    </div>
  );
}

function LineChart({ points, unit, title }: { points: Point[]; unit: ChartUnit; title: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const H = 260;
  const padL = 72;
  const padR = 24;
  const top = 16;
  const axisH = 30;
  const ticks = niceTicks(Math.min(...points.map((p) => p.value)), Math.max(...points.map((p) => p.value)));
  const lo = ticks[0];
  const hi = ticks[ticks.length - 1];
  const step = points.length > 1 ? (W - padL - padR) / (points.length - 1) : 0;
  const sx = (i: number) => (points.length > 1 ? padL + i * step : (padL + W - padR) / 2);
  const sy = (v: number) => top + (1 - (v - lo) / (hi - lo)) * (H - top - axisH);
  const d = points.map((p, i) => `${i === 0 ? "M" : "L"}${sx(i)},${sy(p.value)}`).join(" ");
  const labelEvery = Math.ceil(points.length / 10);
  const maxIndex = points.reduce((best, p, i) => (p.value > points[best].value ? i : best), 0);
  const tip: TooltipState = hover === null ? null : {
    left: (sx(hover) / W) * 100,
    top: (sy(points[hover].value) / H) * 100,
    label: points[hover].label,
    value: formatValue(points[hover].value, unit),
  };

  return (
    <div className="chart-frame">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: Liniendiagramm mit ${points.length} Punkten`} onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={sy(t)} y2={sy(t)} stroke={GRID} strokeWidth={1} />
            <text x={padL - 8} y={sy(t)} textAnchor="end" dominantBaseline="central" className="chart-axis-text" fill={AXIS_TEXT}>{formatValue(t, unit, true)}</text>
          </g>
        ))}
        {points.map((p, i) => i % labelEvery === 0 && (
          <text key={`x-${i}`} x={sx(i)} y={H - 10} textAnchor="middle" className="chart-axis-text" fill={AXIS_TEXT}>{truncate(p.label, 12)}</text>
        ))}
        {hover !== null && <line x1={sx(hover)} x2={sx(hover)} y1={top} y2={H - axisH} stroke="#9fb0c4" strokeWidth={1} strokeDasharray="3 3" />}
        <path d={d} fill="none" stroke={MARK} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {points.map((p, i) => (
          <circle key={`p-${i}`} cx={sx(i)} cy={sy(p.value)} r={hover === i ? 5 : 4} fill={MARK} stroke="#fff" strokeWidth={2} />
        ))}
        <text x={sx(maxIndex)} y={sy(points[maxIndex].value) - 12} textAnchor="middle" className="chart-value-text">{formatValue(points[maxIndex].value, unit, true)}</text>
        {points.map((p, i) => (
          <rect key={`hit-${i}`} x={sx(i) - Math.max(step, 24) / 2} y={top} width={Math.max(step, 24)} height={H - top - axisH} fill="transparent"
            onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0} aria-label={`${p.label}: ${formatValue(p.value, unit)}`} />
        ))}
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

export function AnalysisChart({ analysis, onSelect, selectHint }: { analysis: Analysis } & SelectProps) {
  const points = useMemo(() => chartPoints(analysis), [analysis]);
  if (!points) return null;
  return analysis.chart.type === "linie"
    ? <LineChart points={points} unit={analysis.chart.unit} title={analysis.title} />
    : <BarChart points={points} unit={analysis.chart.unit} title={analysis.title} onSelect={onSelect} selectHint={selectHint} />;
}
