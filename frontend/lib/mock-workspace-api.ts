import { demoWorkspace } from "./demo-data";
import type {
  ChatMessage,
  ManualEntryInput,
  SavedEntry,
  WorkspaceApi,
  WorkspaceSnapshot,
} from "./workspace-contracts";

function copySnapshot(): WorkspaceSnapshot {
  return JSON.parse(JSON.stringify(demoWorkspace)) as WorkspaceSnapshot;
}

/** Demo adapter. Replace with an HTTP-backed WorkspaceApi when backend endpoints are ready. */
export function createMockWorkspaceApi(): WorkspaceApi {
  return {
    async loadWorkspace() {
      return copySnapshot();
    },
    async sendMessage(_conversationId, content): Promise<ChatMessage> {
      const query = content.length > 74 ? `${content.slice(0, 71)}…` : content;
      return {
        id: `demo-${Date.now()}`,
        role: "assistant",
        content: `Ich habe „${query}“ aufgenommen. In diesem Frontend-Prototyp werden noch Demo-Daten verwendet; nach Anschluss des Backends kann ich die passenden Akten und Quellen dazu laden.`,
        createdAt: "Jetzt",
        source: "Prototyp · noch keine Backend-Verbindung",
      };
    },
    async createEntry(input: ManualEntryInput): Promise<SavedEntry> {
      const label =
        input.kind === "partner"
          ? input.name.trim() || "Neuer Vermittler"
          : `Gesprächsnotiz für ${input.partnerName}`;
      return { id: `demo-entry-${Date.now()}`, label };
    },
    async confirmFindings() {
      // Intentionally a no-op in the demo adapter.
    },
  };
}
