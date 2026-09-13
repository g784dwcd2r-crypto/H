# Disclosure web (Phase 3)

Next.js app with three screens: search, company page (period rows + collapsed "other filings"), statements view (IS / BS / CF tabs, periods as columns, Excel download). No form codes on the surface.

```bash
cd web && npm install
cp .env.example .env.local     # FILINGS_API_URL, FILINGS_API_KEY (server-side only)
npm run dev                    # http://localhost:3000, against `filings-hub api` on :8000
npm run build && npm start     # production
```

Deploy to Vercel with the `web/` directory as the project root and the two environment variables set. The API key is only used in server components and the `/api/export` route handler.
