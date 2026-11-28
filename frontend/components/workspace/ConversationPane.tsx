import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import type { Analysis, ChangeProposal, ChatMessage, Conversation, PartnerCandidate, PartnerSummary, ProposalStatus, StartSuggestion } from "@/lib/workspace-contracts";
import { AnalysisPanel } from "./AnalysisPanel";
import { ChangesPanel } from "./ChangesPanel";
import { Icon } from "./Icons";
import { MessageMarkdown } from "./MessageMarkdown";
import { VoiceButton } from "./VoiceButton";

type PaneTab = "chat" | "analyse" | "aenderungen";

/** Anhänge im Chat (siehe backend/anhaenge.py) */
const ATTACHMENT_ACCEPT = ".pdf,.docx,.xlsx,.txt,.md,.csv,.json,.eml,.png,.jpg,.jpeg,.webp,.gif";
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toLocaleString("de-DE", { maximumFractionDigits: 1 })} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** Stufen der automatischen Modellwahl (backend/modellwahl.py) */
const TIER_LABEL: Record<string, string> = { smalltalk: "schnell", analyse: "Analyse", aendern: "Änderung", standard: "Standard" };

const STARTER_PROMPTS: Array<{ id: StartSuggestion; label: string; hint: string; prompt: string }> = [
  { id: "top10", label: "Meine Top 10", hint: "Ranking 2025 mit Diagramm", prompt: "Zeige meine Top 10 Vermittler nach Kreditvolumen 2025." },
  { id: "einbrueche", label: "Größte Einbrüche", hint: "Vergleich 2024 → 2025", prompt: "Welche 10 Vermittler sind von 2024 auf 2025 beim Volumen am stärksten eingebrochen?" },
  { id: "gespraech", label: "Gespräch vorbereiten", hint: "Dr. Hans Baumann (4251)", prompt: "Bereite mich auf das Gespräch mit Dr. Hans Baumann (Vermittler 4251) vor." },
  { id: "marktgebiete", label: "Marktgebiete vergleichen", hint: "Volumen 2025 je Region", prompt: "Vergleiche das Volumen 2025 nach Marktgebiet." },
  { id: "portfolio", label: "Portfolio-Überblick", hint: "Status und Regionen", prompt: "Gib mir einen Überblick über das Vermittlerportfolio." },
  { id: "karte", label: "Kartenansicht", hint: "Volumen je Standort", prompt: "Zeige das Kreditvolumen 2025 nach Standort auf der Deutschlandkarte." },
];

type ConversationPaneProps = {
  conversation: Conversation | undefined;
  messages: ChatMessage[];
  partner: PartnerSummary | null;
  aiConfigured: boolean;
  isSending: boolean;
  /** false = nicht gesendet (z. B. Anhang abgelehnt) – dann bleiben Text und Datei im Eingabefeld */
  onSend: (content: string, startSuggestion?: StartSuggestion, file?: File | null) => Promise<boolean> | void;
  onOpenChats: () => void;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onOpenDetails: () => void;
  /** Rechte Leiste ist eingefahren (Desktop): Button zum Einblenden zeigen. */
  inspectorCollapsed: boolean;
  onExpandInspector: () => void;
  /** Avatar-Knopf oben rechts: Partnerakte ein-/ausblenden. */
  onToggleInspector: () => void;
  onSelectCandidate: (candidate: PartnerCandidate) => void;
  /** Klick auf einen verlinkten Vermittlernamen im Antworttext. */
  onOpenPartner: (vermittlerNr: number, name: string) => void;
  onTranscribe: (pcm: Blob, sampleRate: number) => Promise<string>;
  onError: (message: string) => void;
  /** true = erfolgreich (Status wird lokal aktualisiert); Fehler zeigt der Aufrufer selbst an */
  onConfirmProposal: (proposal: ChangeProposal) => Promise<boolean>;
  onRejectProposal: (proposal: ChangeProposal) => Promise<boolean>;
  /** Analyse-Ergebnis als Excel herunterladen */
  onExportAnalysis: (analysis: Analysis) => Promise<void>;
  /** Auswahlfeld über dem Diagramm geändert → Backend rechnet neu (wirft bei Fehler, Hinweis kommt vom Aufrufer) */
  onRerunAnalysis: (analysis: Analysis, values: Record<string, string>) => Promise<Analysis>;
};

