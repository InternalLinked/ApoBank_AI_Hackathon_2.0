import { useMemo, useState } from "react";
import type { Conversation } from "@/lib/workspace-contracts";
import { Icon } from "./Icons";

type ChatSidebarProps = {
  conversations: Conversation[];
  activeConversationId: string;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onSelect: (id: string) => void;
  onNewConversation: () => void;
};

export function ChatSidebar({
  conversations,
  activeConversationId,
  mobileOpen,
  onCloseMobile,
  onSelect,
  onNewConversation,
}: ChatSidebarProps) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () => conversations.filter((conversation) => `${conversation.title} ${conversation.preview}`.toLowerCase().includes(query.toLowerCase())),
    [conversations, query],
  );

  return (
    <aside className="chat-sidebar" data-mobile-open={mobileOpen} aria-label="Chatverläufe">
      <div className="sidebar-brand">
        <div className="brand-mark"><Icon name="sparkle" size={21} /></div>
        <div className="brand-copy"><strong>apoBank</strong><span>Partner-Copilot</span></div>
        <button className="icon-button sidebar-close" aria-label="Chats schließen" onClick={onCloseMobile}><Icon name="close" /></button>
      </div>

      <button className="workspace-switcher" type="button">
        <span className="workspace-avatar">P</span>
        <span><strong>Partnervertrieb</strong><small>Arbeitsbereich</small></span>
        <Icon name="chevron" size={15} />
      </button>

      <button className="new-chat-button" type="button" onClick={onNewConversation}>
        <Icon name="plus" size={17} />
        <span>Neuer Chat</span>
        <kbd>⌘ K</kbd>
      </button>

      <label className="chat-search">
        <Icon name="search" size={16} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Chats durchsuchen" />
        <kbd>⌘ F</kbd>
      </label>

      <div className="sidebar-section-label"><span>Letzte Chats</span><button className="icon-button tiny" aria-label="Chats filtern"><Icon name="filter" size={15} /></button></div>
      <nav className="conversation-list">
        {filtered.map((conversation) => (
          <button
            type="button"
            key={conversation.id}
            className={`conversation-item ${conversation.id === activeConversationId ? "is-active" : ""}`}
            onClick={() => { onSelect(conversation.id); onCloseMobile(); }}
          >
            <span className="conversation-icon"><Icon name="chat" size={16} /></span>
            <span className="conversation-copy"><strong>{conversation.title}</strong><small>{conversation.preview}</small></span>
            <span className="conversation-time">{conversation.updatedAt}</span>
          </button>
        ))}
        {filtered.length === 0 && <p className="empty-search">Keine Chats gefunden.</p>}
      </nav>

      <div className="sidebar-bottom">
        <div className="sidebar-tip"><span className="tip-icon"><Icon name="sparkle" size={16} /></span><div><strong>Copilot-Tipp</strong><p>Frage in natürlicher Sprache nach einer Partnerakte oder einem Vorgang.</p></div></div>
        <button className="user-profile" type="button">
          <span className="user-avatar">AM</span>
          <span><strong>Adrian M.</strong><small>Persönlicher Bereich</small></span>
          <Icon name="more" size={17} />
        </button>
      </div>
    </aside>
  );
}
