import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { errorMessage } from "@/lib/workspace-api";
import type { ObsidianGraph as Graph, ObsidianGraphNode, WorkspaceApi } from "@/lib/workspace-contracts";

type ObsidianGraphProps = {
  api: WorkspaceApi;
  vermittlerNr: number;
  /** Hochzählen, um den Graphen neu zu laden (z. B. nach neuen Profil-Infos). */
  refreshKey: number;
  onError: (message: string) => void;
};

const WIDTH = 320;
const HEIGHT = 230;

const STYLE: Record<string, { color: string; radius: number; label: string }> = {
  vermittler: { color: "#17427f", radius: 9, label: "Vermittler" },
  profil: { color: "#c08a2b", radius: 6, label: "Profil" },
  kategorie: { color: "#e0795a", radius: 4.5, label: "Kategorie" },
  fakt: { color: "#e2be72", radius: 3.5, label: "Persönliche Info" },
  eintrag: { color: "#5b8fd6", radius: 4.5, label: "Eintrag" },
  betreuer: { color: "#4f9a7b", radius: 5, label: "Betreuer" },
  filiale: { color: "#7a8aa3", radius: 5, label: "Filiale" },
  "vermittler-link": { color: "#8f6ad1", radius: 5, label: "Anderer Vermittler" },
  notiz: { color: "#a3adbd", radius: 4, label: "Notiz" },
};

type Point = { x: number; y: number };

/** Kleine Kräftesimulation (ohne Bibliothek), deterministisch und synchron – für < 60 Knoten völlig ausreichend. */
function layout(graph: Graph): Record<string, Point> {
  const ids = graph.nodes.map((node) => node.id);
  const pos: Record<string, Point> = {};
  const cx = WIDTH / 2;
  const cy = HEIGHT / 2;
  ids.forEach((id, index) => {
    const angle = (index / Math.max(ids.length, 1)) * Math.PI * 2;
    const ring = id === graph.center ? 0 : graph.nodes[index]?.type === "fakt" ? 110 : graph.nodes[index]?.type === "kategorie" ? 85 : 65;
    pos[id] = { x: cx + Math.cos(angle) * ring, y: cy + Math.sin(angle) * ring };
  });
  const links = graph.edges.filter((edge) => pos[edge.from] && pos[edge.to]);
  for (let step = 0; step < 300; step++) {
    const cooling = 1 - step / 300;
    const force: Record<string, Point> = Object.fromEntries(ids.map((id) => [id, { x: 0, y: 0 }]));
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = pos[ids[i]];
        const b = pos[ids[j]];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const dist2 = Math.max(dx * dx + dy * dy, 25);
        const push = 900 / dist2;
        const dist = Math.sqrt(dist2);
        force[ids[i]].x += (dx / dist) * push; force[ids[i]].y += (dy / dist) * push;
        force[ids[j]].x -= (dx / dist) * push; force[ids[j]].y -= (dy / dist) * push;
      }
    }
    for (const edge of links) {
      const a = pos[edge.from];
      const b = pos[edge.to];
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const pull = (dist - 45) * 0.04;
      force[edge.from].x += (dx / dist) * pull; force[edge.from].y += (dy / dist) * pull;
      force[edge.to].x -= (dx / dist) * pull; force[edge.to].y -= (dy / dist) * pull;
    }
    for (const id of ids) {
      if (id === graph.center) continue;
      const p = pos[id];
      p.x += Math.max(-6, Math.min(6, force[id].x + (cx - p.x) * 0.01)) * cooling;
      p.y += Math.max(-6, Math.min(6, force[id].y + (cy - p.y) * 0.01)) * cooling;
      p.x = Math.max(14, Math.min(WIDTH - 14, p.x));
      p.y = Math.max(12, Math.min(HEIGHT - 12, p.y));
    }
  }
  return pos;
}

function shortLabel(text: string, max = 18): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

// Hover-Vergroesserung: Die Karte loest sich aus dem (seitlich abschneidenden) Panel, bleibt rechts oben
// verankert und waechst nach links/unten – das Seitenverhaeltnis des Netzes bleibt gleich.
const ZOOM = 1.9;
const RAND = 16;              // Mindestabstand zum Fensterrand
const HOVER_DELAY_MS = 180;   // nicht schon beim blossen Drueberwischen aufspringen
const ANIMATION_MS = 220;

type Floating = { top: number; right: number; width: number; baseWidth: number; baseHeight: number; targetTop: number; targetWidth: number };

