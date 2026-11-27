import type {
  ChatMessage,
  ChatReply,
  Conversation,
  ExtractedFinding,
  ManualEntryInput,
  PartnerDetail,
  PartnerSummary,
  SavedEntry,
  WorkspaceApi,
  WorkspaceSnapshot,
} from "./workspace-contracts";

type ApiRecord = Record<string, unknown>;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isLocalFrontend = typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname) && window.location.port === "3000";
  const apiBase = isLocalFrontend ? "http://127.0.0.1:8000/api" : "/api";
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : "Die Anfrage konnte nicht verarbeitet werden.");
  }
  return response.json() as Promise<T>;
}

function record(value: unknown): ApiRecord {
  return value && typeof value === "object" ? value as ApiRecord : {};
}

function dateLabel(value: unknown): string {
  if (typeof value !== "string" || !value) return "Jetzt";
  const date = new Date(value.replace(" ", "T") + (value.includes("Z") ? "" : "Z"));
  if (Number.isNaN(date.getTime())) return "Jetzt";
  return new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" }).format(date);
}

function statusLabel(value: unknown): string {
  return value === "aktiv" ? "Aktiv" : value === "inaktiv" ? "Inaktiv" : value === "gesperrt" ? "Gesperrt" : "In Prüfung";
}

function toPartner(value: unknown): PartnerSummary | null {
  const item = record(value);
  const nr = item.vermittler_nr;
  if (typeof nr !== "number") return null;
  return {
    vermittlerNr: nr,
    name: String(item.name ?? item.anzeigename ?? "Unbekannter Vermittler"),
    company: String(item.company ?? item.firma_filiale ?? "Kein Unternehmen hinterlegt"),
    partnerId: String(item.partner_id ?? `VM-${nr}`),
    relationshipManager: String(item.relationship_manager ?? record(item.betreuung).name ?? "Nicht zugeordnet"),
    status: statusLabel(item.status),
  };
}

function toFinding(value: unknown, index: number): ExtractedFinding | null {
  const item = record(value);
  const group = item.group;
  if (group !== "partner" && group !== "business" && group !== "next-step") return null;
  return {
    id: String(item.id ?? `finding-${index}`),
    group,
    label: String(item.label ?? "Angabe"),
    value: String(item.value ?? ""),
    source: String(item.source ?? "Chat"),
    status: item.status === "confirmed" ? "confirmed" : "new",
  };
}

function findingsFrom(value: unknown): ExtractedFinding[] {
  return Array.isArray(value)
    ? value.map(toFinding).filter((finding): finding is ExtractedFinding => finding !== null)
    : [];
}

function toMessage(value: unknown): ChatMessage {
  const item = record(value);
  const metadata = record(item.metadata);
  return {
    id: String(item.id ?? crypto.randomUUID()),
    role: item.role === "user" ? "user" : "assistant",
    content: String(item.content ?? ""),
    createdAt: dateLabel(item.created_at),
    findings: findingsFrom(metadata.findings),
    partner: toPartner(metadata.partner) ?? undefined,
    aiConfigured: metadata.openai_configured === true,
    source: Array.isArray(metadata.sources) && metadata.sources.length > 0 ? metadata.sources.map(String).join(" · ") : undefined,
  };
}

function toConversation(value: unknown): Conversation {
  const item = record(value);
  return {
    id: String(item.id),
    title: String(item.titel ?? "Neue Unterhaltung"),
    preview: String(item.vorschau ?? "Noch keine Nachrichten"),
    updatedAt: dateLabel(item.aktualisiert_am),
    vermittlerNr: typeof item.vermittler_nr === "number" ? item.vermittler_nr : undefined,
  };
}

function isEmptyConversation(conversation: Conversation): boolean {
  return conversation.title === "Neue Unterhaltung" && conversation.preview === "Noch keine Nachrichten";
}

