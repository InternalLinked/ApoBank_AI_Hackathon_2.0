"use client";

import { useEffect, useRef, useState } from "react";
import { createWorkspaceApi } from "@/lib/workspace-api";
import type { ChatMessage, ExtractedFinding, ManualEntryInput, PartnerDetail, PartnerSummary, WorkspaceApi, WorkspaceSnapshot } from "@/lib/workspace-contracts";
import { ChatSidebar } from "./ChatSidebar";
import { ConversationPane } from "./ConversationPane";
import { InspectorPanel } from "./InspectorPanel";
import { Icon } from "./Icons";

const emptyWorkspace: WorkspaceSnapshot = {
  conversations: [],
  messagesByConversation: {},
  partner: null,
  findings: [],
  aiConfigured: false,
};

export function Workspace() {
  const [api] = useState<WorkspaceApi>(() => createWorkspaceApi());
  const [snapshot, setSnapshot] = useState<WorkspaceSnapshot>(emptyWorkspace);
  const [activeConversationId, setActiveConversationId] = useState("");
  const [findings, setFindings] = useState<ExtractedFinding[]>([]);
  const [isSending, setIsSending] = useState(false);
  const [mobileDrawer, setMobileDrawer] = useState<"chats" | "details" | null>(null);
  const [toast, setToast] = useState("");
  const [partnerDetail, setPartnerDetail] = useState<PartnerDetail | null>(null);
  const [profileRefreshKey, setProfileRefreshKey] = useState(0);
  const partnerRequest = useRef(0);

  async function loadPartnerDetail(partner: PartnerSummary | null) {
    const requestId = ++partnerRequest.current;
    if (!partner) {
      setPartnerDetail(null);
      return;
    }
    try {
      const detail = await api.getPartnerDetail(partner.vermittlerNr);
      if (requestId !== partnerRequest.current) return;
      setPartnerDetail(detail);
      setSnapshot((current) => current.partner?.vermittlerNr === partner.vermittlerNr ? { ...current, partner: detail } : current);
    } catch (error) {
      if (requestId !== partnerRequest.current) return;
      setPartnerDetail(null);
      setToast(error instanceof Error ? error.message : "Partnerakte konnte nicht geladen werden.");
    }
  }

  function setCurrentPartner(partner: PartnerSummary | null) {
    setSnapshot((current) => ({ ...current, partner }));
    void loadPartnerDetail(partner);
  }

  function showError(error: unknown, fallback: string) {
    setToast(error instanceof Error ? error.message : fallback);
  }

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const initial = await api.loadWorkspace();
        if (!mounted) return;
        setSnapshot(initial);
        setFindings(initial.findings);
        setActiveConversationId(initial.conversations[0]?.id ?? "");
        void loadPartnerDetail(initial.partner);
      } catch (error) {
        if (mounted) showError(error, "Die Verbindung zum Backend konnte nicht aufgebaut werden.");
      }
    }
    void load();
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
    let conversationId = activeConversationId;
    if (!conversationId) {
      const conversation = await api.createConversation();
      conversationId = conversation.id;
      setActiveConversationId(conversationId);
      setSnapshot((current) => ({ ...current, conversations: [conversation, ...current.conversations], messagesByConversation: { ...current.messagesByConversation, [conversationId]: [] } }));
    }
    const userMessage: ChatMessage = { id: `user-${Date.now()}`, role: "user", content, createdAt: "Jetzt" };
    addMessage(conversationId, userMessage);
    setSnapshot((current) => ({
      ...current,
      conversations: current.conversations.map((conversation) => conversation.id === conversationId ? { ...conversation, preview: content, updatedAt: "Jetzt", title: conversation.title === "Neue Unterhaltung" ? content.slice(0, 34) : conversation.title } : conversation),
    }));
    setIsSending(true);
    try {
      const reply = await api.sendMessage(conversationId, content);
      addMessage(conversationId, reply.message);
      setSnapshot((current) => ({ ...current, partner: reply.partner ?? current.partner, aiConfigured: reply.aiConfigured }));
      if (reply.partner) void loadPartnerDetail(reply.partner);
      if (reply.findings.length > 0) {
        setFindings(reply.findings);
        // Der Copilot speichert direkt in Obsidian: Profil und Netz neu laden
        if (reply.findings.some((finding) => finding.status === "confirmed")) setProfileRefreshKey((key) => key + 1);
      }
      if (reply.error) showError(null, reply.error);
    } catch (error) {
      showError(error, "Die Anfrage konnte nicht beantwortet werden.");
    } finally {
      setIsSending(false);
    }
  }

  async function createConversation() {
    if (activeConversationId && activeMessages.length === 0) {
      setMobileDrawer(null);
      return;
    }
    try {
      const conversation = await api.createConversation();
      setSnapshot((current) => ({
        ...current,
        conversations: [conversation, ...current.conversations],
        messagesByConversation: { ...current.messagesByConversation, [conversation.id]: [] },
        partner: null,
      }));
      void loadPartnerDetail(null);
      setFindings([]);
      setActiveConversationId(conversation.id);
      setMobileDrawer(null);
    } catch (error) {
      showError(error, "Neuer Chat konnte nicht angelegt werden.");
    }
  }

  async function deleteConversation(conversationId: string) {
    try {
      await api.deleteConversation(conversationId);
    } catch (error) {
      showError(error, "Der Chat konnte nicht gelöscht werden.");
      return;
    }
    const remaining = snapshot.conversations.filter((conversation) => conversation.id !== conversationId);
    const wasActive = conversationId === activeConversationId;
    setSnapshot((current) => ({
      ...current,
      conversations: current.conversations.filter((conversation) => conversation.id !== conversationId),
      messagesByConversation: Object.fromEntries(Object.entries(current.messagesByConversation).filter(([id]) => id !== conversationId)),
      partner: wasActive ? null : current.partner,
    }));
    setToast("Der Chat wurde gelöscht.");
    if (!wasActive) return;
    if (remaining[0]) selectConversation(remaining[0].id);
    else await createConversation();
  }

  async function saveEntry(input: ManualEntryInput) {
    const saved = await api.createEntry(input);
    setToast(`${saved.label} wurde gespeichert.`);
    const savedPartner = saved.partner;
    if (savedPartner) setCurrentPartner(savedPartner);
    return saved.label;
  }

  async function confirmFindings(findingIds: string[]) {
    if (!snapshot.partner) {
      showError(null, "Bitte zuerst eine Partnerakte im Chat öffnen.");
      return;
    }
    const selected = findings.filter((finding) => findingIds.includes(finding.id));
    try {
      await api.confirmFindings(activeConversationId, snapshot.partner, selected);
    } catch (error) {
      showError(error, "Die Angaben konnten nicht gespeichert werden.");
      return;
    }
    setFindings((current) => current.map((finding) => findingIds.includes(finding.id) ? { ...finding, status: "confirmed" } : finding));
    const personal = selected.some((finding) => finding.group === "persoenlich");
    if (personal) setProfileRefreshKey((key) => key + 1);
    setToast(personal ? "Die bestätigten Angaben wurden in der Partnerakte und im persönlichen Profil gespeichert." : "Die bestätigten Angaben wurden als Notiz in der Partnerakte gespeichert.");
  }

  function selectConversation(conversationId: string) {
    setActiveConversationId(conversationId);
    const latest = [...(snapshot.messagesByConversation[conversationId] ?? [])].reverse().find((message) => message.role === "assistant");
    setFindings(latest?.findings ?? []);
    const selectedPartner = latest?.partner;
    setCurrentPartner(selectedPartner ?? null);
  }

  return (
    <div className="workspace-shell">
      {mobileDrawer && <button className="mobile-backdrop" aria-label="Seitenleiste schließen" onClick={() => setMobileDrawer(null)} />}
      <ChatSidebar conversations={snapshot.conversations} activeConversationId={activeConversationId} mobileOpen={mobileDrawer === "chats"} onCloseMobile={() => setMobileDrawer(null)} onSelect={selectConversation} onNewConversation={createConversation} onDelete={deleteConversation} />
      <ConversationPane conversation={activeConversation} messages={activeMessages} partner={snapshot.partner} aiConfigured={snapshot.aiConfigured} isSending={isSending} onSend={sendMessage} onOpenChats={() => setMobileDrawer("chats")} onOpenDetails={() => setMobileDrawer("details")} />
      <InspectorPanel partner={snapshot.partner} partnerDetail={partnerDetail} findings={findings} mobileOpen={mobileDrawer === "details"} onCloseMobile={() => setMobileDrawer(null)} onSaveEntry={saveEntry} onConfirmFindings={confirmFindings} api={api} profileRefreshKey={profileRefreshKey} onError={setToast} />
      {toast && <div className="toast" role="status"><Icon name="check" size={16} />{toast}<button onClick={() => setToast("")} aria-label="Hinweis schließen"><Icon name="close" size={15} /></button></div>}
    </div>
  );
}
