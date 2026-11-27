export type Conversation = {
  id: string;
  title: string;
  preview: string;
  updatedAt: string;
};

export type MessageMetric = {
  label: string;
  value: string;
  detail: string;
  tone?: "green" | "amber" | "blue";
};

export type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  content: string;
  createdAt: string;
  metrics?: MessageMetric[];
  bullets?: string[];
  source?: string;
};

export type FindingStatus = "new" | "confirmed";
export type FindingGroup = "partner" | "business" | "next-step";

export type ExtractedFinding = {
  id: string;
  group: FindingGroup;
  label: string;
  value: string;
  source: string;
  status: FindingStatus;
};

export type PartnerSummary = {
  name: string;
  company: string;
  partnerId: string;
  relationshipManager: string;
  status: "Aktiv" | "In Prüfung";
};

export type WorkspaceSnapshot = {
  conversations: Conversation[];
  messagesByConversation: Record<string, ChatMessage[]>;
  partner: PartnerSummary;
  findings: ExtractedFinding[];
};

export type ManualEntryInput =
  | {
      kind: "partner";
      name: string;
      company: string;
      relationshipManager: string;
      email: string;
    }
  | {
      kind: "note";
      partnerName: string;
      date: string;
      content: string;
      fileName?: string;
    };

export type SavedEntry = {
  id: string;
  label: string;
};

export interface WorkspaceApi {
  loadWorkspace(): Promise<WorkspaceSnapshot>;
  sendMessage(conversationId: string, content: string): Promise<ChatMessage>;
  createEntry(input: ManualEntryInput): Promise<SavedEntry>;
  confirmFindings(conversationId: string, findingIds: string[]): Promise<void>;
}
