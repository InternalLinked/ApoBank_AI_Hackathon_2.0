import type { WorkspaceSnapshot } from "./workspace-contracts";

// Synthetic UI data only. Replace this module with data returned by the backend.
export const demoWorkspace: WorkspaceSnapshot = {
  partner: {
    name: "Lea Winter",
    company: "Winter Finanzberatung",
    partnerId: "VP-2048",
    relationshipManager: "M. Fischer",
    status: "Aktiv",
  },
  conversations: [
    {
      id: "annual-review",
      title: "Jahresgespräch vorbereiten",
      preview: "Zusammenfassung & nächste Schritte",
      updatedAt: "10:42",
    },
    {
      id: "pipeline-review",
      title: "Pipeline und offene Vorgänge",
      preview: "Zwei Fälle brauchen Nachverfolgung",
      updatedAt: "Gestern",
    },
    {
      id: "meeting-note",
      title: "Notiz aus dem letzten Termin",
      preview: "Gesprächsnotiz strukturiert erfassen",
      updatedAt: "Di",
    },
  ],
  messagesByConversation: {
    "annual-review": [
      {
        id: "annual-user-1",
        role: "user",
        content: "Bereite mich auf das nächste Gespräch mit Lea Winter vor.",
        createdAt: "10:39",
      },
      {
        id: "annual-assistant-1",
        role: "assistant",
        content:
          "Ich habe die Partnerakte und die letzten Gesprächsnotizen zusammengeführt. Hier ist der aktuelle Überblick für dein Gespräch:",
        createdAt: "10:40",
        metrics: [
          {
            label: "Vermitteltes Volumen 2025",
            value: "4,8 Mio. €",
            detail: "18 Darlehen",
            tone: "green",
          },
          {
            label: "Offene Pipeline",
            value: "1,2 Mio. €",
            detail: "3 Vorgänge in Bearbeitung",
            tone: "blue",
          },
          {
            label: "Nächster Termin",
            value: "04. Dez",
            detail: "Jahresgespräch",
            tone: "amber",
          },
        ],
        bullets: [
          "Zwei Finanzierungsvorgänge warten auf eine Rückmeldung.",
          "Die Partnerin möchte Konditionsfragen vor dem nächsten Abschluss klären.",
        ],
        source: "Partnerakte · Gesprächsnotiz vom 18.11.2026",
      },
      {
        id: "annual-assistant-2",
        role: "assistant",
        content:
          "Ich habe drei Angaben aus der Notiz rechts übernommen. Bitte prüfe die Quelle und bestätige die Einträge, bevor sie in der Partnerakte landen.",
        createdAt: "10:41",
      },
    ],
    "pipeline-review": [
      {
        id: "pipeline-user-1",
        role: "user",
        content: "Welche Vorgänge brauchen gerade Aufmerksamkeit?",
        createdAt: "Gestern",
      },
      {
        id: "pipeline-assistant-1",
        role: "assistant",
        content:
          "In der Demo sind drei offene Vorgänge hinterlegt. Zwei warten auf eine Rückmeldung, einer benötigt noch Unterlagen.",
        createdAt: "Gestern",
        metrics: [
          {
            label: "Offene Vorgänge",
            value: "3",
            detail: "2 Rückmeldungen · 1 Unterlage",
            tone: "amber",
          },
        ],
        source: "Demo-Daten · Pipeline-Übersicht",
      },
    ],
    "meeting-note": [
      {
        id: "note-user-1",
        role: "user",
        content: "Hilf mir, die letzte Gesprächsnotiz zu strukturieren.",
        createdAt: "Di",
      },
      {
        id: "note-assistant-1",
        role: "assistant",
        content:
          "Gern. Du kannst die Notiz rechts manuell erfassen oder Gesprächsinhalte hier schreiben. Ich mache daraus einen Entwurf, den du vor dem Speichern prüfen kannst.",
        createdAt: "Di",
        bullets: [
          "Gesprächsdatum und Teilnehmende",
          "Besprochene Inhalte und Hindernisse",
          "Vereinbarte nächste Schritte",
        ],
      },
    ],
  },
  findings: [
    {
      id: "finding-company",
      group: "partner",
      label: "Partnerunternehmen",
      value: "Winter Finanzberatung",
      source: "Gesprächsnotiz · 18.11.2026",
      status: "new",
    },
    {
      id: "finding-topic",
      group: "partner",
      label: "Gesprächsthema",
      value: "Finanzierungspipeline und Jahresplanung",
      source: "Gesprächsnotiz · 18.11.2026",
      status: "new",
    },
    {
      id: "finding-volume",
      group: "business",
      label: "Vermitteltes Volumen 2025",
      value: "4,8 Mio. €",
      source: "Demo-Musterliste · Datenstand 2025",
      status: "new",
    },
    {
      id: "finding-pipeline",
      group: "business",
      label: "Offene Pipeline",
      value: "1,2 Mio. € · 3 Vorgänge",
      source: "Gesprächsnotiz · 18.11.2026",
      status: "new",
    },
    {
      id: "finding-next-step",
      group: "next-step",
      label: "Vorgeschlagener nächster Schritt",
      value: "Konditionsfragen für zwei Vorgänge klären",
      source: "Gesprächsnotiz · 18.11.2026",
      status: "new",
    },
  ],
};
