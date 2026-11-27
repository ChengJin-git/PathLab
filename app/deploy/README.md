# Deployment

Step-by-step installation is in [docs/installation.md](../../docs/installation.md) and all settings
are in [docs/configuration.md](../../docs/configuration.md). This directory contains the scripts and
templates they use.

| Task | Document or script |
| --- | --- |
| New installation | [docs/installation.md](../../docs/installation.md) |
| Moving an installation to another server | [guides/MIGRATION.md](guides/MIGRATION.md) |
| Dependency versions and upgrades | [guides/DEPENDENCIES.md](guides/DEPENDENCIES.md) |
| Measuring responsiveness | [guides/PERFORMANCE.md](guides/PERFORMANCE.md) |

## Contents

```text
deploy/
├── README.md
├── guides/                     # migration, dependencies, performance
├── nginx/                      # HTTPS and HTTP reverse-proxy templates
├── systemd/                    # service unit template
├── sandbox/Dockerfile          # Docker research sandbox image
├── start.sh                    # full start: checks, client build, backend
├── hot-reload.sh               # restart one part after a code change
├── python-runtime.sh           # shared interpreter selection
├── install-system-deps.sh      # Ubuntu system packages
├── install-runtime.sh          # install an exported runtime bundle
├── runtime_bundle.py           # export / verify / restore runtime bundles
├── install-opencode.py         # install the pinned OpenCode release (npm SHA-512 verified)
├── verify-runtime.py           # import and compute checks for the Python environment
├── prepare-knowledge.py        # retrieval embedding model (prepare / --check)
├── prepare-ocr.py              # OCR models (prepare / --check)
├── build-autoresearch-sandbox.sh   # ML base layer of the Apptainer sandbox
├── build-skills-runtime.py         # full research sandbox image (adds scientific tools)
├── sync-research-skills.py         # fetch pinned third-party skills (commit + file hashes)
├── install-pathtrove-data.py       # install the pinned PathTrove data package
└── research-skills.env.example     # optional research tool credentials
```

Logs, screenshots and build outputs belong outside the repository or in the ignored `logs/`,
`build/` and `dist/` directories.

## Services and nginx

`start.sh` loads `server/.env`, verifies dependencies, stops an earlier instance, builds the web
client and starts `server/main.py`: Gateway (6100), Preprocessing (6101), AI (6102), TaskWorker and
ResearchWorker. After the health checks pass, also confirm that both workers are running and that a
real operation works. Logs are written to `logs/backend.log` and the main PID to `logs/backend.pid`.

| Path | Target |
| --- | --- |
| `/` | `src/renderer/dist` (single-page app) |
| `/api/` | Gateway `127.0.0.1:6100/` |
| `/preprocessing/` | `127.0.0.1:6101/` |
| `/ai/` | `127.0.0.1:6102/api/ai/` |
| `/ai/health` | `127.0.0.1:6102/health` |

The research API is `/api/research` through nginx (`/research` on the Gateway). Templates:
`nginx/pathlab.conf` (HTTPS), `nginx/pathlab-http-only.conf`, `systemd/pathlab.service`. In
production, put the interpreter and OpenCode paths in the unit's `Environment=` lines or
`EnvironmentFile`, not only in a terminal session.

`hot-reload.sh` accepts `frontend`, `backend`, `gateway`, `preprocessing`, `ai`, `task-worker`,
`research-worker` or `all`. Changes to shared protocols or worker code need a full backend restart.
The client is built into a temporary directory and swapped in atomically; PWA users pick up the new
service worker on their next load.

Both scripts choose the Python interpreter through `python-runtime.sh`, in this order:

1. `PATHLAB_PYTHON`
2. `server/backend/autoresearch/.venv/bin/python`
3. `venv/bin/python3` in the app directory
4. `$CONDA_PREFIX/bin/python3`
5. `python3` on `PATH`

If `server/.venv/pathlab.env` exists it is loaded first. The scripts check dependencies but never
upgrade packages implicitly.

## Storage and GPUs

- Storage root: `PATHLAB_UPLOADS_DIR` > the location saved in Settings (`storage.json`) > `uploads/`
  in the application-data directory. Change it later with the storage migration in **Settings →
  Storage**.
- `CUDA_VISIBLE_DEVICES=0,1,3` in `server/.env` restricts GPUs for all start paths; otherwise
  `server/main.py` probes GPUs and excludes unhealthy devices.
- The research sandbox image defaults to `~/.local/share/PathLab/sandbox/pathlab-sandbox.sif`
  (override with `AUTORESEARCH_SANDBOX_IMAGE`). Rebuild it with
  `"$PATHLAB_PYTHON" deploy/build-skills-runtime.py --rebuild-base`; the ML base layer is built by
  `deploy/build-autoresearch-sandbox.sh` and the scientific tools are added by the Python builder.
- Language models and Hugging Face access are configured in **Settings → General**. When moving a
  server, keep the database, storage and settings together.
