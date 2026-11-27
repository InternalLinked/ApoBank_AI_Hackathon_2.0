export type Conversation = {
  id: string;
  title: string;
  preview: string;
  updatedAt: string;
  vermittlerNr?: number;
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
  findings?: ExtractedFinding[];
  partner?: PartnerSummary;
  aiConfigured?: boolean;
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
  vermittlerNr: number;
  name: string;
  company: string;
  partnerId: string;
  relationshipManager: string;
  status: string;
};

export type WorkspaceSnapshot = {
  conversations: Conversation[];
  messagesByConversation: Record<string, ChatMessage[]>;
  partner: PartnerSummary | null;
  findings: ExtractedFinding[];
  aiConfigured: boolean;
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
      file?: File | null;
      vermittlerNr?: number;
    };

export type SavedEntry = {
  id: string;
  label: string;
  partner?: PartnerSummary;
};

export type ChatReply = {
  message: ChatMessage;
  partner: PartnerSummary | null;
  findings: ExtractedFinding[];
  aiConfigured: boolean;
};

export interface WorkspaceApi {
  loadWorkspace(): Promise<WorkspaceSnapshot>;
  createConversation(): Promise<Conversation>;
  deleteConversation(conversationId: string): Promise<void>;
  sendMessage(conversationId: string, content: string): Promise<ChatReply>;
  createEntry(input: ManualEntryInput): Promise<SavedEntry>;
  confirmFindings(conversationId: string, partner: PartnerSummary, findings: ExtractedFinding[]): Promise<void>;
}
