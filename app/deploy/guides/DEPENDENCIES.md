# Dependency baseline and upgrade policy

PathLab pins every dependency so an installation can be reproduced: the newest versions that work
together, chosen from actual releases, dependency resolution and functional checks.

## How versions are pinned

- `package.json` pins direct npm dependencies and overrides exactly; `package-lock.json` pins
  transitive dependencies with integrity hashes. Install with `npm ci`. `.npmrc` sets
  `save-exact=true`.
- OpenCode (the research agent runtime) is pinned in `package.json` as `opencodeVersion` (2.4.2).
  The installer, start-up check, sandbox builds and the research service all read this field;
  `deploy/install-opencode.py` verifies the npm SHA-512 checksum.
- `server/requirements.txt` and `requirements-test.txt` pin Python dependencies; GitHub packages are
  pinned to commit SHAs. A clean install from these files on Python 3.12 is tested.
- `deploy/runtime_bundle.py` can export an installed environment as hashed wheels with a
  `requirements.lock`, to move a verified environment to another server
  ([MIGRATION.md](MIGRATION.md)).
- The PathTrove MCP (catalog of public computational-pathology datasets used by the research agent)
  is pinned to commit `DearCaat/PathTrove@89cd983d` with per-file SHA-256 hashes in
  `skill_library/sources.lock.json`; its data package is pinned by size and SHA-256 in its
  `data-manifest.json` and verified at install and run time.
- The Apptainer and Docker sandboxes share `runtime/containers/ml-runtime-requirements.txt`; skill
  helpers are pinned in `skills-runtime-requirements.txt`. PyTorch is pinned per image.
- The Docker CPU sandbox image is tagged `pathlab/sandbox:1.0.8-r3-cpu`.

## Main versions

| Component | Version |
| --- | --- |
| Node.js | 26.13.0 LTS recommended; `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0` supported |
| React / React DOM | 18.3.1 |
| Vite | 8.3.6 |
| Tailwind CSS / TypeScript | 4.3.5 / 5.9.3 |
| React Router / React Query | 7.18.5 / 5.107.1 |
| Vitest / jsdom | 5.1.0 / 31.0.0 |
| FastAPI / Starlette / Pydantic | 0.141.1 / 1.10.0 / 2.14.3 |
| SQLAlchemy / asyncpg | 2.0.57 / 0.32.0 |
| PyTorch / torchvision / torchaudio | 2.12.1 / 0.27.1 / 2.11.0 (CUDA 13 wheels) |
| Transformers / timm / OpenCLIP | 5.12.1 / 1.0.27 / 3.3.0 |
| OpenAI Python / HTTPX | 2.54.0 / 0.28.1 |
| Redis Python | 8.1.0 |
| pytest / pytest-asyncio / Ruff | 9.2.0 / 1.4.1.post1 / 0.17.4 |

All other versions are in the dependency files.

## Why some versions are held back

| Held version | Reason |
| --- | --- |
| React 18, TypeScript 5 | Keeps the current editor, React types and tooling; React 19 and TypeScript 7 need a separate migration. |
| minimatch 10.2.6 (override) | Keeps the 10.x interface for older build dependencies. |
| SQLAlchemy 2.0.57 | `fastapi-users-db-sqlalchemy` 7.0.0 requires `<2.1`. |
| FastAPI 0.141.1, OpenAI 2.54.0, websockets 16.1.1 | Constrained by OpenTelemetry 1.39, `openai<3` and `websockets<17` in research dependencies (browser-use, google-genai, Laminar); `pip check` must stay clean. |
| NumPy 1.26.4, OpenCV 4.11.0.86, pandas 2.3.3, SciPy 1.17.1, tifffile 2026.3.3, PyArrow 24.0.0 | Compatible with the native slide readers; newer OpenCV, pandas, SciPy, tifffile and PyArrow require NumPy 2. NumPy 1.26.4 has wheels up to Python 3.12, which is why Python 3.12 is the recommended interpreter. |
| zarr 2.18.7 | Result bundles are written and read with the Zarr v2 interface. |
| PyTorch 2.12.1, timm 1.0.27, Transformers 5.12.1, OpenCLIP 3.3.0 | Existing weights and the CONCH package metadata depend on this combination; upgrades need the full pretrained-extractor test suite on a GPU. |
| scikit-learn 1.7.2 / scikit-survival 0.26.0 on the host; scikit-learn 1.9.0 in the sandbox | Keeps host survival metrics and the pickled research models in the sandbox loadable. |
| PyMuPDF / PyMuPDF Layout / pymupdf4llm 1.27.2.3 | The three packages are pinned together for the validated document-layout parser; the sandbox uses PyMuPDF 1.28.2 independently. |
| Skill tools: MCP 1.30.0, pypdf 6.21.4; Node 22.23.4, Mermaid CLI 11.4.0, Puppeteer 23.1.1 in the sandbox | Validated together with the image's Chromium, fonts, R, Office and TeX tools. |

## Upgrading

1. Create a new Python environment and upgrade within the constraints above.
2. Install the client from the lockfile and run the type check, unit tests, build and browser tests.
3. Run `python -m pip check`, `python deploy/verify-runtime.py` and the backend tests, including
   `test_ai_extractors_pretrained.py` on a GPU; check OpenCode authentication, sessions, the
   persistent inbox, pause and deletion.
4. After changing sandbox dependencies, rebuild the image and run the full skill verification
   (`runtime/containers/verify-skills-runtime.py`: Office/PDF, Python and R plots, TeX, Chromium,
   Mermaid, COCO).

Updating the repository does not replace an installed OpenCode binary, `node_modules` or Python
environment; the start-up check requires matching versions. After `git pull`:

```bash
nvm install && nvm use          # .nvmrc pins Node 26.13.0
npm ci
OPENCODE_BIN="${PATHLAB_OPENCODE_BIN:-$HOME/.opencode/bin/opencode}"
python3 deploy/install-opencode.py --output "$OPENCODE_BIN"
"$OPENCODE_BIN" --version       # opencode v2.4.2
```

Install Python upgrades into the environment selected by `deploy/python-runtime.sh` (an explicit
`PATHLAB_PYTHON` wins) while the service is stopped, then run `pip check` and
`deploy/verify-runtime.py`, and restart with `bash deploy/start.sh`.
