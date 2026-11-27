"use client";

import { useEffect, useState } from "react";
import { demoWorkspace } from "@/lib/demo-data";
import { createMockWorkspaceApi } from "@/lib/mock-workspace-api";
import type { ChatMessage, ExtractedFinding, ManualEntryInput, WorkspaceApi, WorkspaceSnapshot } from "@/lib/workspace-contracts";
import { ChatSidebar } from "./ChatSidebar";
import { ConversationPane } from "./ConversationPane";
import { InspectorPanel } from "./InspectorPanel";
import { Icon } from "./Icons";

export function Workspace() {
  const [api] = useState<WorkspaceApi>(() => createMockWorkspaceApi());
  const [snapshot, setSnapshot] = useState<WorkspaceSnapshot>(demoWorkspace);
  const [activeConversationId, setActiveConversationId] = useState(demoWorkspace.conversations[0].id);
  const [findings, setFindings] = useState<ExtractedFinding[]>(demoWorkspace.findings);
  const [isSending, setIsSending] = useState(false);
  const [mobileDrawer, setMobileDrawer] = useState<"chats" | "details" | null>(null);
  const [toast, setToast] = useState("");

  useEffect(() => {
    let mounted = true;
    api.loadWorkspace().then((initial) => {
      if (!mounted) return;
      setSnapshot(initial);
      setFindings(initial.findings);
    });
    return () => { mounted = false; };
  }, [api]);

  const activeConversation = snapshot.conversations.find((conversation) => conversation.id === activeConversationId);
  const activeMessages = snapshot.messagesByConversation[activeConversationId] ?? [];

  function addMessage(conversationId: string, message: ChatMessage) {
    setSnapshot((current) => ({
      ...current,
      messagesByConversation: {
        ...current.messagesByConversation,
        [conversationId]: [...(current.messagesByConversation[conversationId] ?? []), message],
      },
    }));
  }

  async function sendMessage(content: string) {
    const conversationId = activeConversationId;
    const userMessage: ChatMessage = { id: `user-${Date.now()}`, role: "user", content, createdAt: "Jetzt" };
    addMessage(conversationId, userMessage);
    setSnapshot((current) => ({
      ...current,
      conversations: current.conversations.map((conversation) => conversation.id === conversationId ? { ...conversation, preview: content, updatedAt: "Jetzt", title: conversation.title === "Neue Unterhaltung" ? content.slice(0, 34) : conversation.title } : conversation),
    }));
    setIsSending(true);
    try {
      const reply = await api.sendMessage(conversationId, content);
      addMessage(conversationId, reply);
    } catch {
      addMessage(conversationId, { id: `error-${Date.now()}`, role: "assistant", content: "Die Demo-Antwort konnte nicht erstellt werden. Bitte versuche es erneut.", createdAt: "Jetzt" });
    } finally {
      setIsSending(false);
    }
  }

  function createConversation() {
    const id = `conversation-${Date.now()}`;
    setSnapshot((current) => ({
      ...current,
      conversations: [{ id, title: "Neue Unterhaltung", preview: "Noch keine Nachrichten", updatedAt: "Jetzt" }, ...current.conversations],
      messagesByConversation: { ...current.messagesByConversation, [id]: [] },
    }));
    setActiveConversationId(id);
    setMobileDrawer(null);
  }

  async function saveEntry(input: ManualEntryInput) {
    const saved = await api.createEntry(input);
    setToast(`${saved.label} wurde im Prototyp angelegt.`);
    if (input.kind === "note") {
      addMessage(activeConversationId, { id: `entry-${saved.id}`, role: "assistant", content: `Die Notiz „${saved.label}“ wurde in dieser Demo erfasst. Mit dem Backend-Anschluss wird sie in der Partnerakte gespeichert.`, createdAt: "Jetzt" });
    }
    return saved.label;
  }

  async function confirmFindings(findingIds: string[]) {
    await api.confirmFindings(activeConversationId, findingIds);
    setFindings((current) => current.map((finding) => findingIds.includes(finding.id) ? { ...finding, status: "confirmed" } : finding));
    setToast("Die erkannten Angaben wurden im Prototyp bestätigt.");
  }

  return (
    <div className="workspace-shell">
      {mobileDrawer && <button className="mobile-backdrop" aria-label="Seitenleiste schließen" onClick={() => setMobileDrawer(null)} />}
      <ChatSidebar conversations={snapshot.conversations} activeConversationId={activeConversationId} mobileOpen={mobileDrawer === "chats"} onCloseMobile={() => setMobileDrawer(null)} onSelect={setActiveConversationId} onNewConversation={createConversation} />
      <ConversationPane conversation={activeConversation} messages={activeMessages} partner={snapshot.partner} isSending={isSending} onSend={sendMessage} onOpenChats={() => setMobileDrawer("chats")} onOpenDetails={() => setMobileDrawer("details")} />
      <InspectorPanel partner={snapshot.partner} findings={findings} mobileOpen={mobileDrawer === "details"} onCloseMobile={() => setMobileDrawer(null)} onSaveEntry={saveEntry} onConfirmFindings={confirmFindings} />
      {toast && <div className="toast" role="status"><Icon name="check" size={16} />{toast}<button onClick={() => setToast("")} aria-label="Hinweis schließen"><Icon name="close" size={15} /></button></div>}
    </div>
  );
}
