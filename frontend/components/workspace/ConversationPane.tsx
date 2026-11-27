import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage, Conversation, PartnerCandidate, PartnerSummary } from "@/lib/workspace-contracts";
import { AnalysisPanel } from "./AnalysisPanel";
import { Icon } from "./Icons";
import { MessageMarkdown } from "./MessageMarkdown";
import { VoiceButton } from "./VoiceButton";

type PaneTab = "chat" | "analyse";

const STARTER_PROMPTS: Array<{ label: string; hint: string; prompt: string }> = [
  { label: "Top 10 nach Volumen", hint: "Ranking 2025 mit Diagramm", prompt: "Zeige die Top 10 Vermittler nach Volumen 2025." },
  { label: "Größte Einbrüche", hint: "Vergleich 2024 → 2025", prompt: "Welche 10 Vermittler sind von 2024 auf 2025 beim Volumen am stärksten eingebrochen?" },
  { label: "Gespräch vorbereiten", hint: "Dr. Hans Baumann (4251)", prompt: "Bereite mich auf das Gespräch mit Dr. Hans Baumann (Vermittler 4251) vor." },
  { label: "Marktgebiete vergleichen", hint: "Volumen 2025 je Region", prompt: "Vergleiche das Volumen 2025 nach Marktgebiet." },
  { label: "Portfolio-Überblick", hint: "Status und Regionen", prompt: "Gib mir einen Überblick über das Vermittlerportfolio." },
  { label: "Notizen durchsuchen", hint: "z. B. Praxisfinanzierung", prompt: "Suche in den Gesprächsnotizen nach Praxisfinanzierung." },
];

type ConversationPaneProps = {
  conversation: Conversation | undefined;
  messages: ChatMessage[];
  partner: PartnerSummary | null;
  aiConfigured: boolean;
  isSending: boolean;
  onSend: (content: string) => void;
  onOpenChats: () => void;
  onOpenDetails: () => void;
  /** Rechte Leiste ist eingefahren (Desktop): Button zum Einblenden zeigen. */
  inspectorCollapsed: boolean;
  onExpandInspector: () => void;
  onSelectCandidate: (candidate: PartnerCandidate) => void;
  /** Klick auf einen verlinkten Vermittlernamen im Antworttext. */
  onOpenPartner: (vermittlerNr: number, name: string) => void;
  onTranscribe: (pcm: Blob, sampleRate: number) => Promise<string>;
  onError: (message: string) => void;
};

