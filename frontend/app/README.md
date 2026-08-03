# LedgerFlow Web App

The React single-page app for LedgerFlow. Talks to the Django REST API; no
server-side rendering.

## Stack

- **Vite + React 18 + TypeScript** — SPA behind JWT auth (no SEO surface, so no
  Next.js/SSR)
- **TanStack Query** — server-state caching and invalidation over the REST API
- **React Router** — routing, with route-level code splitting
- **react-hook-form + zod** — forms and validation
- **Recharts** — dashboard charts (lazy-loaded with the dashboard route)
- The existing **`frontend/design-system/`** CSS (design tokens + components),
  imported unchanged

## Getting started

```bash
cp .env.example .env      # VITE_API_BASE_URL=http://localhost:8000/api/v1
npm install
npm run dev               # http://localhost:5173
```

Run the backend alongside (`make run` from the repo root, or the Docker stack).
Create an account via the in-app **Create account** link, or a superuser with
`python manage.py createsuperuser`.

## Scripts

- `npm run dev` — dev server with HMR
- `npm run build` — typecheck + production build to `dist/`
- `npm run preview` — serve the production build locally

## Architecture

```
src/
  api/          typed API client (JWT refresh, X-Tenant-ID injection) + per-domain calls
  hooks/        TanStack Query hooks, one file per domain
  lib/          AuthContext (session + workspace switching), money formatting
  components/   AppShell, ProtectedRoute, Money
  pages/        one component per route
  styles/       design-system CSS (tokens, base, components) + app-specific additions
```

Key conventions:

- **Money is always integer minor units** (cents) across the API and app; the
  only float conversion is at display/entry (`lib/money.ts`).
- **Every tenant-scoped request carries `X-Tenant-ID`** — injected centrally in
  `api/client.ts` from the active workspace. Switching workspace does a full
  reload so no cross-tenant data can bleed across the switch.
- **401 handling is centralized**: the client tries one silent refresh, retries
  once, and otherwise dispatches a `lf:session-expired` event the AuthContext
  listens for.

## Production

Built and served by Caddy in the deploy stack — see `deploy/README.md`.
