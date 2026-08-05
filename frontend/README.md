# AutoAudit AI — Frontend

React + TypeScript + Vite + Tailwind v4 dashboard for the AutoAudit AI API.

## Stack

- React 19 + TypeScript, built with Vite
- Tailwind CSS v4 (CSS-first `@theme` tokens — see `src/index.css`)
- TanStack React Query for all server state (polling, caching, mutations)
- React Router for navigation
- Framer Motion for the pipeline scan-beam animation
- Recharts for the health-score trend chart
- lucide-react for icons

No shadcn/ui component library is vendored in — the design system's own
`src/components/ui/*` primitives (Card, Badge, Button, EmptyState, Skeleton)
cover everything the pages need, styled directly with Tailwind utilities
generated from the custom `@theme` tokens.

## Design system

Dark, "instrument panel" aesthetic — see the Design Plan note in
`prompts.md` for the full rationale. Key tokens live in `src/index.css`:

- Surfaces: `ink` (page bg) -> `panel` -> `panel-raised`
- Text: `fog-0` (primary) -> `fog-1` -> `fog-2` (dimmest)
- Severity/status palette: `critical`, `warning`, `caution`, `info`, `success`
  (functional, not decorative — these are the actual finding-severity colors
  used throughout Findings/Fixes/Dashboard)
- Brand accent: `signal` (used sparingly, for interactive/active states only)
- Type: Space Grotesk (display), Inter (body/UI), IBM Plex Mono (all numeric
  data — confidence scores, line numbers, timestamps, fingerprints)

The signature element is the **Pipeline Rail** (`src/components/PipelineRail.tsx`):
an animated node graph of the real agent execution order
(Supervisor -> Repository -> Security -> Quality -> Documentation -> Report),
with a traveling scan-beam animation on the active edge while an audit runs.
It appears condensed on the Dashboard and full-size on the Audit page.

## Running locally

Requires the backend API running first (from the repo root):

```bash
pip install -r requirements.txt
uvicorn autoaudit.api.app:app --reload --port 8000
```

Then, in this directory:

```bash
npm install
npm run dev
```

`vite.config.ts` proxies `/api/*` to `http://127.0.0.1:8000`, so the two dev
servers work together with no extra configuration. Open http://localhost:5173.

## Production build

```bash
npm run build
```

Outputs static files to `dist/`. Serve them behind any static host or
reverse proxy that also proxies `/api/*` to the FastAPI backend. The API
already sends permissive CORS headers, so `dist/` can also be hosted on a
separate origin if you point the API base URL there instead.

## Testing

```bash
npm run test           # run once (Vitest + React Testing Library)
npm run test:watch     # watch mode
npm run test:coverage  # with v8 coverage report
```

53 tests across utilities, the typed API client, key components
(FindingCard, HealthGauge, PipelineRail, UI primitives), and page-level
integration tests (Dashboard empty state, Findings page's full filter
logic — severity, search, confidence threshold, category — against mocked
API responses).

## Pages

| Route | Purpose |
|---|---|
| `/` | Dashboard — health score, mini pipeline status, severity stats, recent runs |
| `/repository` | Repository overview + doc coverage before/after an audit |
| `/audit` | Live pipeline execution (full Pipeline Rail + streaming trace logs) |
| `/explorer` | VS Code-style repository explorer: file tree, syntax-highlighted code, finding highlighting, click-to-jump, suggested fixes inline |
| `/findings` | Search/filter findings, evidence panel, "View in Explorer" deep link |
| `/fixes` | Generate and review Fix Agent proposals (patch, PR, tests) |
| `/ai-comparison` | Live Groq vs Gemini comparison on a prompt |
| `/memory` | Health-score trend chart, repository timeline, run-vs-run comparison |
| `/reports` | Markdown/HTML/JSON/PDF export + preview |
| `/settings` | Model/provider status, cache/performance info |

## Known gaps (not yet built)

- No light theme.
- No auth — matches the backend, which also has no auth yet.
- Advanced Findings filters cover severity, agent, AI model, finding type,
  file path, confidence, status, and full-text search; there's no saved-filter-
  presets feature yet.