/** Lokale Graph-Ansicht wie in Obsidian: der aktuelle Vermittler und alles, was mit ihm verbunden ist. */
export function ObsidianGraph({ api, vermittlerNr, refreshKey, onError }: ObsidianGraphProps) {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [hovered, setHovered] = useState<ObsidianGraphNode | null>(null);
  const cardRef = useRef<HTMLElement>(null);
  const [floating, setFloating] = useState<Floating | null>(null);
  const [grown, setGrown] = useState(false);
  const openTimer = useRef<number | null>(null);
  const closeTimer = useRef<number | null>(null);

  function clearTimers() {
    if (openTimer.current) window.clearTimeout(openTimer.current);
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    openTimer.current = closeTimer.current = null;
  }

  function startGrow() {
    clearTimers();
    if (floating) { setGrown(true); return; }   // war gerade am Schrumpfen -> wieder gross
    if (!graph || !window.matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    openTimer.current = window.setTimeout(() => {
      const el = cardRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const targetWidth = Math.min(r.width * ZOOM, r.right - RAND);   // nach links bis knapp an den Fensterrand
      if (targetWidth < r.width * 1.15) return;                       // zu wenig Platz: lohnt nicht
      const targetHeight = r.height * (targetWidth / r.width);        // obere Schaetzung (Texte wachsen nicht mit)
      const targetTop = Math.max(RAND, Math.min(r.top, window.innerHeight - targetHeight - RAND));
      setFloating({ top: r.top, right: window.innerWidth - r.right, width: r.width, baseWidth: r.width, baseHeight: r.height, targetTop, targetWidth });
      // erst in Ausgangsgroesse fixieren, dann im naechsten Frame wachsen lassen -> fluessige Animation
      requestAnimationFrame(() => requestAnimationFrame(() => setGrown(true)));
    }, HOVER_DELAY_MS);
  }

  function shrink() {
    clearTimers();
    if (!floating) return;
    setGrown(false);
    closeTimer.current = window.setTimeout(() => setFloating(null), ANIMATION_MS);
  }

  // Vergroesserte Karte bei Scrollen, Fenstergroesse oder Esc sofort zuruecksetzen (sonst stimmt die Position nicht)
  useEffect(() => {
    if (!floating) return;
    const reset = () => { clearTimers(); setGrown(false); setFloating(null); };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") reset(); };
    window.addEventListener("scroll", reset, true);
    window.addEventListener("resize", reset);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", reset, true);
      window.removeEventListener("resize", reset);
      window.removeEventListener("keydown", onKey);
    };
  }, [floating]);

  useEffect(() => () => clearTimers(), []);
  // Anderer Vermittler: nie mit alter Position stehen bleiben
  useEffect(() => { setGrown(false); setFloating(null); }, [vermittlerNr]);

  useEffect(() => {
    let active = true;
    api.getObsidianGraph(vermittlerNr)
      .then((loaded) => { if (active) setGraph(loaded); })
      .catch((error) => { if (active) onError(errorMessage(error, "Das Obsidian-Netz konnte nicht geladen werden.")); });
    return () => { active = false; };
  }, [api, vermittlerNr, refreshKey]);

  const positions = useMemo(() => (graph ? layout(graph) : {}), [graph]);
  const types = useMemo(() => [...new Set(graph?.nodes.map((node) => node.type) ?? [])], [graph]);
  const neighbours = useMemo(() => {
    if (!graph || !hovered) return new Set<string>();
    return new Set(graph.edges.flatMap((edge) => edge.from === hovered.id ? [edge.to] : edge.to === hovered.id ? [edge.from] : []));
  }, [graph, hovered]);

  function open(node: ObsidianGraphNode) {
    if (node.uri) window.location.href = node.uri;
  }

  const floatingStyle: CSSProperties | undefined = floating ? {
    position: "fixed",
    top: grown ? floating.targetTop : floating.top,
    right: floating.right,
    width: grown ? floating.targetWidth : floating.width,
    margin: 0,
    zIndex: 60,
  } : undefined;

  return (
    <>
    {/* Platzhalter haelt die Hoehe im Panel, solange die Karte schwebt – nichts darunter springt */}
    {floating && <div className="obsidian-graph-placeholder" style={{ height: floating.baseHeight }} aria-hidden="true" />}
    <section ref={cardRef} className={`obsidian-graph ${floating ? "is-floating" : ""} ${grown ? "is-grown" : ""}`} style={floatingStyle}
      aria-label="Obsidian-Netz" onMouseEnter={startGrow} onMouseLeave={shrink}>
      <div className="partner-profile-heading"><h3>Obsidian-Netz</h3><span>{graph ? `${graph.nodes.length} Knoten` : "lädt …"}</span></div>
      <div className="obsidian-graph-canvas">
        {graph && <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Verbindungen des Vermittlers in Obsidian">
          {graph.edges.map((edge) => {
            const a = positions[edge.from];
            const b = positions[edge.to];
            if (!a || !b) return null;
            const active = hovered && (edge.from === hovered.id || edge.to === hovered.id);
            return <line key={`${edge.from}-${edge.to}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className={active ? "is-active" : hovered ? "is-dimmed" : ""} />;
          })}
          {graph.nodes.map((node) => {
            const p = positions[node.id];
            if (!p) return null;
            const style = STYLE[node.type] ?? STYLE.notiz;
            const dimmed = hovered && hovered.id !== node.id && !neighbours.has(node.id);
            const showLabel = node.type !== "fakt" || hovered?.id === node.id;
            return (
              <g key={node.id} transform={`translate(${p.x} ${p.y})`} className={`graph-node ${node.uri ? "is-link" : ""} ${dimmed ? "is-dimmed" : ""}`}
                onMouseEnter={() => setHovered(node)} onMouseLeave={() => setHovered(null)} onClick={() => open(node)}>
                <title>{[node.label, node.detail].filter(Boolean).join(" – ")}{node.uri ? " (in Obsidian öffnen)" : ""}</title>
                <circle r={style.radius} fill={style.color} />
                {showLabel && <text y={style.radius + 8} textAnchor="middle">{shortLabel(node.label, node.type === "vermittler" ? 26 : 18)}</text>}
              </g>
            );
          })}
        </svg>}
      </div>
      <p className="obsidian-graph-hint">{hovered ? [hovered.label, hovered.detail].filter(Boolean).join(" · ") : "Knoten antippen, um die Notiz in Obsidian zu öffnen."}</p>
      <div className="obsidian-graph-legend">
        {types.map((type) => <span key={type}><i style={{ background: (STYLE[type] ?? STYLE.notiz).color }} />{(STYLE[type] ?? STYLE.notiz).label}</span>)}
      </div>
    </section>
    </>
  );
}
