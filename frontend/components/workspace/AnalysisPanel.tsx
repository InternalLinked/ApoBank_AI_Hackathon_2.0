import { useEffect, useMemo, useRef, useState } from "react";
import type { Analysis, ChartUnit } from "@/lib/workspace-contracts";
import { AnalysisChart, chartPoints, formatValue, toNumber, type Point } from "./AnalysisChart";
import { Icon } from "./Icons";

type AnalysisPanelProps = {
  analyses: Analysis[];
  focusedId: string | null;
  onBackToChat: () => void;
  /** Lädt das Ergebnis als .xlsx herunter; Fehler meldet der Aufrufer */
  onExport: (analysis: Analysis) => Promise<void>;
  /** Auswahlfeld der KI geändert → Backend rechnet mit dem gespeicherten SQL neu (wirft bei Fehler) */
  onRerun: (analysis: Analysis, values: Record<string, string>) => Promise<Analysis>;
  /** Klick auf einen Vermittler (Balken oder Tabellenzeile) → Partnerakte rechts */
  onOpenPartner: (vermittlerNr: number, name: string) => void;
};

/** Kennungen und Jahre: ohne Tausenderpunkt anzeigen („4251“, nicht „4.251“) und nie als Kennzahl anbieten */
const ID_COLUMN = /(^|_)(nr|id|knr|plz|jahr)$|^(lat|lon)$/i;
/** Spalte mit der Vermittlernummer – macht Balken und Zeilen klickbar */
const PARTNER_NR_COLUMN = /^vermittler_?nr$/i;
const PARTNER_NAME_COLUMN = /^(vermittler|vermittler_name|name)$/i;

type SortOrder = "original" | "desc" | "asc";
type View = { y: string | null; sort: SortOrder; top: string };

/** Einheit für eine Spalte, die die KI nicht als Kennzahl gewählt hat – aus dem Spaltennamen geraten */
function guessUnit(column: string): ChartUnit {
  const name = column.toLowerCase();
  if (/prozent|pct|quote|anteil/.test(name)) return "prozent";
  if (/eur|volumen|betrag|umsatz/.test(name)) return "eur";
  if (/anzahl|darlehen|count|^n$/.test(name)) return "anzahl";
  return "keine";
}

