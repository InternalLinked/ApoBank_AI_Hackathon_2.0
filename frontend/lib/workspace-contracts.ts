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
  /** Mehrere passende Vermittler: werden als Auswahl-Buttons unter der Antwort angezeigt. */
  candidates?: PartnerCandidate[];
  /** SQL-Analysen dieser Antwort – Diagramm und SQL im Tab „Analyse“. */
  analyses?: Analysis[];
  /** Änderungsvorschläge der KI – erst nach Bestätigung im Tab „Änderungen“ gespeichert. */
  proposals?: ChangeProposal[];
  /** Automatisch gewähltes Modell, z. B. { name: "gpt-5-nano", tier: "smalltalk", seconds: 1.2 } */
  model?: { name: string; tier: string; rounds: number; seconds: number };
};

export type ProposalStatus = "offen" | "bestaetigt" | "verworfen";

export type ProposedChange = {
  /** z. B. „Kontakt“, „Stammdaten“, „Geschäftszahlen“, „Persönliches Profil“ */
  area: string;
  /** z. B. „E-Mail“, „Kreditvolumen (EUR) 2025“ */
  label: string;
  oldValue: string | number | null;
  newValue: string | number | null;
  kind: "stammdaten" | "kontakt" | "geschaeftszahlen" | "profil_fakt_aendern" | "profil_fakt_loeschen" | "profil_fakt_neu" | "notiz_neu";
};

export type ChangeProposal = {
  id: string;
  status: ProposalStatus;
  vermittlerNr: number;
  vermittler: string;
  reason: string;
  changes: ProposedChange[];
  createdAt: string;
};

export type ChartType = "balken" | "linie" | "tabelle";
export type ChartUnit = "eur" | "anzahl" | "prozent" | "keine";

export type Analysis = {
  id: string;
  title: string;
  /** Genau das SQL, das die KI ausgeführt hat */
  sql: string;
  columns: string[];
  rows: Array<Array<string | number | null>>;
  rowCount: number;
  truncated: boolean;
  chart: { type: ChartType; x: string; y: string; unit: ChartUnit };
  /** Zeitpunkt der zugehörigen Antwort, z. B. „18:42“ */
  createdAt: string;
};

export type PartnerCandidate = {
  vermittlerNr: number;
  /** Voller Name inkl. Titel, z. B. „Dr. Anna Scholz“ */
  name: string;
  company?: string;
  location?: string;
};

export type FindingStatus = "new" | "confirmed";
export type FindingGroup = "partner" | "business" | "next-step" | "persoenlich";

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

export type PartnerDetail = PartnerSummary & {
  email: string;
  phone: string;
  location: string;
  branch: string;
  marketArea: string;
  interests: string[];
  /** obsidian://-Link auf die Hub-Notiz des Vermittlers. */
  obsidianUri: string;
  businessFigures: Array<{
    year: number;
    volume: number;
    loanCount: number;
  }>;
};

export type ProfileCategory = "interessen" | "familie" | "haustiere" | "hobbys" | "reisen" | "vorlieben" | "termine" | "sonstiges";

/** Eine persönliche Info aus dem Obsidian-Profil (z. B. „Hat einen Hund namens Tim“). */
export type ProfileFact = {
  id: string;
  category: string;
  categoryLabel: string;
  text: string;
  date: string | null;
};

export type PersonalProfile = {
  facts: ProfileFact[];
  categories: Record<string, string>;
  /** obsidian://-Link auf die Profil-Notiz. */
  obsidianUri: string;
};

export type ObsidianGraphNode = {
  id: string;
  label: string;
  /** vermittler | profil | fakt | eintrag | betreuer | filiale | vermittler-link | notiz */
  type: string;
  uri: string | null;
  detail: string | null;
};

export type ObsidianGraph = {
  center: string;
  nodes: ObsidianGraphNode[];
  edges: Array<{ from: string; to: string }>;
};

export type StartSuggestion = "top10" | "einbrueche" | "gespraech" | "marktgebiete" | "portfolio" | "notizen";

export type WorkspaceSnapshot = {
  accountName: string | null;
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
      title: string;
      content: string;
      participants: string;
      nextSteps: string;
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
  /** Gesetzt, wenn der Copilot einen Fehler gemeldet hat (z. B. „… (OPENAI_AUTH · HTTP 401)“). */
  error?: string;
};

export type Transcription = {
  text: string;
  /** Länge der Aufnahme in Sekunden */
  seconds: number;
  /** Bearbeitungszeit bei Amazon Transcribe */
  processingMs: number;
};

export interface WorkspaceApi {
  loadWorkspace(): Promise<WorkspaceSnapshot>;
  /** Excel-Export (.xlsx, im Backend erzeugt); liefert den Dateinamen */
  exportAnalysis(analysis: Analysis): Promise<string>;
  exportPartner(vermittlerNr: number): Promise<string>;
  /** Änderungsvorschlag der KI ausführen (409 bei Konflikt) bzw. verwerfen */
  confirmProposal(proposalId: string): Promise<{ partner: PartnerSummary | null }>;
  rejectProposal(proposalId: string): Promise<void>;
  /** Sprachaufnahme (16-bit-PCM, mono) per Amazon Transcribe in Text umwandeln */
  transcribe(pcm: Blob, sampleRate: number, language?: string): Promise<Transcription>;
  createConversation(): Promise<Conversation>;
  deleteConversation(conversationId: string): Promise<void>;
  sendMessage(conversationId: string, content: string, startSuggestion?: StartSuggestion): Promise<ChatReply>;
  getPartnerDetail(vermittlerNr: number): Promise<PartnerDetail>;
  createEntry(input: ManualEntryInput): Promise<SavedEntry>;
  confirmFindings(conversationId: string, partner: PartnerSummary, findings: ExtractedFinding[]): Promise<void>;
  getProfile(vermittlerNr: number): Promise<PersonalProfile>;
  addProfileFact(vermittlerNr: number, text: string, category?: ProfileCategory): Promise<ProfileFact>;
  deleteProfileFact(vermittlerNr: number, factId: string): Promise<void>;
  getObsidianGraph(vermittlerNr: number): Promise<ObsidianGraph>;
}
