# apoBank Partner-Copilot — Frontend-Prototyp

Responsive Oberfläche für Chat, Partnerakte und manuelle Erfassung. Die Oberfläche ist derzeit eine interaktive Demo mit synthetischen Beispieldaten; ein Backend ist noch nicht angeschlossen.

## Lokal starten

```bash
npm install
npm run dev
```

Öffne danach http://localhost:3000.

## Struktur

- `app/` — Next.js App Router, globales Layout und Styles
- `components/workspace/` — Chat-Seitenleiste, Unterhaltung und Partnerakten-Panel
- `lib/workspace-contracts.ts` — typisierter Vertrag zwischen UI und Datenzugriff
- `lib/demo-data.ts` — synthetischer UI-Zustand
- `lib/mock-workspace-api.ts` — Demo-Adapter für Laden, Chat, manuelle Einträge und Bestätigungen

## Backend anschließen

Die UI hängt an `WorkspaceApi` aus `lib/workspace-contracts.ts`. `createMockWorkspaceApi()` in `lib/mock-workspace-api.ts` ist der austauschbare Demo-Adapter. Für das Backend kann ein HTTP-Adapter dieselben Methoden implementieren (`loadWorkspace`, `sendMessage`, `createEntry`, `confirmFindings`), ohne Chat- und Panel-Komponenten an API-Details zu koppeln.

Die konkreten Endpunkte, Authentifizierung, Fehlerbehandlung und Persistenz sollen mit dem Backend-Team abgestimmt werden. Die Demo speichert keine Daten dauerhaft.
