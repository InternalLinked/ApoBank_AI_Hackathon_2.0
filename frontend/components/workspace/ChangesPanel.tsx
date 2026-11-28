import { useEffect, useRef, useState } from "react";
import type { ChangeProposal, ProposalStatus, ProposedChange } from "@/lib/workspace-contracts";
import { Icon } from "./Icons";

type ChangesPanelProps = {
  proposals: ChangeProposal[];
  focusedId: string | null;
  onConfirm: (proposal: ChangeProposal) => Promise<void>;
  onReject: (proposal: ChangeProposal) => Promise<void>;
  onBackToChat: () => void;
};

const STATUS_LABEL: Record<ProposalStatus, string> = {
  offen: "Wartet auf Bestätigung",
  bestaetigt: "Gespeichert",
  verworfen: "Verworfen",
};

function display(change: ProposedChange, value: string | number | null): string {
  if (value === null || value === "") return "–";
  if (typeof value === "number" && change.label.startsWith("Kreditvolumen")) {
    return value.toLocaleString("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
  }
  return typeof value === "number" ? value.toLocaleString("de-DE") : value;
}

function changeVerb(change: ProposedChange): string {
  if (change.kind === "profil_fakt_loeschen" || change.newValue === null || change.newValue === "") return "entfernen";
  if (change.oldValue === null || change.oldValue === "") return "neu";
  return "ändern";
}

function ProposalCard({ proposal, focused, onConfirm, onReject }: {
  proposal: ChangeProposal; focused: boolean;
  onConfirm: (p: ChangeProposal) => Promise<void>; onReject: (p: ChangeProposal) => Promise<void>;
}) {
  const [busy, setBusy] = useState<"confirm" | "reject" | null>(null);
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [focused]);

  async function run(kind: "confirm" | "reject") {
    setBusy(kind);
    try {
      await (kind === "confirm" ? onConfirm(proposal) : onReject(proposal));
    } finally {
      setBusy(null);
    }
  }

  const open = proposal.status === "offen";
  return (
    <article ref={ref} className={`change-card status-${proposal.status} ${focused ? "is-focused" : ""}`} aria-label={`Änderungsvorschlag für ${proposal.vermittler}`}>
      <header className="change-card-head">
        <div>
          <h3>{proposal.vermittler} <span>VM-{proposal.vermittlerNr}</span></h3>
          <p>{proposal.changes.length} {proposal.changes.length === 1 ? "Änderung" : "Änderungen"} · vorgeschlagen {proposal.createdAt}{proposal.reason && <> · {proposal.reason}</>}</p>
        </div>
        <span className={`change-status status-${proposal.status}`}>
          {proposal.status === "bestaetigt" && <Icon name="check" size={13} />}
          {STATUS_LABEL[proposal.status]}
        </span>
      </header>

      <table className="change-table">
        <thead>
          <tr><th scope="col">Feld</th><th scope="col">Bisher</th><th scope="col" aria-hidden="true" /><th scope="col">Neu</th></tr>
        </thead>
        <tbody>
          {proposal.changes.map((change, index) => (
            <tr key={`${change.label}-${index}`}>
              <th scope="row">
                <span className="change-area">{change.area}</span>
                {change.label}
                <span className={`change-verb verb-${changeVerb(change)}`}>{changeVerb(change)}</span>
              </th>
              <td className="change-old">{display(change, change.oldValue)}</td>
              <td className="change-arrow" aria-label="wird zu">→</td>
              <td className="change-new">{changeVerb(change) === "entfernen" ? <em>entfernt</em> : display(change, change.newValue)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {open ? (
        <div className="change-actions">
          <button type="button" className="change-confirm" disabled={busy !== null} onClick={() => void run("confirm")}>
            {busy === "confirm" ? <span className="voice-spinner" aria-hidden="true" /> : <Icon name="check" size={15} />}
            {busy === "confirm" ? "Wird gespeichert …" : `${proposal.changes.length === 1 ? "Änderung" : "Alle Änderungen"} bestätigen und speichern`}
          </button>
          <button type="button" className="change-reject" disabled={busy !== null} onClick={() => void run("reject")}>Verwerfen</button>
          <span className="change-hint">Erst nach dem Bestätigen wird etwas gespeichert – die neuen Infos stehen dann direkt in der Akte und im Obsidian-Netz.</span>
        </div>
      ) : (
        <p className="change-done">{proposal.status === "bestaetigt" ? "Gespeichert – steht jetzt in der Akte und im Obsidian-Netz." : "Nicht übernommen."}</p>
      )}
    </article>
  );
}

export function ChangesPanel({ proposals, focusedId, onConfirm, onReject, onBackToChat }: ChangesPanelProps) {
  if (proposals.length === 0) {
    return (
      <div className="analysis-empty">
        <div className="empty-orbit"><Icon name="note" size={22} /></div>
        <h2>Keine Änderungsvorschläge</h2>
        <p>Bitte im Chat z. B. „Ändere die E-Mail von Jens Weber auf j.weber@neu.de“ – der Vorschlag erscheint dann hier zur Bestätigung.</p>
        <button type="button" className="analysis-secondary-button" onClick={onBackToChat}>Zum Chat</button>
      </div>
    );
  }
  const open = proposals.filter((p) => p.status === "offen");
  const done = proposals.filter((p) => p.status !== "offen");
  return (
    <div className="analysis-scroll">
      <div className="analysis-column">
        {open.length > 0 && <h2 className="change-section">Zu prüfen ({open.length})</h2>}
        {open.map((p) => <ProposalCard key={p.id} proposal={p} focused={p.id === focusedId} onConfirm={onConfirm} onReject={onReject} />)}
        {done.length > 0 && <h2 className="change-section">Erledigt</h2>}
        {done.map((p) => <ProposalCard key={p.id} proposal={p} focused={p.id === focusedId} onConfirm={onConfirm} onReject={onReject} />)}
      </div>
    </div>
  );
}
