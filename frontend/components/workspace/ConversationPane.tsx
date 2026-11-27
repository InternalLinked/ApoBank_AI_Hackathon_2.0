import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import type { ChatMessage, Conversation, PartnerCandidate, PartnerSummary } from "@/lib/workspace-contracts";
import { Icon } from "./Icons";

type ConversationPaneProps = {
  conversation: Conversation | undefined;
  messages: ChatMessage[];
  partner: PartnerSummary | null;
  aiConfigured: boolean;
  isSending: boolean;
  onSend: (content: string) => void;
  onOpenChats: () => void;
  onOpenDetails: () => void;
  onSelectCandidate: (candidate: PartnerCandidate) => void;
};

export function ConversationPane({ conversation, messages, partner, aiConfigured, isSending, onSend, onOpenChats, onOpenDetails, onSelectCandidate }: ConversationPaneProps) {
  const [value, setValue] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

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
          <button className="topbar-avatar" aria-label={`Partnerakte ${partner?.name ?? "öffnen"}`}>{partner?.name.split(" ").map((part) => part[0]).join("").slice(0, 2) ?? "PC"}</button>
        </div>
      </header>

      <section className="conversation-heading">
        <div className="heading-mark"><Icon name="sparkle" size={15} /></div>
        <div className="heading-copy"><span>CHAT · {partner ? `PARTNERAKTE ${partner.partnerId}` : "PARTNERVERTRIEB"}</span><h1>{conversation?.title ?? "Neue Unterhaltung"}</h1></div>
        <button className="heading-action" type="button"><Icon name="more" size={18} /></button>
      </section>

      <div className="message-scroll">
        <div className="message-column">
          {messages.length === 0 ? (
            <div className="empty-conversation"><div className="empty-orbit"><Icon name="sparkle" size={23} /></div><h2>Womit kann ich helfen?</h2><p>Frage nach einer Partnerakte, Geschäftszahlen oder einem Gesprächsprotokoll.</p><div className="suggestion-chips"><button onClick={() => onSend("Zeig mir die aktuelle Partnerakte")}>Partnerakte ansehen <Icon name="arrow" size={14} /></button><button onClick={() => onSend("Fasse die letzte Gesprächsnotiz zusammen")}>Gesprächsnotiz zusammenfassen <Icon name="arrow" size={14} /></button></div></div>
          ) : messages.map((message) => (
            <article className={`message-row ${message.role}`} key={message.id}>
              {message.role === "assistant" && <div className="assistant-avatar"><Icon name="sparkle" size={15} /></div>}
              <div className="message-body">
                <div className="message-meta"><strong>{message.role === "assistant" ? "Partner-Copilot" : "Du"}</strong><span>{message.createdAt}</span></div>
                <div className={`message-card ${message.role === "user" ? "user-message-card" : "assistant-message-card"}`}>
                  <p>{message.content}</p>
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
        <div className="quick-prompts"><span>Vorschläge</span><button type="button" onClick={() => onSend("Welche Punkte sollte ich im Gespräch ansprechen?")}>Gespräch vorbereiten</button><button type="button" onClick={() => onSend("Zeig mir offene Vorgänge")}>Offene Vorgänge</button></div>
        <form className="composer" onSubmit={submit}>
          <textarea rows={1} value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={handleKeyDown} placeholder="Frage zur Partnerakte oder schreibe eine Notiz …" aria-label="Nachricht an den Partner-Copilot" />
          <div className="composer-footer"><span><Icon name="sparkle" size={14} /> Antworten mit Quellenbezug</span><div className="composer-actions"><button type="button" className="composer-attach" aria-label="Datei anhängen" title="Datei anhängen"><Icon name="file" size={17} /></button><button type="submit" className="send-button" disabled={!value.trim() || isSending} aria-label="Nachricht senden"><Icon name="send" size={16} /></button></div></div>
        </form>
        <p className="composer-note">Angaben aus dem Chat erst prüfen und anschließend bewusst in die Partnerakte übernehmen.</p>
      </div>
    </main>
  );
}
