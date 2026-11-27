import { useEffect, useRef, useState } from "react";
import type { Analysis } from "@/lib/workspace-contracts";
import { AnalysisChart, chartPoints, formatValue } from "./AnalysisChart";
import { Icon } from "./Icons";

type AnalysisPanelProps = {
  analyses: Analysis[];
  focusedId: string | null;
  onBackToChat: () => void;
};

function DataTable({ analysis }: { analysis: Analysis }) {
  const yIndex = analysis.columns.indexOf(analysis.chart.y);
  return (
    <div className="analysis-table-wrap">
      <table className="analysis-table">
        <thead><tr>{analysis.columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
        <tbody>
          {analysis.rows.map((row, r) => (
            <tr key={r}>
              {row.map((cell, c) => (
                <td key={c} className={typeof cell === "number" ? "is-number" : ""}>
                  {cell === null ? "–" : typeof cell === "number" && c === yIndex ? formatValue(cell, analysis.chart.unit) : typeof cell === "number" ? cell.toLocaleString("de-DE") : cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {analysis.truncated && <p className="chart-note">Ergebnis gekürzt auf {analysis.rowCount} Zeilen.</p>}
    </div>
  );
}

/** SQL-Ansicht vorerst ausgeblendet – auf true setzen, um "SQL-Code anzeigen" wieder einzublenden. */
const SQL_ANZEIGEN = false;

function AnalysisCard({ analysis, focused }: { analysis: Analysis; focused: boolean }) {
  const hasChart = chartPoints(analysis) !== null;
  const [showSql, setShowSql] = useState(false);
  const [showTable, setShowTable] = useState(!hasChart);
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focused]);

  async function copySql() {
    try {
      await navigator.clipboard.writeText(analysis.sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setShowSql(true); // ohne Zwischenablage (z. B. ohne HTTPS): SQL wenigstens sichtbar machen
    }
  }

  return (
    <article ref={ref} className={`analysis-card ${focused ? "is-focused" : ""}`} aria-label={analysis.title}>
      <header className="analysis-card-head">
        <div>
          <h3>{analysis.title}</h3>
          <span>{analysis.createdAt} · {analysis.rowCount} {analysis.rowCount === 1 ? "Zeile" : "Zeilen"} · Quelle: Vermittler-Datenbank</span>
        </div>
      </header>

      {hasChart && <AnalysisChart analysis={analysis} />}
      {showTable && <DataTable analysis={analysis} />}

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

export function AnalysisPanel({ analyses, focusedId, onBackToChat }: AnalysisPanelProps) {
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
        {analyses.map((analysis) => <AnalysisCard key={analysis.id} analysis={analysis} focused={analysis.id === focusedId} />)}
      </div>
    </div>
  );
}
