import { useEffect, useRef } from "react";
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

const LEFT_COLUMN = new Set(["dashboard-verlauf", "dashboard-karte"]);
const PORTFOLIO_LIST = "dashboard-liste";

const MONTH_LABEL = new Intl.DateTimeFormat("de-DE", { month: "short", year: "2-digit", timeZone: "UTC" });
const MONTH_TITLE = new Intl.DateTimeFormat("de-DE", { month: "long", year: "numeric", timeZone: "UTC" });

function CustomerGrowth() {
  const now = new Date();
  // Stabile Zufallswerte pro Kalendermonat, damit die Demo beim Aktualisieren gleich bleibt.
  const months = Array.from({ length: 24 }, (_, i) => {
    const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 24 + i, 1));
    const month = date.getUTCFullYear() * 12 + date.getUTCMonth();
    const value = ((Math.imul(month ^ (month >>> 3), 0x45d9f3b) >>> 0) % 11);
    return { date, value };
  });
  return (
    <section className="analysis-card dashboard-growth" aria-labelledby="dashboard-growth-title">
      <header className="analysis-card-head">
        <h3 id="dashboard-growth-title">Kundenzuwachs über die letzten 24 Monate</h3>
        <span>Demo-Daten</span>
      </header>
      <div className="dashboard-growth-chart">
        <span className="dashboard-growth-axis">Kundenzuwachs</span>
        <ol className="dashboard-growth-months">
          {months.map(({ date, value }, i) => (
            <li key={date.getTime()}>
              <div className="dashboard-growth-track" title={`${MONTH_TITLE.format(date)}: ${value}`} aria-label={`${MONTH_TITLE.format(date)}: ${value}`}>
                <span style={{ height: `${value * 10}%` }} />
              </div>
              {i % 3 === 0 && <span className="dashboard-growth-month" aria-hidden="true">{MONTH_LABEL.format(date)}</span>}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

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
  const scrollRef = useRef<HTMLDivElement>(null);
  const hasData = data !== null;

  useEffect(() => {
    const panel = scrollRef.current;
    if (!hasData || !panel) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (reducedMotion.matches) return;

    let frame = 0;
    let start = 0;
    const initialPosition = panel.scrollTop;
    function advance(now: number) {
      if (!panel) return;
      if (!start) start = now;
      const target = panel.scrollHeight - panel.clientHeight;
      panel.scrollTop = Math.min(target, initialPosition + (now - start) * 0.065);
      if (panel.scrollTop < target) frame = window.requestAnimationFrame(advance);
    }
    const delay = window.setTimeout(() => {
      frame = window.requestAnimationFrame(advance);
    }, 950);

    const interactions = ["wheel", "touchstart", "pointerdown", "keydown"] as const;
    function stop() {
      window.clearTimeout(delay);
      window.cancelAnimationFrame(frame);
      for (const event of interactions) panel?.removeEventListener(event, stop);
      reducedMotion.removeEventListener("change", stop);
    }
    for (const event of interactions) panel.addEventListener(event, stop, { passive: true });
    reducedMotion.addEventListener("change", stop);
    return stop;
  }, [hasData]);

  const kpis = data?.kpis;
  const change = kpis?.changePercent ?? null;
  const leftCards = data?.analyses.filter(({ id }) => LEFT_COLUMN.has(id));
  const rightCards = data?.analyses.filter(({ id }) => id !== PORTFOLIO_LIST && !LEFT_COLUMN.has(id));
  const portfolio = data?.analyses.find(({ id }) => id === PORTFOLIO_LIST);
  const card = (analysis: Analysis) => (
    <AnalysisCard key={analysis.id} analysis={analysis} focused={false}
      forecastThroughYear={analysis.id === "dashboard-verlauf" ? kpis?.year : undefined}
      onExport={onExport} onRerun={onRerun} onOpenPartner={onOpenPartner} />
  );
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

      <div ref={scrollRef} className="analysis-scroll dashboard-scroll">
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
              <div>{leftCards?.map(card)}</div>
              <div>{rightCards?.map(card)}</div>
              {portfolio && (
                <div className="is-wide">
                  <CustomerGrowth />
                  {card(portfolio)}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
