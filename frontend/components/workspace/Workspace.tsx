"use client";

import { useEffect, useRef, useState } from "react";
import { createWorkspaceApi, errorMessage } from "@/lib/workspace-api";
import type { Analysis, ChangeProposal, DashboardData, ChatAttachment, ChatMessage, ExtractedFinding, ManualEntryInput, PartnerCandidate, PartnerDetail, PartnerSummary, StartSuggestion, WorkspaceApi, WorkspaceSnapshot } from "@/lib/workspace-contracts";
import { ChatSidebar } from "./ChatSidebar";
import { ConversationPane } from "./ConversationPane";
import { DashboardView } from "./DashboardView";
import { InspectorPanel } from "./InspectorPanel";
import { Icon } from "./Icons";

const emptyWorkspace: WorkspaceSnapshot = {
  accountName: null,
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
  // Rechte Leiste ist standardmäßig eingefahren und öffnet sich nie automatisch (auch nicht, wenn der Copilot
  // einen Vermittler findet) – nur per Klick auf einen Namen, einen Auswahl-Button oder den Knopf oben rechts.
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  // Mitte: Chat oder Berater-Dashboard (Knopf oben in der linken Leiste)
  const [view, setView] = useState<"chat" | "dashboard">("chat");
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [dashboardLoading, setDashboardLoading] = useState(false);
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

  /** Änderungsvorschlag der KI ausführen; danach Partnerakte und Profil neu laden, damit die neuen Werte sichtbar sind */
  async function confirmProposal(proposal: ChangeProposal): Promise<boolean> {
    try {
      const { partner } = await api.confirmProposal(proposal.id);
      setToast(`${proposal.changes.length} ${proposal.changes.length === 1 ? "Änderung" : "Änderungen"} für ${proposal.vermittler} gespeichert.`);
      if (partner) setCurrentPartner(partner);
      setProfileRefreshKey((key) => key + 1);
      return true;
    } catch (error) {
      setToast(errorMessage(error, "Die Änderungen konnten nicht gespeichert werden."));
      return false;
    }
  }

  /** Excel-Export aus dem Analyse-Tab; Fehler mit Code/Ref als Hinweis */
  async function exportAnalysis(analysis: Analysis): Promise<void> {
    try {
      const filename = await api.exportAnalysis(analysis);
      setToast(`Excel-Datei „${filename}“ wurde heruntergeladen.`);
    } catch (error) {
      setToast(errorMessage(error, "Der Excel-Export ist fehlgeschlagen."));
    }
  }

  /** Auswahlfeld im Analyse-Tab geändert: Backend rechnet mit dem gespeicherten SQL neu (keine neue KI-Frage).
   *  Das Ergebnis ersetzt die Analyse in der Nachricht – die Auswahl bleibt auch nach einem Tab-Wechsel. */
  async function rerunAnalysis(analysis: Analysis, values: Record<string, string>): Promise<Analysis> {
    try {
      const updated = await api.rerunAnalysis(analysis, values);
      setSnapshot((current) => {
        const messagesByConversation: Record<string, ChatMessage[]> = {};
        for (const [conversationId, messages] of Object.entries(current.messagesByConversation)) {
          messagesByConversation[conversationId] = messages.map((message) =>
            message.analyses?.some((item) => item.id === updated.id)
              ? { ...message, analyses: message.analyses.map((item) => (item.id === updated.id ? updated : item)) }
              : message);
        }
        return { ...current, messagesByConversation };
      });
      return updated;
    } catch (error) {
      setToast(errorMessage(error, "Die Analyse konnte nicht neu berechnet werden."));
      throw error;
    }
  }

  async function loadDashboard() {
    setDashboardLoading(true);
    try {
      setDashboard(await api.getDashboard());
    } catch (error) {
      setToast(errorMessage(error, "Das Dashboard konnte nicht geladen werden."));
    } finally {
      setDashboardLoading(false);
    }
  }

  function openDashboard() {
    setView("dashboard");
    void loadDashboard(); // bei jedem Öffnen frisch, z. B. nach bestätigten Änderungen im Chat
  }

  /** Auswahlfeld in einem Dashboard-Diagramm geändert: neu berechnen und im Dashboard ersetzen */
  async function rerunDashboardAnalysis(analysis: Analysis, values: Record<string, string>): Promise<Analysis> {
    try {
      const updated = await api.rerunAnalysis(analysis, values);
      setDashboard((current) => current && { ...current, analyses: current.analyses.map((item) => (item.id === updated.id ? updated : item)) });
      return updated;
    } catch (error) {
      setToast(errorMessage(error, "Das Diagramm konnte nicht neu berechnet werden."));
      throw error;
    }
  }

  async function rejectProposal(proposal: ChangeProposal): Promise<boolean> {
    try {
      await api.rejectProposal(proposal.id);
      setToast("Änderungsvorschlag verworfen – nichts gespeichert.");
      return true;
    } catch (error) {
      setToast(errorMessage(error, "Der Vorschlag konnte nicht verworfen werden."));
      return false;
    }
  }

  /** Mikrofon → Amazon Transcribe; Fehler mit Code/Ref (z. B. TRANSCRIBE_RECHTE), damit sie im Log auffindbar sind */
  async function transcribeAudio(pcm: Blob, sampleRate: number): Promise<string> {
    try {
      return (await api.transcribe(pcm, sampleRate)).text;
    } catch (error) {
      throw new Error(errorMessage(error, "Die Transkription ist fehlgeschlagen."));
    }
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

  /** Liefert false, wenn nicht gesendet wurde (z. B. Anhang abgelehnt) – dann behält das Eingabefeld Text und Datei. */
  async function sendMessage(content: string, startSuggestion?: StartSuggestion, file?: File | null): Promise<boolean> {
    if (isSending) return false;
    let conversationId = activeConversationId;
    if (!conversationId) {
      const conversation = await api.createConversation();
      conversationId = conversation.id;
      setActiveConversationId(conversationId);
      setSnapshot((current) => ({ ...current, conversations: [conversation, ...current.conversations], messagesByConversation: { ...current.messagesByConversation, [conversationId]: [] } }));
    }
    // Anhang zuerst hochladen: Wird die Datei abgelehnt (Typ, Größe, unlesbar), geht die Nachricht gar nicht erst raus
    let attachments: ChatAttachment[] = [];
    if (file) {
      setIsSending(true);
      try {
        attachments = [await api.uploadAttachment(conversationId, file)];
        if (attachments[0].hint) setToast(attachments[0].hint);
      } catch (error) {
        setToast(errorMessage(error, "Der Anhang konnte nicht hochgeladen werden."));
        setIsSending(false);
        return false;
      }
    }
    const userMessage: ChatMessage = { id: `user-${Date.now()}`, role: "user", content, createdAt: "Jetzt", attachments: attachments.length ? attachments : undefined };
    addMessage(conversationId, userMessage);
    setSnapshot((current) => ({
      ...current,
      conversations: current.conversations.map((conversation) => conversation.id === conversationId ? { ...conversation, preview: content, updatedAt: "Jetzt", title: conversation.title === "Neue Unterhaltung" ? content.slice(0, 34) : conversation.title } : conversation),
    }));
    setIsSending(true);
    try {
      const request = api.sendMessage(conversationId, content, startSuggestion, attachments.map((attachment) => attachment.id));
      const reply = startSuggestion
        ? (await Promise.all([request, new Promise<void>((resolve) => window.setTimeout(resolve, 2000))]))[0]
        : await request;
      addMessage(conversationId, reply.message);
      setSnapshot((current) => ({
        ...current,
        partner: reply.partner ?? current.partner,
        aiConfigured: reply.aiConfigured,
        // Titel vom Titel-Bot ersetzt den vorläufigen (abgeschnittene erste Frage)
        conversations: reply.title
          ? current.conversations.map((conversation) => (conversation.id === conversationId ? { ...conversation, title: reply.title as string } : conversation))
          : current.conversations,
      }));
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
    return true;
  }

  async function createConversation() {
    setView("chat");
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

  function selectCandidate(candidate: PartnerCandidate) {
    // Vorläufige Zusammenfassung sofort zeigen; loadPartnerDetail ersetzt sie durch die vollständige Akte.
    setCurrentPartner({
      vermittlerNr: candidate.vermittlerNr,
      name: candidate.name,
      company: candidate.company ?? "Kein Unternehmen hinterlegt",
      partnerId: `VM-${candidate.vermittlerNr}`,
      relationshipManager: "Wird geladen …",
      status: "Aktiv",
    });
    setFindings([]);
    openInspector();
  }

  /** Rechte Leiste öffnen – nur auf ausdrücklichen Klick des Nutzers, nie automatisch. */
  function openInspector() {
    setInspectorOpen(true);
    setMobileDrawer((current) => (current === null && window.matchMedia("(max-width: 900px)").matches ? "details" : current));
  }

  /** Leiste einfahren (die geladene Akte bleibt im Hintergrund erhalten). */
  function hideInspector() {
    setInspectorOpen(false);
    setMobileDrawer((current) => (current === "details" ? null : current));
  }

  /** Kreuz in der Partnerakte: Akte schließen (Chat bleibt offen, Akte lässt sich per Namen wieder öffnen). */
  function closePartner() {
    hideInspector(); // Leiste fährt ein, der Chat wird breiter
    setCurrentPartner(null);
    setFindings([]);
  }

  /** Klick auf einen Vermittlernamen im Chat-Text: Partnerakte rechts öffnen. */
  function openPartnerFromLink(vermittlerNr: number, name: string) {
    if (snapshot.partner?.vermittlerNr !== vermittlerNr) {
      selectCandidate({ vermittlerNr, name });
      return;
    }
    openInspector();
  }

  function selectConversation(conversationId: string) {
    setView("chat");
    setActiveConversationId(conversationId);
    const latest = [...(snapshot.messagesByConversation[conversationId] ?? [])].reverse().find((message) => message.role === "assistant");
    setFindings(latest?.findings ?? []);
    const selectedPartner = latest?.partner;
    setCurrentPartner(selectedPartner ?? null);
  }

  const inspectorCollapsed = !inspectorOpen;

  return (
    <div className={`workspace-shell ${inspectorCollapsed ? "inspector-collapsed" : ""} ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      {mobileDrawer && <button className="mobile-backdrop" aria-label="Seitenleiste schließen" onClick={() => setMobileDrawer(null)} />}
      <ChatSidebar accountName={snapshot.accountName} dashboardActive={view === "dashboard"} onOpenDashboard={openDashboard} conversations={snapshot.conversations} activeConversationId={activeConversationId} mobileOpen={mobileDrawer === "chats"} onCloseMobile={() => setMobileDrawer(null)} onSelect={selectConversation} onNewConversation={createConversation} onDelete={deleteConversation} />
      {view === "dashboard" ? (
        <DashboardView data={dashboard} loading={dashboardLoading} onReload={() => void loadDashboard()} onOpenChats={() => setMobileDrawer("chats")} sidebarCollapsed={sidebarCollapsed} onToggleSidebar={() => setSidebarCollapsed((collapsed) => !collapsed)} inspectorCollapsed={inspectorCollapsed} onToggleInspector={() => (inspectorOpen ? hideInspector() : openInspector())} onExport={exportAnalysis} onRerun={rerunDashboardAnalysis} onOpenPartner={openPartnerFromLink} />
      ) : (
        <ConversationPane conversation={activeConversation} messages={activeMessages} partner={snapshot.partner} aiConfigured={snapshot.aiConfigured} isSending={isSending} onSend={sendMessage} onOpenChats={() => setMobileDrawer("chats")} sidebarCollapsed={sidebarCollapsed} onToggleSidebar={() => setSidebarCollapsed((collapsed) => !collapsed)} onOpenDetails={openInspector} inspectorCollapsed={inspectorCollapsed} onExpandInspector={openInspector} onToggleInspector={() => (inspectorOpen ? hideInspector() : openInspector())} onSelectCandidate={selectCandidate} onOpenPartner={openPartnerFromLink} onTranscribe={transcribeAudio} onError={setToast} onConfirmProposal={confirmProposal} onRejectProposal={rejectProposal} onExportAnalysis={exportAnalysis} onRerunAnalysis={rerunAnalysis} />
      )}
      <InspectorPanel partner={snapshot.partner} partnerDetail={partnerDetail} findings={findings} mobileOpen={mobileDrawer === "details"} onCloseMobile={hideInspector} onSaveEntry={saveEntry} onConfirmFindings={confirmFindings} api={api} profileRefreshKey={profileRefreshKey} onError={setToast} onClosePartner={closePartner} />
      {toast && <div className="toast" role="status"><Icon name="check" size={16} />{toast}<button onClick={() => setToast("")} aria-label="Hinweis schließen"><Icon name="close" size={15} /></button></div>}
    </div>
  );
}
