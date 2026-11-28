import { useMemo, useState } from "react";
import type { Conversation } from "@/lib/workspace-contracts";
import { Icon } from "./Icons";

type ChatSidebarProps = {
  accountName: string | null;
  conversations: Conversation[];
  activeConversationId: string;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onSelect: (id: string) => void;
  onNewConversation: () => void;
  onDelete: (id: string) => void;
};

export function ChatSidebar({
  accountName,
  conversations,
  activeConversationId,
  mobileOpen,
  onCloseMobile,
  onSelect,
  onNewConversation,
  onDelete,
}: ChatSidebarProps) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () => conversations.filter((conversation) => `${conversation.title} ${conversation.preview}`.toLowerCase().includes(query.toLowerCase())),
    [conversations, query],
  );

  return (
    <aside id="chat-sidebar" className="chat-sidebar" data-mobile-open={mobileOpen} aria-label="Chatverläufe">
      <div className="sidebar-brand">
        <img className="brand-mark" src="/apobank-logo.svg" alt="apoBank" width={72} height={72} />
        <div className="brand-copy"><strong>apoBank</strong><span>Bank der Gesundheit</span><small>Aipo</small></div>
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
          <div className="conversation-row" key={conversation.id}>
            <button
              type="button"
              className={`conversation-item ${conversation.id === activeConversationId ? "is-active" : ""}`}
              onClick={() => { onSelect(conversation.id); onCloseMobile(); }}
            >
              <span className="conversation-icon"><Icon name="chat" size={16} /></span>
              <span className="conversation-copy"><strong title={conversation.title}>{conversation.title}</strong></span>
              <span className="conversation-time">{conversation.updatedAt}</span>
            </button>
            <button
              type="button"
              className="icon-button tiny conversation-delete"
              aria-label={`Chat „${conversation.title}“ löschen`}
              title="Chat löschen"
              onClick={() => {
                if (window.confirm(`Chat „${conversation.title}“ endgültig löschen?`)) onDelete(conversation.id);
              }}
            >
              <Icon name="trash" size={15} />
            </button>
          </div>
        ))}
        {filtered.length === 0 && <p className="empty-search">Keine Chats gefunden.</p>}
      </nav>

      <div className="sidebar-bottom">
        <button className="user-profile" type="button">
          <span className="user-avatar">{accountName?.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase() ?? "–"}</span>
          <span><strong>{accountName ?? "Kein Betreuerkonto"}</strong><small>Persönlicher Bereich</small></span>
          <Icon name="more" size={17} />
        </button>
      </div>
    </aside>
  );
}
