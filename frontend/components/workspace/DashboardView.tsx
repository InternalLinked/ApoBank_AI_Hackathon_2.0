import type { Analysis, DashboardData } from "@/lib/workspace-contracts";
import { AnalysisCard } from "./AnalysisPanel";
import { formatValue } from "./AnalysisChart";
import { Icon } from "./Icons";

type DashboardViewProps = {
  data: DashboardData | null;
  loading: boolean;
  onReload: () => void;
  onOpenChats: () => void;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  inspectorCollapsed: boolean;
  onToggleInspector: () => void;
  onExport: (analysis: Analysis) => Promise<void>;
  onRerun: (analysis: Analysis, values: Record<string, string>) => Promise<Analysis>;
  onOpenPartner: (vermittlerNr: number, name: string) => void;
};

/** Die lange Tabelle braucht die volle Breite; die übrigen Diagramme stehen zu zweit nebeneinander */
const WIDE = new Set(["dashboard-liste"]);

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "up" | "down" }) {
  return (
    <div className="dashboard-kpi">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small className={tone ? `is-${tone}` : ""}>{hint}</small>}
    </div>
  );
}

export function DashboardView({ data, loading, onReload, onOpenChats, sidebarCollapsed, onToggleSidebar, inspectorCollapsed, onToggleInspector, onExport, onRerun, onOpenPartner }: DashboardViewProps) {
  const kpis = data?.kpis;
  const change = kpis?.changePercent ?? null;
  return (
    <main className="conversation-pane dashboard-pane">
      <header className="topbar">
        <button className="icon-button chats-mobile-trigger" type="button" aria-controls="chat-sidebar" aria-label="Chatverläufe öffnen" onClick={onOpenChats}><Icon name="menu" /></button>
        <button className="icon-button sidebar-toggle" type="button" aria-controls="chat-sidebar" aria-expanded={!sidebarCollapsed} aria-label={sidebarCollapsed ? "Chatleiste einblenden" : "Chatleiste einklappen"} title={sidebarCollapsed ? "Chatleiste einblenden" : "Chatleiste einklappen"} onClick={onToggleSidebar}>
          <Icon name="panel" />
        </button>
        <div className="topbar-actions">
          <button type="button" className="analysis-secondary-button" onClick={onReload} disabled={loading}>{loading ? "Lädt …" : "Aktualisieren"}</button>
          <button className="icon-button" type="button" aria-label={inspectorCollapsed ? "Partnerakte-Leiste einblenden" : "Partnerakte-Leiste einfahren"} title={inspectorCollapsed ? "Partnerakte-Leiste einblenden" : "Partnerakte-Leiste einfahren"} onClick={onToggleInspector}><Icon name="panel" /></button>
        </div>
      </header>

      <section className="conversation-heading">
        <div className="heading-mark"><Icon name="dashboard" size={15} /></div>
        <div className="heading-copy">
          <span>DASHBOARD · {data ? [data.advisor.branch, data.advisor.marketArea && `Marktgebiet ${data.advisor.marketArea}`].filter(Boolean).join(" · ").toUpperCase() : "BERATER"}</span>
          <h1>{data ? `Meine Vermittler – ${data.advisor.name}` : "Meine Vermittler"}</h1>
        </div>
      </section>

      <div className="analysis-scroll dashboard-scroll">
        {!data && <p className="dashboard-loading">{loading ? "Dashboard wird geladen …" : "Das Dashboard konnte nicht geladen werden."}</p>}
        {data && (
          <div className="dashboard-content">
            {kpis && (
              <div className="dashboard-kpis" aria-label="Kennzahlen">
                <Kpi label="Meine Vermittler" value={kpis.partnerCount.toLocaleString("de-DE")} hint={`${kpis.activePartners} aktiv`} />
                <Kpi label={`Kreditvolumen ${kpis.year}`} value={formatValue(kpis.volume, "eur", true)}
                  hint={change === null ? undefined : `${change > 0 ? "+" : ""}${change.toLocaleString("de-DE")} % zu ${kpis.previousYear}`}
                  tone={change === null ? undefined : change >= 0 ? "up" : "down"} />
                <Kpi label={`Kreditvolumen ${kpis.previousYear}`} value={formatValue(kpis.previousVolume, "eur", true)} />
                <Kpi label={`Darlehen ${kpis.year}`} value={kpis.loanCount.toLocaleString("de-DE")}
                  hint={kpis.partnerCount ? `Ø ${(kpis.loanCount / kpis.partnerCount).toLocaleString("de-DE", { maximumFractionDigits: 1 })} je Vermittler` : undefined} />
              </div>
            )}
            <div className="dashboard-grid">
              {data.analyses.map((analysis) => (
                <div key={analysis.id} className={WIDE.has(analysis.id) ? "is-wide" : ""}>
                  <AnalysisCard analysis={analysis} focused={false} onExport={onExport} onRerun={onRerun} onOpenPartner={onOpenPartner} />
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
