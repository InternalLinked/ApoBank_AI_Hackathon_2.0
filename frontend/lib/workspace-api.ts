import type {
  Analysis,
  ChartType,
  ChartUnit,
  ChatMessage,
  ChatReply,
  Conversation,
  ExtractedFinding,
  ManualEntryInput,
  ObsidianGraph,
  PartnerCandidate,
  PartnerDetail,
  PartnerSummary,
  PersonalProfile,
  ProfileCategory,
  ProfileFact,
  SavedEntry,
  WorkspaceApi,
  WorkspaceSnapshot,
} from "./workspace-contracts";

type ApiRecord = Record<string, unknown>;

/** Fehler aus einem API-Aufruf, inkl. allem, was man zum Nachschlagen im Backend-Log braucht. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly code: string,
    readonly endpoint: string,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Kurzzeile für die Oberfläche, z. B. „HTTP 500 · INTERNER_FEHLER · Ref a1b2c3“. */
  get reference(): string {
    return [this.status ? `HTTP ${this.status}` : null, this.code, this.requestId ? `Ref ${this.requestId}` : null]
      .filter(Boolean)
      .join(" · ");
  }
}

const STATUS_TEXT: Record<number, string> = {
  400: "Die Anfrage war ungültig.",
  401: "Nicht angemeldet.",
  403: "Keine Berechtigung.",
  404: "Nicht gefunden.",
  409: "Konflikt mit vorhandenen Daten.",
  413: "Die Datei ist zu groß.",
  422: "Eingabe ungültig.",
  500: "Interner Serverfehler.",
  502: "Backend nicht erreichbar (Gateway).",
  503: "Backend vorübergehend nicht verfügbar.",
  504: "Backend hat nicht rechtzeitig geantwortet.",
};

function detailText(data: ApiRecord): string | null {
  if (typeof data.meldung === "string" && data.meldung) return data.meldung;
  if (typeof data.detail === "string" && data.detail) return data.detail;
  if (Array.isArray(data.detail)) {
    // FastAPI-Validierungsfehler: [{loc: ["body", "feld"], msg: "..."}]
    const parts = data.detail.map((entry) => {
      const item = record(entry);
      const loc = Array.isArray(item.loc) ? item.loc.filter((part) => part !== "body").join(".") : "";
      return `${loc ? `${loc}: ` : ""}${String(item.msg ?? "ungültig")}`;
    });
    if (parts.length > 0) return `Eingabe ungültig – ${parts.join("; ")}`;
  }
  return null;
}

const CLIENT_ID_KEY = "apobank.clientId";
let cachedClientId: string | null = null;