export function ConversationPane({ conversation, messages, partner, aiConfigured, isSending, onSend, onOpenChats, onOpenDetails, inspectorCollapsed, onExpandInspector, onSelectCandidate, onOpenPartner, onTranscribe, onError }: ConversationPaneProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  useEffect(() => {
    if (tab === "chat") bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, tab]);

  // Anderer Chat gewählt → zurück zum Chat-Tab
  useEffect(() => {
    setTab("chat");
    setFocusedAnalysisId(null);
  }, [conversation?.id]);

  function openAnalysis(id: string) {
    setFocusedAnalysisId(id);
    setTab("analyse");
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = value.trim();
    if (!message || isSending) return;
    onSend(message);
    setValue("");
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
        <button className="icon-button mobile-trigger" aria-label="Chatverläufe öffnen" onClick={onOpenChats}><Icon name="menu" /></button>
        <div className="breadcrumb"><span>Partnervertrieb</span><Icon name="chevron" size={14} /><strong>Unterhaltungen</strong></div>
        <div className="topbar-actions">
          <span className={`prototype-pill ${aiConfigured ? "is-ready" : ""}`}><span /> {aiConfigured ? "KI verbunden" : "KI-Key fehlt"}</span>
          <button className="icon-button mobile-trigger" aria-label="Partnerakte öffnen" onClick={onOpenDetails}><Icon name="panel" /></button>
          {inspectorCollapsed && <button className="icon-button panel-expand" type="button" aria-label="Partnerakte-Leiste einblenden" title="Partnerakte-Leiste einblenden" onClick={onExpandInspector}><Icon name="panel" /></button>}
          <button className="topbar-avatar" aria-label={`Partnerakte ${partner?.name ?? "öffnen"}`}>{partner?.name.split(" ").map((part) => part[0]).join("").slice(0, 2) ?? "PC"}</button>
        </div>
      </header>

      <section className="conversation-heading">
        <div className="heading-mark"><Icon name="sparkle" size={15} /></div>
        <div className="heading-copy"><span>CHAT · {partner ? `PARTNERAKTE ${partner.partnerId}` : "PARTNERVERTRIEB"}</span><h1>{conversation?.title ?? "Neue Unterhaltung"}</h1></div>
        <button className="heading-action" type="button"><Icon name="more" size={18} /></button>
      </section>

      <div className="pane-tabs" role="tablist" aria-label="Ansicht">
        <button type="button" role="tab" id="tab-chat" aria-controls="panel-chat" aria-selected={tab === "chat"} className={tab === "chat" ? "is-active" : ""} onClick={() => setTab("chat")}>
          <Icon name="chat" size={14} /> Chat
        </button>
        <button type="button" role="tab" id="tab-analyse" aria-controls="panel-analyse" aria-selected={tab === "analyse"} className={tab === "analyse" ? "is-active" : ""} onClick={() => setTab("analyse")}>
          <Icon name="filter" size={14} /> Analyse{analyses.length > 0 && <span className="pane-tab-count">{analyses.length}</span>}
        </button>
      </div>

      {tab === "analyse" ? (
        <section className="pane-tab-panel" role="tabpanel" id="panel-analyse" aria-labelledby="tab-analyse">
          <AnalysisPanel analyses={analyses} focusedId={focusedAnalysisId} onBackToChat={() => setTab("chat")} />
        </section>
      ) : (
      <section className="pane-tab-panel" role="tabpanel" id="panel-chat" aria-labelledby="tab-chat">
      <div className="message-scroll">
        <div className="message-column">
          {messages.length === 0 ? (
            <div className="empty-conversation"><div className="empty-orbit"><Icon name="sparkle" size={23} /></div><h2>Womit kann ich helfen?</h2><p>Frage nach einer Partnerakte, Geschäftszahlen oder einem Gesprächsprotokoll.</p><div className="suggestion-chips suggestion-grid">{STARTER_PROMPTS.map((starter) => <button key={starter.label} type="button" onClick={() => onSend(starter.prompt)}><span><strong>{starter.label}</strong><small>{starter.hint}</small></span><Icon name="arrow" size={14} /></button>)}</div></div>
          ) : messages.map((message) => (
            <article className={`message-row ${message.role}`} key={message.id}>
              {message.role === "assistant" && <div className="assistant-avatar"><Icon name="sparkle" size={15} /></div>}
              <div className="message-body">
                <div className="message-meta"><strong>{message.role === "assistant" ? "Partner-Copilot" : "Du"}</strong><span>{message.createdAt}</span></div>
                <div className={`message-card ${message.role === "user" ? "user-message-card" : "assistant-message-card"}`}>
                  {message.role === "assistant" ? <MessageMarkdown content={message.content} onOpenPartner={onOpenPartner} /> : <p>{message.content}</p>}
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
                  {message.source && <div className="message-source"><Icon name="file" size={14} /><span>{message.source}</span><Icon name="chevron" size={13} /></div>}
                </div>
                {message.role === "assistant" && <div className="message-feedback"><button aria-label="Antwort kopieren" title="Antwort kopieren"><Icon name="file" size={14} /></button><button aria-label="Antwort hilfreich" title="Hilfreich"><Icon name="check" size={14} /></button></div>}
              </div>
            </article>
          ))}
          {isSending && <div className="typing-indicator"><span /><span /><span /> Copilot denkt nach …</div>}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="composer-wrap">
        <div className="quick-prompts"><span>Vorschläge</span><button type="button" onClick={() => onSend("Welche Punkte sollte ich im Gespräch ansprechen?")}>Gespräch vorbereiten</button><button type="button" onClick={() => onSend("Zeig mir offene Vorgänge")}>Offene Vorgänge</button><button type="button" onClick={() => onSend("Wer sind die Top 10 Vermittler nach Kreditvolumen?")}>Top-Vermittler</button></div>
        <form className="composer" onSubmit={submit}>
          <textarea ref={textareaRef} rows={1} value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={handleKeyDown} placeholder="Frage zur Partnerakte oder schreibe eine Notiz … (oder Mikrofon nutzen)" aria-label="Nachricht an den Partner-Copilot" />
          <div className="composer-footer"><span><Icon name="sparkle" size={14} /> Antworten mit Quellenbezug</span><div className="composer-actions"><button type="button" className="composer-attach" aria-label="Datei anhängen" title="Datei anhängen"><Icon name="file" size={17} /></button><VoiceButton disabled={isSending} onTranscribe={onTranscribe} onText={insertTranscript} onError={onError} /><button type="submit" className="send-button" disabled={!value.trim() || isSending} aria-label="Nachricht senden"><Icon name="send" size={16} /></button></div></div>
        </form>
        <p className="composer-note">Angaben aus dem Chat erst prüfen und anschließend bewusst in die Partnerakte übernehmen.</p>
      </div>
      </section>
      )}
    </main>
  );
}
