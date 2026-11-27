# apoBank Partner-Copilot — Frontend

Responsive Oberfläche für persistente Chats, Partnerakten und manuelle Erfassung. Sie nutzt die FastAPI-API im selben Repository.

## Lokal starten

```bash
npm install
npm run dev
```

Öffne danach http://127.0.0.1:3000. Das Backend muss parallel auf Port 8000 laufen; die Oberfläche spricht es im lokalen Entwicklungsmodus direkt an.

## Struktur

- `app/` — Next.js App Router, globales Layout und Styles
- `components/workspace/` — Chat-Seitenleiste, Unterhaltung und Partnerakten-Panel
- `lib/workspace-contracts.ts` — typisierter Vertrag zwischen UI und Datenzugriff
- `lib/workspace-api.ts` — HTTP-Adapter für Chats, Vermittler, Notizen, Uploads und Bestätigungen

## API und KI

`WorkspaceApi` hält die Komponenten von HTTP-Details getrennt. Der konkrete Adapter speichert Chats, legt Vermittler und Notizen an und lädt Partnerakten aus FastAPI. Die OpenAI-Anfrage erfolgt ausschließlich im Python-Backend; der Browser bekommt keinen API-Key.

Für die Produktionsauslieferung wird die App als statischer Export gebaut und durch FastAPI bereitgestellt. Dadurch verwendet sie auch dort dieselbe relative `/api`-Adresse.