function randomId(): string {
  // crypto.randomUUID gibt es nur in sicheren Kontexten (HTTPS/localhost); getRandomValues überall.
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * Zufällige ID dieses Browsers. Das Backend zeigt nur Chats mit derselben ID.
 * Trennt die Ansicht, ist aber KEIN Zugriffsschutz (wer die ID kennt, sieht die Chats).
 */
function clientId(): string {
  if (cachedClientId) return cachedClientId;
  try {
    const stored = window.localStorage.getItem(CLIENT_ID_KEY);
    if (stored && /^[A-Za-z0-9-]{16,64}$/.test(stored)) return (cachedClientId = stored);
    const created = randomId();
    window.localStorage.setItem(CLIENT_ID_KEY, created);
    return (cachedClientId = created);
  } catch {
    // localStorage gesperrt (z. B. strikter Privatmodus): ID gilt nur bis zum Neuladen.
    return (cachedClientId = randomId());
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isLocalFrontend = typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname) && window.location.port === "3000";
  const apiBase = isLocalFrontend ? "http://127.0.0.1:8000/api" : "/api";
  const method = (init?.method ?? "GET").toUpperCase();
  const endpoint = `${method} ${path.split("?")[0]}`;

  let response: Response;
  try {
    const headers = new Headers(init?.headers);
    headers.set("X-Client-ID", clientId());
    // Bei FormData setzt der Browser Content-Type inkl. Boundary selbst.
    if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    response = await fetch(`${apiBase}${path}`, { ...init, headers });
  } catch (cause) {
    const error = new ApiError(
      `Backend nicht erreichbar (${apiBase}). Läuft der Server?`,
      null,
      "NETZWERK",
      endpoint,
    );
    console.error(`[API] ${endpoint} – Netzwerkfehler`, cause);
    throw error;
  }

  const requestId = response.headers.get("X-Request-ID");
  if (!response.ok) {
    const raw = await response.text().catch(() => "");
    let data: ApiRecord = {};
    try { data = record(JSON.parse(raw)); } catch { /* kein JSON, z. B. HTML vom Proxy */ }
    const message = detailText(data) ?? STATUS_TEXT[response.status] ?? `Unerwartete Antwort vom Server (${response.statusText || "ohne Statustext"}).`;
    const error = new ApiError(
      message,
      response.status,
      typeof data.fehler_code === "string" ? data.fehler_code : `HTTP_${response.status}`,
      endpoint,
      typeof data.request_id === "string" ? data.request_id : requestId,
    );
    console.error(`[API] ${endpoint} -> ${response.status} [${error.code}]${error.requestId ? ` ref=${error.requestId}` : ""}: ${message}`, data.detail ?? raw.slice(0, 500));
    throw error;
  }
  if (response.status === 204) return undefined as T;
  try {
    return await response.json() as T;
  } catch (cause) {
    console.error(`[API] ${endpoint} – Antwort ist kein gültiges JSON`, cause);
    throw new ApiError("Der Server hat eine unlesbare Antwort geschickt.", response.status, "UNGUELTIGE_ANTWORT", endpoint, requestId);
  }
}

/** Fehlertext für Toasts: Meldung plus Referenz (Status, Code, Request-ID). */
export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return `${error.message} (${error.reference})`;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
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
  if (group !== "partner" && group !== "business" && group !== "next-step" && group !== "persoenlich") return null;
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

function toCandidate(value: unknown): PartnerCandidate | null {
  const item = record(value);
  const nr = item.vermittler_nr;
  if (typeof nr !== "number") return null;
  return {
    vermittlerNr: nr,
    name: String(item.name ?? `Vermittler ${nr}`),
    company: typeof item.firma === "string" && item.firma ? item.firma : undefined,
    location: typeof item.ort === "string" && item.ort ? item.ort : undefined,
  };
}

function candidatesFrom(value: unknown): PartnerCandidate[] {
  return Array.isArray(value)
    ? value.map(toCandidate).filter((candidate): candidate is PartnerCandidate => candidate !== null)
    : [];
}

const CHART_TYPES: ChartType[] = ["balken", "linie", "tabelle"];
const CHART_UNITS: ChartUnit[] = ["eur", "anzahl", "prozent", "keine"];

function toAnalysis(value: unknown, createdAt: string): Analysis | null {
  const item = record(value);
  if (typeof item.id !== "string" || typeof item.sql !== "string") return null;
  const columns = Array.isArray(item.spalten) ? item.spalten.map(String) : [];
  const rows = Array.isArray(item.zeilen)
    ? item.zeilen.filter(Array.isArray).map((row: unknown[]) => row.map((cell) => (typeof cell === "number" || typeof cell === "string" ? cell : cell == null ? null : String(cell))))
    : [];
  const chart = record(item.diagramm);
  const type = CHART_TYPES.includes(chart.typ as ChartType) ? chart.typ as ChartType : "tabelle";
  const unit = CHART_UNITS.includes(chart.einheit as ChartUnit) ? chart.einheit as ChartUnit : "keine";
  return {
    id: item.id,
    title: String(item.titel ?? "Analyse"),
    sql: item.sql,
    columns,
    rows,
    rowCount: typeof item.anzahl === "number" ? item.anzahl : rows.length,
    truncated: item.abgeschnitten === true,
    chart: { type, x: String(chart.x ?? columns[0] ?? ""), y: String(chart.y ?? columns[columns.length - 1] ?? ""), unit },
    createdAt,
  };
}

function toMessage(value: unknown): ChatMessage {
  const item = record(value);
  const metadata = record(item.metadata);
  const candidates = candidatesFrom(metadata.kandidaten);
  const createdAt = dateLabel(item.created_at);
  const analyses = Array.isArray(metadata.analysen)
    ? metadata.analysen.map((analysis) => toAnalysis(analysis, createdAt)).filter((analysis): analysis is Analysis => analysis !== null)
    : [];
  return {
    candidates: candidates.length > 0 ? candidates : undefined,
    analyses: analyses.length > 0 ? analyses : undefined,
    id: String(item.id ?? randomId()),
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
    obsidianUri: String(record(item.obsidian).uri ?? ""),
    businessFigures: figures.map((figure) => ({
      year: Number(figure.jahr ?? 0),
      volume: Number(figure.volumen_eur ?? 0),
      loanCount: Number(figure.anzahl_darlehen ?? 0),
    })).filter((figure) => figure.year > 0),
  };
}

function toProfileFact(value: unknown): ProfileFact {
  const item = record(value);
  return {
    id: String(item.id ?? ""),
    category: String(item.kategorie ?? "sonstiges"),
    categoryLabel: String(item.kategorie_label ?? item.kategorie ?? "Sonstiges"),
    text: String(item.text ?? ""),
    date: typeof item.datum === "string" ? item.datum : null,
  };
}

/** Ordnet das vom Copilot gelieferte Label („Haustiere“, „Reisen & Urlaub“ …) einer Profil-Kategorie zu. */
function categoryFromLabel(label: string): ProfileCategory | undefined {
  const value = label.toLocaleLowerCase("de-DE");
  if (value.includes("famil")) return "familie";
  if (value.includes("haustier") || value.includes("tier")) return "haustiere";
  if (value.includes("hobby") || value.includes("freizeit")) return "hobbys";
  if (value.includes("reise") || value.includes("urlaub")) return "reisen";
  if (value.includes("vorliebe") || value.includes("gespräch") || value.includes("gespraech")) return "vorlieben";
  if (value.includes("datum") || value.includes("daten") || value.includes("termin") || value.includes("geburtstag")) return "termine";
  if (value.includes("sonstig")) return "sonstiges";
  return undefined; // Backend erkennt die Kategorie dann per Stichwort
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

    async deleteConversation(conversationId: string): Promise<void> {
      await request<void>(`/chat/conversations/${encodeURIComponent(conversationId)}`, { method: "DELETE" });
    },

    async sendMessage(conversationId: string, content: string): Promise<ChatReply> {
      const data = record(await request<unknown>(`/chat/conversations/${conversationId}/messages`, {
        method: "POST",
        body: JSON.stringify({ inhalt: content }),
      }));
      const message = toMessage(data.message);
      const fehler = record(data.fehler);
      let error: string | undefined;
      if (typeof fehler.code === "string") {
        const reference = [fehler.code, typeof fehler.status === "number" ? `HTTP ${fehler.status}` : null].filter(Boolean).join(" · ");
        error = `${String(fehler.meldung ?? "KI-Fehler")} (${reference})`;
        console.error(`[Copilot] ${error}`);
      }
      return {
        error,
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

    async confirmFindings(_conversationId: string, partner: PartnerSummary, allFindings: ExtractedFinding[]): Promise<void> {
      // Persönliches landet im Obsidian-Profil, alles andere wie bisher als Notiz-Eintrag.
      for (const finding of allFindings.filter((item) => item.group === "persoenlich")) {
        await request(`/vermittler/${partner.vermittlerNr}/profil/fakten`, {
          method: "POST",
          body: JSON.stringify({ text: finding.value, kategorie: categoryFromLabel(finding.label) }),
        });
      }
      const findings = allFindings.filter((item) => item.group !== "persoenlich");
      if (findings.length === 0) return;
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

    async getProfile(vermittlerNr: number): Promise<PersonalProfile> {
      const data = record(await request<unknown>(`/vermittler/${vermittlerNr}/profil`));
      const categories = record(data.kategorien);
      return {
        facts: Array.isArray(data.fakten) ? data.fakten.map(toProfileFact) : [],
        categories: Object.fromEntries(Object.entries(categories).map(([key, label]) => [key, String(label)])),
        obsidianUri: String(data.uri ?? ""),
      };
    },

    async addProfileFact(vermittlerNr: number, text: string, category?: ProfileCategory): Promise<ProfileFact> {
      return toProfileFact(await request<unknown>(`/vermittler/${vermittlerNr}/profil/fakten`, {
        method: "POST",
        body: JSON.stringify({ text, kategorie: category }),
      }));
    },

    async getObsidianGraph(vermittlerNr: number): Promise<ObsidianGraph> {
      const data = record(await request<unknown>(`/vermittler/${vermittlerNr}/obsidian/netz`));
      return {
        center: String(data.zentrum ?? ""),
        nodes: (Array.isArray(data.knoten) ? data.knoten : []).map((value) => {
          const item = record(value);
          return {
            id: String(item.id ?? ""),
            label: String(item.label ?? ""),
            type: String(item.typ ?? "notiz"),
            uri: typeof item.uri === "string" ? item.uri : null,
            detail: typeof item.detail === "string" ? item.detail : null,
          };
        }),
        edges: (Array.isArray(data.kanten) ? data.kanten : []).map((value) => {
          const item = record(value);
          return { from: String(item.von ?? ""), to: String(item.nach ?? "") };
        }),
      };
    },

    async deleteProfileFact(vermittlerNr: number, factId: string): Promise<void> {
      await request<void>(`/vermittler/${vermittlerNr}/profil/fakten/${encodeURIComponent(factId)}`, { method: "DELETE" });
    },
  };
}
