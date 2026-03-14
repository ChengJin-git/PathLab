# Repository Guidelines

## Project Structure & Module Organization
- Repository root is `PathLab/`, with the main app in `pathlab/pathlab-client/`.
- Frontend lives in `pathlab/pathlab-client/src/`:
  - `main/` (Electron main process), `preload/`, and `renderer/` (React UI).
  - UI pages are in `src/renderer/src/pages/`; shared UI in `src/renderer/src/components/`.
- Backend lives in `pathlab/pathlab-client/server/`:
  - `main.py` is the unified entrypoint.
  - `gateway/` exposes the FastAPI API; `backend/` hosts AI, preprocessing, database, and storage services.
- Build scripts: `build-python.sh`, `start_all.sh`, `start_all_yihui.sh`.

## Build, Test, and Development Commands
Run these from `pathlab/pathlab-client/` unless noted:
- `npm install`: install frontend dependencies.
- `npm run dev`: Electron dev mode with hot reload.
- `cd server && python main.py`: run backend only (prints `PORT=...`).
- `npm run build`: build Electron bundles.
- `npm run build:mac|win|linux`: produce installers.
- `./build-python.sh`: package the Python sidecar (requires `pyinstaller`).
- `npm run lint` / `npm run format`: ESLint auto-fix and Prettier formatting.

## Coding Style & Naming Conventions
- TypeScript/React: follow ESLint/Prettier outputs; components are `PascalCase` (e.g., `WSIViewer.tsx`), hooks `useX`, and files in `src/renderer` follow feature-based grouping.
- Python: `snake_case` modules/functions, async-aware APIs, and type hints where already used; mirror existing patterns in `server/`.

## Testing Guidelines
- Python tests use `pytest` (see `server/pyproject.toml`).
- Run: `cd server && uv run pytest` (or `python -m pytest` in an activated venv).
- Tests are under `server/**/tests` and `server/backend/agent/**/tests`; nnUNet integration scripts are under `server/backend/ai/segmentors/nnUNet/nnunetv2/tests`.

## Commit & Pull Request Guidelines
- Commit messages follow a short, prefixed style seen in history: `Feat:`, `Fix:`, `Chore:` (e.g., `Feat: Local vLLM support`).
- PRs should include a concise summary, key commands run, and screenshots/GIFs for UI changes.
- Note any new environment variables or data path changes in the PR description.

## Configuration & Secrets
- Copy `.env.example` or `src/renderer/.env.example` to a local `.env.*` file; never commit real secrets.
- OpenRouter keys should be configured via the Settings page; `.env` values are fallback defaults.