function toPartnerFromProfile(value: unknown): PartnerSummary | null {
  const item = record(value);
  const nr = item.vermittler_nr;
  if (typeof nr !== "number") return null;
  return {
    vermittlerNr: nr,
    name: String(item.anzeigename ?? `${item.vorname ?? ""} ${item.name ?? ""}`.trim()),
    company: String(item.firma_filiale ?? "Kein Unternehmen hinterlegt"),
    partnerId: `VM-${nr}`,
    relationshipManager: String(record(item.betreuung).name ?? "Nicht zugeordnet"),
    status: statusLabel(item.status),
  };
}

function toPartnerDetail(value: unknown): PartnerDetail | null {
  const item = record(value);
  const summary = toPartnerFromProfile(item);
  if (!summary) return null;
  const contact = record(item.kontakt);
  const betreuung = record(item.betreuung);
  const figures = Array.isArray(item.geschaeftszahlen) ? item.geschaeftszahlen.map(record) : [];
  return {
    ...summary,
    email: String(contact.email ?? ""),
    phone: String(contact.telefon_dienst ?? contact.handy_dienst ?? ""),
    location: [contact.plz, contact.ort].filter(Boolean).join(" "),
    branch: String(betreuung.filiale ?? ""),
    marketArea: String(betreuung.marktgebiet ?? ""),
    interests: Array.isArray(item.interessen) ? item.interessen.map(String) : [],
    businessFigures: figures.map((figure) => ({
      year: Number(figure.jahr ?? 0),
      volume: Number(figure.volumen_eur ?? 0),
      loanCount: Number(figure.anzahl_darlehen ?? 0),
    })).filter((figure) => figure.year > 0),
  };
}

function splitName(fullName: string): { vorname: string; name: string } {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length < 2) throw new Error("Bitte Vor- und Nachname eingeben.");
  return { vorname: parts.slice(0, -1).join(" "), name: parts[parts.length - 1] ?? "" };
}

function toParticipants(value: string): string[] {
  return value.split(",").map((participant) => participant.trim()).filter(Boolean);
}

function toNextSteps(value: string): Array<{ beschreibung: string }> {
  return value.split("\n").map((step) => step.trim()).filter(Boolean).map((beschreibung) => ({ beschreibung }));
}

async function resolvePartner(input: Extract<ManualEntryInput, { kind: "note" }>): Promise<PartnerSummary> {
  if (input.vermittlerNr) {
    const profile = await request<unknown>(`/vermittler/${input.vermittlerNr}`);
    const partner = toPartnerFromProfile(profile);
    if (partner) return partner;
  }
  const result = record(await request<unknown>(`/vermittler?q=${encodeURIComponent(input.partnerName)}&limit=8`));
  const items = Array.isArray(result.items) ? result.items : [];
  const exact = items.find((candidate) => {
    const item = record(candidate);
    return `${item.vorname ?? ""} ${item.name ?? ""}`.trim().toLocaleLowerCase("de-DE") === input.partnerName.trim().toLocaleLowerCase("de-DE");
  }) ?? items[0];
  const nr = record(exact).vermittler_nr;
  if (typeof nr !== "number") throw new Error("Vermittler nicht gefunden. Bitte zuerst einen Vermittler anlegen.");
  const profile = await request<unknown>(`/vermittler/${nr}`);
  const partner = toPartnerFromProfile(profile);
  if (!partner) throw new Error("Partnerakte konnte nicht geladen werden.");
  return partner;
}