function prettyColumn(column: string): string {
  const text = column.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Zahlenspalten, zwischen denen das Diagramm wechseln kann (ohne Kennungen/Jahre und ohne die Beschriftungsspalte) */
function metricColumns(analysis: Analysis): string[] {
  const numeric = analysis.columns.filter((column, index) => {
    if (column === analysis.chart.x || ID_COLUMN.test(column)) return false;
    const values = analysis.rows.map((row) => row[index]).filter((cell) => cell !== null);
    return values.length > 0 && values.every((cell) => toNumber(cell) !== null);
  });
  const current = analysis.chart.y;
  return analysis.columns.includes(current) ? [current, ...numeric.filter((column) => column !== current)] : numeric;
}

/** Sortierung, Top-N und Kennzahl im Browser anwenden – das Backend wird dafür nicht gefragt */
function applyView(analysis: Analysis, view: View): Analysis {
  const y = view.y && analysis.columns.includes(view.y) ? view.y : analysis.chart.y;
  const unit = y === analysis.chart.y ? analysis.chart.unit : guessUnit(y);
  const yi = analysis.columns.indexOf(y);
  // Balken nach Vermittlernummer beschriftet? Lieber den Namen zeigen – die Nummer bleibt für den Klick in der Zeile
  const nameColumn = analysis.columns.find((column) => PARTNER_NAME_COLUMN.test(column));
  const x = PARTNER_NR_COLUMN.test(analysis.chart.x) && nameColumn ? nameColumn : analysis.chart.x;
  let rows = analysis.rows;
  if (view.sort !== "original" && yi >= 0) {
    const direction = view.sort === "desc" ? -1 : 1;
    rows = [...rows].sort((a, b) => {
      const av = toNumber(a[yi]);
      const bv = toNumber(b[yi]);
      if (av === null) return bv === null ? 0 : 1; // leere Werte immer ans Ende
      if (bv === null) return -1;
      return (av - bv) * direction;
    });
  }
  if (view.top !== "alle") rows = rows.slice(0, Number(view.top));
  return { ...analysis, rows, chart: { ...analysis.chart, x, y, unit } };
}

function formatCell(cell: string | number | null, column: string, analysis: Analysis): string {
  if (cell === null) return "–";
  if (typeof cell !== "number") return cell;
  if (ID_COLUMN.test(column)) return String(cell);
  if (column === analysis.chart.y) return formatValue(cell, analysis.chart.unit);
  const unit = guessUnit(column);
  return unit === "keine" ? cell.toLocaleString("de-DE") : formatValue(cell, unit);
}

type PartnerTarget = { vermittlerNr: number; name: string };

/** Vermittler einer Ergebniszeile (nur wenn die Analyse eine Spalte vermittler_nr hat) */
function partnerOf(analysis: Analysis, row: Array<string | number | null>): PartnerTarget | null {
  const nrIndex = analysis.columns.findIndex((column) => PARTNER_NR_COLUMN.test(column));
  if (nrIndex < 0) return null;
  const nr = toNumber(row[nrIndex]);
  if (nr === null || !Number.isInteger(nr) || nr <= 0) return null;
  const nameIndex = analysis.columns.findIndex((column) => PARTNER_NAME_COLUMN.test(column));
  const xIndex = analysis.columns.indexOf(analysis.chart.x);
  const nameCell = nameIndex >= 0 ? row[nameIndex] : xIndex >= 0 && xIndex !== nrIndex ? row[xIndex] : null;
  return { vermittlerNr: nr, name: nameCell == null ? `VM-${nr}` : String(nameCell) };
}

function DataTable({ analysis, onOpenPartner }: { analysis: Analysis; onOpenPartner?: (target: PartnerTarget) => void }) {
  const nameIndex = analysis.columns.findIndex((column) => PARTNER_NAME_COLUMN.test(column));
  const xIndex = analysis.columns.indexOf(analysis.chart.x);
  const nrIndex = analysis.columns.findIndex((column) => PARTNER_NR_COLUMN.test(column));
  // Spalte, die als Link zur Partnerakte erscheint: Name, sonst Beschriftung, sonst die Nummer selbst
  const linkIndex = nameIndex >= 0 ? nameIndex : xIndex >= 0 && xIndex !== nrIndex ? xIndex : nrIndex;
  // Die Nummer ist nur der Schlüssel für den Klick – ausblenden, wenn der Name verlinkt ist (Excel-Export behält sie)
  const visible = analysis.columns.map((_, c) => !(onOpenPartner && c === nrIndex && linkIndex !== nrIndex));
  return (
    <div className="analysis-table-wrap">
      <table className="analysis-table">
        <thead><tr>{analysis.columns.map((column, c) => visible[c] && <th key={column} scope="col">{column}</th>)}</tr></thead>
        <tbody>
          {analysis.rows.map((row, r) => {
            const target = onOpenPartner ? partnerOf(analysis, row) : null;
            return (
              <tr key={r} className={target ? "is-clickable" : ""} onClick={target ? () => onOpenPartner?.(target) : undefined}>
                {row.map((cell, c) => {
                  if (!visible[c]) return null;
                  const text = formatCell(cell, analysis.columns[c], analysis);
                  return (
                    <td key={c} className={typeof cell === "number" && !ID_COLUMN.test(analysis.columns[c]) ? "is-number" : ""}>
                      {target && c === linkIndex ? (
                        <button type="button" className="analysis-partner-link" title="Partnerakte öffnen"
                          onClick={(event) => { event.stopPropagation(); onOpenPartner?.(target); }}>
                          {text}
                        </button>
                      ) : text}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      {analysis.truncated && <p className="chart-note">Ergebnis gekürzt auf {analysis.rowCount} Zeilen.</p>}
    </div>
  );
}

/** SQL-Ansicht vorerst ausgeblendet – auf true setzen, um "SQL-Code anzeigen" wieder einzublenden. */
const SQL_ANZEIGEN = false;

const TOP_OPTIONS = [5, 10, 25];

type AnalysisCardProps = {
  analysis: Analysis;
  focused: boolean;
  forecastThroughYear?: number;
  onExport: (a: Analysis) => Promise<void>;
  onRerun: AnalysisPanelProps["onRerun"];
  onOpenPartner: AnalysisPanelProps["onOpenPartner"];
};

export function AnalysisCard({ analysis, focused, forecastThroughYear, onExport, onRerun, onOpenPartner }: AnalysisCardProps) {
  const [view, setView] = useState<View>({ y: null, sort: "desc", top: "alle" });
  /** Gerade gewählte Werte, während das Backend neu rechnet (danach kommt die neue Analyse als Prop) */
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [exporting, setExporting] = useState(false);
  const [showSql, setShowSql] = useState(false);
  const [showTable, setShowTable] = useState(() => chartPoints(analysis) === null);
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLElement>(null);

  const metrics = useMemo(() => metricColumns(analysis), [analysis]);
  const parameterNames = new Set(analysis.parameters.map((parameter) => parameter.name));
  const isBar = analysis.chart.type === "balken";
  // Eigene Auswahlfelder nur, wo die KI keine passenden festgelegt hat
  const showMetric = !parameterNames.has("kennzahl") && metrics.length >= 2;
  const topOptions = TOP_OPTIONS.filter((n) => n < analysis.rows.length);
  const showTop = isBar && !parameterNames.has("limit") && topOptions.length > 0;
  // Nach Jahr/Kennung beschriftete Balken behalten ihre Reihenfolge (2023, 2024 …) – dort keine Sortierung anbieten
  const showSort = isBar && analysis.rows.length > 1 && !parameterNames.has("sortierung") && !ID_COLUMN.test(analysis.chart.x);
  // Auswahl, die nach einer Neuberechnung nicht mehr passt (z. B. Top 10 bei nur 8 Zeilen), fällt auf den Standard zurück
  const effective: View = {
    y: showMetric && view.y && metrics.includes(view.y) ? view.y : null,
    sort: showSort ? view.sort : "original",
    top: showTop && topOptions.includes(Number(view.top)) ? view.top : "alle",
  };
  const shown = applyView(analysis, effective); // höchstens 200 Zeilen – günstig genug für jeden Render
  const hasChart = chartPoints(shown) !== null;
  const hasPartners = analysis.rows.some((row) => partnerOf(analysis, row) !== null);
  const hasControls = analysis.parameters.length > 0 || showMetric || showTop || showSort;
  const pending = draft !== null;

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focused]);

  async function changeParameter(name: string, value: string) {
    const values = { ...analysis.values, [name]: value };
    setDraft(values);
    try {
      await onRerun(analysis, values);
    } catch {
      // Hinweis mit Fehlercode zeigt der Workspace; die Karte behält die bisherige Auswahl
    } finally {
      setDraft(null);
    }
  }

  function openPartner(target: PartnerTarget | null) {
    if (target) onOpenPartner(target.vermittlerNr, target.name);
  }

  function selectBar(point: Point) {
    openPartner(partnerOf(shown, shown.rows[point.rowIndex]));
  }

  async function exportExcel() {
    setExporting(true);
    try {
      await onExport(shown); // exportiert, was gerade zu sehen ist (Sortierung, Top-N)
    } finally {
      setExporting(false);
    }
  }

  async function copySql() {
    try {
      await navigator.clipboard.writeText(analysis.sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setShowSql(true); // ohne Zwischenablage (z. B. ohne HTTPS): SQL wenigstens sichtbar machen
    }
  }

  const topLabel = effective.top === "alle" ? null : `Top ${shown.rows.length} von ${analysis.rows.length}`;

  return (
    <article ref={ref} className={`analysis-card ${focused ? "is-focused" : ""}`} aria-label={analysis.title}>
      <header className="analysis-card-head">
        <div>
          <h3>{analysis.title}</h3>
          <span>
            {analysis.createdAt} · {topLabel ?? `${analysis.rowCount} ${analysis.rowCount === 1 ? "Zeile" : "Zeilen"}`} · Quelle: Vermittler-Datenbank
            {hasPartners && isBar && hasChart && " · Balken anklicken öffnet die Partnerakte"}
          </span>
        </div>
      </header>

      {hasControls && (
        <div className="analysis-controls" role="group" aria-label={`Auswahl für „${analysis.title}“`}>
          {analysis.parameters.map((parameter) => (
            <label key={parameter.name} className="analysis-control">
              <span>{parameter.label}</span>
              <select value={(draft ?? analysis.values)[parameter.name] ?? ""} disabled={pending}
                onChange={(event) => void changeParameter(parameter.name, event.target.value)}>
                {parameter.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
          ))}
          {showMetric && (
            <label className="analysis-control">
              <span>Kennzahl</span>
              <select value={shown.chart.y} disabled={pending}
                onChange={(event) => {
                  const y = event.target.value;
                  setView((current) => ({ ...current, y }));
                }}>
                {metrics.map((column) => <option key={column} value={column}>{prettyColumn(column)}</option>)}
              </select>
            </label>
          )}
          {showTop && (
            <label className="analysis-control">
              <span>Anzeigen</span>
              <select value={effective.top} disabled={pending} onChange={(event) => setView((current) => ({ ...current, top: event.target.value }))}>
                {topOptions.map((n) => <option key={n} value={String(n)}>Top {n}</option>)}
                <option value="alle">Alle ({analysis.rows.length})</option>
              </select>
            </label>
          )}
          {showSort && (
            <label className="analysis-control">
              <span>Sortierung</span>
              <select value={effective.sort} disabled={pending} onChange={(event) => setView((current) => ({ ...current, sort: event.target.value as SortOrder }))}>
                <option value="desc">Größte zuerst</option>
                <option value="asc">Kleinste zuerst</option>
              </select>
            </label>
          )}
          {pending && <span className="analysis-control-status" role="status"><span className="voice-spinner" aria-hidden="true" /> Wird neu berechnet …</span>}
        </div>
      )}

      <div className={`analysis-body ${pending ? "is-pending" : ""}`} aria-busy={pending}>
        {shown.rows.length === 0 && <p className="analysis-no-rows">Keine Daten für diese Auswahl.</p>}
        {hasChart && (
          <AnalysisChart analysis={shown} forecastThroughYear={forecastThroughYear} onSelect={hasPartners ? selectBar : undefined} selectHint="Klicken öffnet die Partnerakte" />
        )}
        {(showTable || !hasChart) && shown.rows.length > 0 && (
          <DataTable analysis={shown} onOpenPartner={hasPartners ? openPartner : undefined} />
        )}
      </div>

      <div className="analysis-actions">
        {SQL_ANZEIGEN && (
          <button type="button" className="analysis-sql-button" aria-expanded={showSql} onClick={() => setShowSql((v) => !v)}>
            <Icon name="file" size={14} /> {showSql ? "SQL-Code ausblenden" : "SQL-Code anzeigen"}
          </button>
        )}
        {hasChart && (
          <button type="button" className="analysis-secondary-button" aria-expanded={showTable} onClick={() => setShowTable((v) => !v)}>
            {showTable ? "Tabelle ausblenden" : "Tabelle anzeigen"}
          </button>
        )}
        <button type="button" className="excel-button" onClick={() => void exportExcel()} disabled={exporting || pending || shown.rows.length === 0}
          title="Ergebnis als Excel-Datei (.xlsx) herunterladen – so, wie es gerade angezeigt wird">
          {exporting ? <span className="voice-spinner" aria-hidden="true" /> : <Icon name="file" size={14} />}
          {exporting ? "Wird erstellt …" : "Excel exportieren"}
        </button>
      </div>

      {SQL_ANZEIGEN && showSql && (
        <div className="analysis-sql">
          <div className="analysis-sql-head">
            <span>Verwendetes SQL (read-only ausgeführt)</span>
            <button type="button" onClick={copySql} aria-label="SQL kopieren" title="SQL kopieren">
              <Icon name={copied ? "check" : "copy"} size={14} /> {copied ? "Kopiert" : "Kopieren"}
            </button>
          </div>
          <pre><code>{analysis.sql}</code></pre>
        </div>
      )}
    </article>
  );
}

export function AnalysisPanel({ analyses, focusedId, onBackToChat, onExport, onRerun, onOpenPartner }: AnalysisPanelProps) {
  if (analyses.length === 0) {
    return (
      <div className="analysis-empty">
        <div className="empty-orbit"><Icon name="sparkle" size={22} /></div>
        <h2>Noch keine Analyse</h2>
        <p>Frage im Chat z. B. „Wer ist der Top-Vermittler 2025?“ – das Diagramm erscheint dann hier.</p>
        <button type="button" className="analysis-secondary-button" onClick={onBackToChat}>Zum Chat</button>
      </div>
    );
  }
  return (
    <div className="analysis-scroll">
      <div className="analysis-column">
        {analyses.map((analysis) => (
          <AnalysisCard key={analysis.id} analysis={analysis} focused={analysis.id === focusedId}
            onExport={onExport} onRerun={onRerun} onOpenPartner={onOpenPartner} />
        ))}
      </div>
    </div>
  );
}
