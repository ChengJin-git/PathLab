# SmartResearch Frontend (skeleton)

- Stack: React + Vite + TypeScript
- Viewer: OpenSeadragon (bundled locally, no CDN)
- Base path: /SmartResearch/ (configure via env later, Nginx path already fixed)

Pages (planned):
- WSI viewer page with parameter panel (tile_size, stride, feature_model, aggregator, device)
- Results page: slide-level prediction, CSV export, attention overlay (P1)

Run locally (you run the commands):

1) Install deps (choose one)
- npm install  (or pnpm install / yarn)

2) Dev server (CORS already enabled on backend):
- npm run dev  (http://127.0.0.1:5173)
  - Uses .env.development → API_BASE=http://127.0.0.1:6100, AI_BASE=http://127.0.0.1:6102/api/ai

3) Build for Nginx prefix /SmartResearch/:
- npm run build → dist/
- Nginx serves SPA at /SmartResearch/ and proxies /SmartResearch/api/*

Environment:
- VITE_BASE_PATH: / (dev) or /SmartResearch/ (prod)
- VITE_API_BASE: http://127.0.0.1:6100 (dev) or /SmartResearch/api (prod)
- VITE_AI_BASE: http://127.0.0.1:6102/api/ai (dev) or /SmartResearch/api/ai (prod)