export function createWorkspaceApi(): WorkspaceApi {
  return {
    async loadWorkspace(): Promise<WorkspaceSnapshot> {
      const data = record(await request<unknown>("/chat/workspace"));
      const allConversations = Array.isArray(data.conversations) ? data.conversations.map(toConversation) : [];
      let emptyConversationShown = false;
      const conversations = allConversations.filter((conversation) => {
        if (!isEmptyConversation(conversation)) return true;
        if (emptyConversationShown) return false;
        emptyConversationShown = true;
        return true;
      });
      const rawMessages = record(data.messages_by_conversation);
      const messagesByConversation = Object.fromEntries(conversations.map((conversation) => {
        const rawConversationMessages = rawMessages[conversation.id];
        return [
          conversation.id,
          Array.isArray(rawConversationMessages) ? rawConversationMessages.map(toMessage) : [],
        ];
      }));
      const currentMessages = conversations[0] ? messagesByConversation[conversations[0].id] ?? [] : [];
      const latestAssistant = [...currentMessages].reverse().find((message) => message.role === "assistant");
      return {
        conversations,
        messagesByConversation,
        partner: latestAssistant?.partner ?? null,
        findings: latestAssistant?.findings ?? [],
        aiConfigured: data.openai_configured === true,
      };
    },

    async createConversation(): Promise<Conversation> {
      return toConversation(await request<unknown>("/chat/conversations", {
        method: "POST",
        body: JSON.stringify({ titel: "Neue Unterhaltung" }),
      }));
    },

    async sendMessage(conversationId: string, content: string): Promise<ChatReply> {
      const data = record(await request<unknown>(`/chat/conversations/${conversationId}/messages`, {
        method: "POST",
        body: JSON.stringify({ inhalt: content }),
      }));
      const message = toMessage(data.message);
      return {
        message,
        partner: toPartner(data.partner),
        findings: findingsFrom(data.findings),
        aiConfigured: data.openai_configured === true,
      };
    },

    async getPartnerDetail(vermittlerNr: number): Promise<PartnerDetail> {
      const detail = toPartnerDetail(await request<unknown>(`/vermittler/${vermittlerNr}`));
      if (!detail) throw new Error("Partnerakte konnte nicht geladen werden.");
      return detail;
    },

    async createEntry(input: ManualEntryInput): Promise<SavedEntry> {
      if (input.kind === "partner") {
        const name = splitName(input.name);
        const profile = await request<unknown>("/vermittler", {
          method: "POST",
          body: JSON.stringify({
            ...name,
            firma_filiale: input.company || undefined,
            kontakt: input.email ? { email: input.email } : undefined,
          }),
        });
        const partner = toPartnerFromProfile(profile);
        if (!partner) throw new Error("Der neue Vermittler konnte nicht geladen werden.");
        return { id: String(partner.vermittlerNr), label: partner.name, partner };
      }

      const partner = await resolvePartner(input);
      const teilnehmer = toParticipants(input.participants);
      const massnahmen = toNextSteps(input.nextSteps);
      if (input.file) {
        const form = new FormData();
        form.set("file", input.file);
        form.set("titel", input.title);
        form.set("inhalt", input.content);
        form.set("datum", input.date);
        form.set("teilnehmer", teilnehmer.join(","));
        form.set("massnahmen", massnahmen.map((step) => step.beschreibung).join("\n"));
        await request(`/vermittler/${partner.vermittlerNr}/dokumente`, { method: "POST", body: form });
      } else {
        await request(`/vermittler/${partner.vermittlerNr}/obsidian/eintraege`, {
          method: "POST",
          body: JSON.stringify({
            typ: "gespraech",
            titel: input.title,
            inhalt: input.content,
            datum: input.date,
            teilnehmer,
            massnahmen,
            quelle: "manuell",
            autor: "ui",
          }),
        });
      }
      return { id: `note-${Date.now()}`, label: `Gesprächsnotiz für ${partner.name}`, partner };
    },

    async confirmFindings(_conversationId: string, partner: PartnerSummary, findings: ExtractedFinding[]): Promise<void> {
      await request(`/vermittler/${partner.vermittlerNr}/obsidian/eintraege`, {
        method: "POST",
        body: JSON.stringify({
          typ: "notiz",
          titel: "Aus dem Chat übernommene Angaben",
          inhalt: findings.map((finding) => `- **${finding.label}:** ${finding.value}`).join("\n"),
          quelle: "chat",
          autor: "ui",
          tags: ["chat-bestaetigt"],
        }),
      });
    },
  };
}
