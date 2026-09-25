# VeriTrack AI — web app

React 19 + Vite + Tailwind 4 + TanStack Query.

```bash
npm ci
npm run dev      # http://localhost:5173 (proxies /api to http://localhost:8000)
npm test         # vitest + Testing Library
npm run lint     # oxlint
npm run build    # production build in dist/
```

Structure: `src/pages` (one lazily-loaded chunk per page), `src/layouts`
(app shell: sidebar, command palette, theme), `src/components/ui` (design-system
kit + toasts), `src/api` (client with single-flight token refresh, typed
endpoints, query hooks), `src/navigation/nav.ts` (the single route ↔ role map
used by both the sidebar and the route guards).

Set `VITE_API_BASE_URL` only when the API is served from another origin; by
default the app calls `/api/*` on its own origin (Vite proxy, Vercel rewrite or
nginx).