export function ConversationPane({ conversation, messages, partner, aiConfigured, isSending, onSend, onOpenChats, sidebarCollapsed, onToggleSidebar, onOpenDetails, inspectorCollapsed, onExpandInspector, onToggleInspector, onSelectCandidate, onOpenPartner, onTranscribe, onError, onConfirmProposal, onRejectProposal, onExportAnalysis, onRerunAnalysis }: ConversationPaneProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [attachment, setAttachment] = useState<File | null>(null);

  // Diktierten Text anhängen (nicht ersetzen) und zum Prüfen ins Feld fokussieren – gesendet wird erst per Klick/Enter
  function insertTranscript(text: string) {
    setValue((current) => (current.trim() ? `${current.trimEnd()} ${text}` : text));
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  }
  const [tab, setTab] = useState<PaneTab>("chat");
  const [focusedAnalysisId, setFocusedAnalysisId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Neueste Analyse zuerst
  const analyses = useMemo(() => messages.flatMap((message) => message.analyses ?? []).reverse(), [messages]);
  // Status nach Klick sofort lokal übernehmen (beim nächsten Laden kommt er vom Server)
  const [proposalStatus, setProposalStatus] = useState<Record<string, ProposalStatus>>({});
  const [focusedProposalId, setFocusedProposalId] = useState<string | null>(null);
  const proposals = useMemo(
    () => messages.flatMap((message) => message.proposals ?? []).reverse().map((p) => ({ ...p, status: proposalStatus[p.id] ?? p.status })),
    [messages, proposalStatus],
  );
  const openProposals = proposals.filter((p) => p.status === "offen").length;
  const hasAnalyses = analyses.length > 0;
  const hasProposals = proposals.length > 0;
  // Ein leerer Tab wird nicht angezeigt – war er gewählt (z. B. nach Chatwechsel), zeigen wir den Chat
  const activeTab: PaneTab = (tab === "analyse" && !hasAnalyses) || (tab === "aenderungen" && !hasProposals) ? "chat" : tab;

  async function decide(proposal: ChangeProposal, confirm: boolean) {
    const ok = await (confirm ? onConfirmProposal(proposal) : onRejectProposal(proposal));
    if (ok) setProposalStatus((current) => ({ ...current, [proposal.id]: confirm ? "bestaetigt" : "verworfen" }));
  }

  function openProposal(id: string) {
    setFocusedProposalId(id);
    setTab("aenderungen");
  }

  useEffect(() => {
    if (activeTab === "chat") bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, activeTab]);

  // Anderer Chat gewählt → zurück zum Chat-Tab
  useEffect(() => {
    setTab("chat");
    setFocusedAnalysisId(null);
    setFocusedProposalId(null);
  }, [conversation?.id]);

  function openAnalysis(id: string) {
    setFocusedAnalysisId(id);
    setTab("analyse");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const typed = value.trim();
    const file = attachment;
    const message = typed || (file ? "Bitte sieh dir den Anhang an und fasse ihn zusammen." : "");
    if (!message || isSending) return;
    setValue("");
    setAttachment(null);
    const sent = await onSend(message, undefined, file);
    if (sent === false) {   // z. B. Anhang abgelehnt: Eingabe und Datei wiederherstellen
      setValue(typed);
      setAttachment(file);
    }
  }

  function pickFile(file: File | null) {
    if (!file) return;
    if (file.size > MAX_ATTACHMENT_BYTES) {
      onError(`„${file.name}“ ist zu groß (max. 10 MB).`);
      return;
    }
    setAttachment(file);
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <main className="conversation-pane">
      <header className="topbar">
        <button className="icon-button chats-mobile-trigger" type="button" aria-controls="chat-sidebar" aria-label="Chatverläufe öffnen" onClick={onOpenChats}><Icon name="menu" /></button>
        <button className="icon-button sidebar-toggle" type="button" aria-controls="chat-sidebar" aria-expanded={!sidebarCollapsed} aria-label={sidebarCollapsed ? "Chatleiste einblenden" : "Chatleiste einklappen"} title={sidebarCollapsed ? "Chatleiste einblenden" : "Chatleiste einklappen"} onClick={onToggleSidebar}>
          <Icon name="panel" />
        </button>
        <div className="topbar-actions">
          <span className={`prototype-pill ${aiConfigured ? "is-ready" : ""}`}><span /> {aiConfigured ? "KI verbunden" : "KI-Key fehlt"}</span>
          <button className="icon-button mobile-trigger" aria-label="Partnerakte öffnen" onClick={onOpenDetails}><Icon name="panel" /></button>
          {inspectorCollapsed && <button className="icon-button panel-expand" type="button" aria-label="Partnerakte-Leiste einblenden" title="Partnerakte-Leiste einblenden" onClick={onExpandInspector}><Icon name="panel" /></button>}
          <button className="topbar-avatar" type="button" onClick={onToggleInspector}
            aria-label={inspectorCollapsed ? `Partnerakte ${partner?.name ? `von ${partner.name} ` : ""}öffnen` : "Partnerakte einfahren"}
            title={inspectorCollapsed ? "Partnerakte öffnen" : "Partnerakte einfahren"}>{partner?.name.split(" ").map((part) => part[0]).join("").slice(0, 2) ?? "PC"}</button>
        </div>
      </header>

      <section className="conversation-heading">
        <div className="heading-mark"><Icon name="sparkle" size={15} /></div>
        <div className="heading-copy"><span>CHAT · {partner ? `PARTNERAKTE ${partner.partnerId}` : "PARTNERVERTRIEB"}</span><h1>{conversation?.title ?? "Neue Unterhaltung"}</h1></div>
      </section>

      {/* Tabs nur, wenn es neben dem Chat etwas zu zeigen gibt */}
      {(hasAnalyses || hasProposals) && (
        <div className="pane-tabs" role="tablist" aria-label="Ansicht">
          <button type="button" role="tab" id="tab-chat" aria-controls="panel-chat" aria-selected={activeTab === "chat"} className={activeTab === "chat" ? "is-active" : ""} onClick={() => setTab("chat")}>
            <Icon name="chat" size={14} /> Chat
          </button>
          {hasAnalyses && (
            <button type="button" role="tab" id="tab-analyse" aria-controls="panel-analyse" aria-selected={activeTab === "analyse"} className={activeTab === "analyse" ? "is-active" : ""} onClick={() => setTab("analyse")}>
              <Icon name="filter" size={14} /> Analyse<span className="pane-tab-count">{analyses.length}</span>
            </button>
          )}
          {hasProposals && (
            <button type="button" role="tab" id="tab-aenderungen" aria-controls="panel-aenderungen" aria-selected={activeTab === "aenderungen"} className={activeTab === "aenderungen" ? "is-active" : ""} onClick={() => setTab("aenderungen")}>
              <Icon name="note" size={14} /> Änderungen{openProposals > 0 && <span className="pane-tab-count is-alert" aria-label={`${openProposals} offen`}>{openProposals}</span>}
            </button>
          )}
        </div>
      )}

      {activeTab === "aenderungen" ? (
        <section className="pane-tab-panel" role="tabpanel" id="panel-aenderungen" aria-labelledby="tab-aenderungen">
          <ChangesPanel proposals={proposals} focusedId={focusedProposalId} onConfirm={(p) => decide(p, true)} onReject={(p) => decide(p, false)} onBackToChat={() => setTab("chat")} />
        </section>
      ) : activeTab === "analyse" ? (
        <section className="pane-tab-panel" role="tabpanel" id="panel-analyse" aria-labelledby="tab-analyse">
          <AnalysisPanel analyses={analyses} focusedId={focusedAnalysisId} onBackToChat={() => setTab("chat")} onExport={onExportAnalysis}
            onRerun={onRerunAnalysis} onOpenPartner={onOpenPartner} />
        </section>
      ) : (
      <section className="pane-tab-panel" role="tabpanel" id="panel-chat" aria-labelledby="tab-chat">
      <div className="message-scroll">
        <div className="message-column">
          {messages.length === 0 ? (
            <div className="empty-conversation"><div className="empty-orbit"><Icon name="sparkle" size={23} /></div><h2>Womit kann ich helfen?</h2><p>Frage nach einer Partnerakte, Geschäftszahlen oder einem Gesprächsprotokoll.</p><div className="suggestion-chips suggestion-grid">{STARTER_PROMPTS.map((starter) => <button key={starter.id} type="button" disabled={isSending} onClick={() => onSend(starter.prompt, starter.id)}><span><strong>{starter.label}</strong><small>{starter.hint}</small></span><Icon name="arrow" size={14} /></button>)}</div></div>
          ) : messages.map((message) => (
            <article className={`message-row ${message.role}`} key={message.id}>
              {message.role === "assistant" && <div className="assistant-avatar"><Icon name="sparkle" size={15} /></div>}
              <div className="message-body">
                <div className="message-meta">
                  <strong>{message.role === "assistant" ? "Aipo" : "Du"}</strong><span>{message.createdAt}</span>
                  {message.model && (
                    <span className="message-model" title={`Automatisch gewählt: ${TIER_LABEL[message.model.tier] ?? message.model.tier} · ${message.model.rounds} KI-Runde(n)`}>
                      {message.model.name} · {TIER_LABEL[message.model.tier] ?? message.model.tier} · {message.model.seconds.toLocaleString("de-DE", { maximumFractionDigits: 1 })} s
                    </span>
                  )}
                </div>
                <div className={`message-card ${message.role === "user" ? "user-message-card" : "assistant-message-card"}`}>
                  {message.role === "assistant" ? <MessageMarkdown content={message.content} onOpenPartner={onOpenPartner} /> : <p>{message.content}</p>}
                  {message.attachments && (
                    <ul className="message-attachments" aria-label="Anhänge">
                      {message.attachments.map((attachment) => (
                        <li key={attachment.id} title={attachment.hint ?? attachment.name}>
                          <Icon name={attachment.kind === "bild" ? "upload" : "file"} size={13} />
                          <span>{attachment.name}</span>
                          {attachment.size > 0 && <small>{formatSize(attachment.size)}</small>}
                        </li>
                      ))}
                    </ul>
                  )}
                  {message.metrics && <div className="metric-grid">{message.metrics.map((metric) => <div className={`metric-card tone-${metric.tone ?? "green"}`} key={metric.label}><span>{metric.label}</span><strong>{metric.value}</strong><small>{metric.detail}</small></div>)}</div>}
                  {message.bullets && <ul className="message-bullets">{message.bullets.map((bullet) => <li key={bullet}><span className="bullet-dot" />{bullet}</li>)}</ul>}
                  {message.candidates && (
                    <div className="candidate-list" role="group" aria-label="Passende Vermittler auswählen">
                      {message.candidates.map((candidate) => (
                        <button
                          type="button"
                          key={candidate.vermittlerNr}
                          className={`candidate-button ${partner?.vermittlerNr === candidate.vermittlerNr ? "is-selected" : ""}`}
                          aria-pressed={partner?.vermittlerNr === candidate.vermittlerNr}
                          onClick={() => onSelectCandidate(candidate)}
                        >
                          <strong>{candidate.name}</strong>
                          {(candidate.company || candidate.location) && (
                            <small>{[candidate.company, candidate.location].filter(Boolean).join(" · ")}</small>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                  {message.analyses && (
                    <div className="analysis-links">
                      {message.analyses.map((analysis) => (
                        <button type="button" key={analysis.id} className="analysis-link" onClick={() => openAnalysis(analysis.id)}>
                          <Icon name="filter" size={14} /> Diagramm ansehen: {analysis.title} <Icon name="chevron" size={13} />
                        </button>
                      ))}
                    </div>
                  )}
                  {message.proposals && (
                    <div className="analysis-links">
                      {message.proposals.map((proposal) => {
                        const status = proposalStatus[proposal.id] ?? proposal.status;
                        return (
                          <button type="button" key={proposal.id} className={`proposal-link status-${status}`} onClick={() => openProposal(proposal.id)}>
                            <Icon name={status === "bestaetigt" ? "check" : "note"} size={14} />
                            {status === "offen" ? `${proposal.changes.length} ${proposal.changes.length === 1 ? "Änderung" : "Änderungen"} prüfen und bestätigen` : status === "bestaetigt" ? "Änderungen gespeichert" : "Änderungen verworfen"}
                            <Icon name="chevron" size={13} />
                          </button>
                        );
                      })}
                    </div>
                  )}
                  {message.source && <div className="message-source"><Icon name="file" size={14} /><span>{message.source}</span><Icon name="chevron" size={13} /></div>}
                </div>
                {message.role === "assistant" && <div className="message-feedback"><button aria-label="Antwort kopieren" title="Antwort kopieren"><Icon name="file" size={14} /></button><button aria-label="Antwort hilfreich" title="Hilfreich"><Icon name="check" size={14} /></button></div>}
              </div>
            </article>
          ))}
          {isSending && <div className="typing-indicator"><span /><span /><span /> Aipo denkt nach …</div>}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="composer-wrap">
        <div className="quick-prompts"><span>Vorschläge</span><button type="button" onClick={() => onSend("Welche Punkte sollte ich im Gespräch ansprechen?")}>Gespräch vorbereiten</button><button type="button" onClick={() => onSend("Zeig mir offene Vorgänge")}>Offene Vorgänge</button><button type="button" disabled={isSending} onClick={() => onSend(STARTER_PROMPTS[0].prompt, "top10")}>Meine Top 10</button></div>
        <form className="composer" onSubmit={submit}>
          {attachment && (
            <div className="composer-attachment" role="status">
              <Icon name="file" size={14} />
              <span className="composer-attachment-name" title={attachment.name}>{attachment.name}</span>
              <small>{formatSize(attachment.size)}</small>
              <button type="button" onClick={() => setAttachment(null)} aria-label={`Anhang ${attachment.name} entfernen`} title="Anhang entfernen" disabled={isSending}><Icon name="close" size={13} /></button>
            </div>
          )}
          <textarea ref={textareaRef} rows={1} value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={handleKeyDown} placeholder={attachment ? "Was soll Aipo mit dem Anhang machen? (z. B. „Fasse das Protokoll zusammen“)" : "Frage zur Partnerakte oder schreibe eine Notiz … (oder Mikrofon nutzen)"} aria-label="Nachricht an Aipo" />
          <div className="composer-footer">
            <div className="composer-tools">
              <input ref={fileInputRef} type="file" hidden accept={ATTACHMENT_ACCEPT} onChange={(event) => { pickFile(event.target.files?.[0] ?? null); event.target.value = ""; }} />
              <button type="button" className="composer-upload" onClick={() => fileInputRef.current?.click()} disabled={isSending}
                aria-label="Datei anhängen (PDF, Word, Excel, Text, Bild)" title="Datei anhängen – PDF, Word, Excel, Text oder Bild, max. 10 MB">
                <Icon name="upload" size={16} />
              </button>
            </div>
            <div className="composer-actions"><VoiceButton disabled={isSending} onTranscribe={onTranscribe} onText={insertTranscript} onError={onError} /><button type="submit" className="send-button" disabled={(!value.trim() && !attachment) || isSending} aria-label="Nachricht senden"><Icon name="send" size={16} /></button></div>
          </div>
        </form>
        <p className="composer-note">Angaben aus dem Chat erst prüfen und anschließend bewusst in die Partnerakte übernehmen.</p>
      </div>
      </section>
      )}
    </main>
  );
}
