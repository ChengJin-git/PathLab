# Installation

PathLab is a browser/server web application. The server runs the Python services, PostgreSQL,
Redis and the research sandbox; users only need a modern browser. All commands below run from the
`app/` directory of the repository unless stated otherwise.

## Requirements

| Component | Version / notes |
| --- | --- |
| Operating system | Linux x86_64. Ubuntu 22.04 and 24.04 are tested. |
| GPU | NVIDIA GPU with a driver that supports CUDA 13 (PyTorch 2.12.1, `cu130` wheels). Training and feature extraction need a GPU; the web platform, viewer and chat run without one. |
| Python | 3.12 or newer. The pinned dependencies in `server/requirements.txt` install from PyPI and GitHub; this is verified on Python 3.12. |
| Node.js | 22.22.2+, 24.15+ or 26.x (26.13.0 LTS recommended), npm 10+. Only needed to build the web client. |
| PostgreSQL, Redis | The Ubuntu packages installed by `deploy/install-system-deps.sh`. |
| Apptainer | Required for research sessions (autonomous code execution). Docker can be used instead. |
| OpenSlide, LibreOffice | Installed by `deploy/install-system-deps.sh`; used for slide reading and document previews. |
| Disk | About 7 GB for the Python environment and 6 GB for the research sandbox image, plus your slides, features and model weights. |

## 1. System packages

```bash
git clone https://github.com/ChengJin-git/PathLab.git
cd PathLab/app
sudo bash deploy/install-system-deps.sh
```

The script installs PostgreSQL, Redis, OpenSlide, LibreOffice, build tools and Apptainer from the
official Ubuntu repositories and the Apptainer PPA. It does not install Node.js or the NVIDIA
driver; install those with your usual method and check with `node --version` and `nvidia-smi`.

## 2. Python environment

```bash
python3.12 -m venv ~/.local/share/PathLab/venv
source ~/.local/share/PathLab/venv/bin/activate
pip install --upgrade pip
pip install -r server/requirements.txt
python deploy/verify-runtime.py
```

`verify-runtime.py` imports every module the services need and runs small CPU/GPU computations;
it prints `"status": "passed"` on success.

Prepare the models used for literature retrieval and OCR, and install the pinned OpenCode release
(the agent runtime used by research sessions):

```bash
python deploy/prepare-knowledge.py          # embedding model, cached under HF_HOME
python deploy/prepare-ocr.py                # PP-OCR model for scanned PDFs
python deploy/install-opencode.py --output ~/.opencode/bin/opencode
```

`install-opencode.py` reads the pinned version from `package.json` (`opencodeVersion`) and verifies
the npm package checksum before installing it.

## 3. Web client

```bash
npm ci
npm run typecheck
npm run build        # outputs src/renderer/dist
```

`deploy/start.sh` also builds the client, so this step is only needed to check the toolchain.

## 4. Database and configuration

```bash
sudo systemctl enable --now postgresql redis-server
sudo -u postgres createuser --pwprompt pathlab
sudo -u postgres createdb --owner=pathlab pathlab
cp server/.env.example server/.env
```

Edit `server/.env`:

- `DATABASE_URL` with the password you chose (URL-encode special characters).
- `REDIS_URL` if Redis is not on `127.0.0.1:6379`.
- `JWT_SECRET`: a long random value, for example `openssl rand -hex 32`. Keep it stable; changing
  it signs everyone out.
- `DEFAULT_ADMIN_PASSWORD` for the first `admin` account. If unset, a random password is generated
  and printed once in `logs/backend.log` on the first start.
- Optionally `PATHLAB_UPLOADS_DIR`, an absolute path outside the repository where slides, features,
  models and results are stored.

The database schema is created automatically on first start. See [configuration.md](configuration.md)
for every variable.

## Research sandbox

Research sessions run generated code inside a container so that it cannot touch the host or other
users' data. Build the Apptainer image once:

```bash
export PATHLAB_PYTHON=$(which python)
"$PATHLAB_PYTHON" deploy/build-skills-runtime.py --rebuild-base
```

The build uses `server/backend/autoresearch/runtime/containers/pathlab-sandbox.def` (CUDA, PyTorch
and the ML stack) and `skills-runtime.def` (scientific tools, OpenCode). It verifies the candidate
image and only then publishes it to `~/.local/share/PathLab/sandbox/pathlab-sandbox.sif`, or to
`AUTORESEARCH_SANDBOX_IMAGE` if set. The build downloads several GB and can take an hour.

To use Docker instead, build `deploy/sandbox/Dockerfile` and set `PATHLAB_SANDBOX_BACKEND=docker`
and `PATHLAB_DOCKER_IMAGE` in `server/.env`. For development only, `AUTORESEARCH_SANDBOX=local`
skips the sandbox check; generated code then runs on the host without isolation.

Optional credentials for research tools (PubMed, Unpaywall, image generation) go in
`<storage>/autoresearch/credentials/skills.env` (mode 600), where `<storage>` is the storage
directory; see `deploy/research-skills.env.example`.

## 5. Start

```bash
export PATHLAB_PYTHON=$(which python)
export PATHLAB_OPENCODE_BIN=~/.opencode/bin/opencode
bash deploy/start.sh
```

`start.sh` checks the Python packages, OpenCode and the sandbox, starts Redis if needed, builds the
web client into `src/renderer/dist` and launches `server/main.py`, which starts:

| Process | Port | Role |
| --- | --- | --- |
| Gateway | 6100 | Public API, authentication, chat, research API |
| Preprocessing | 6101 | Slide reading, tiles, thumbnails |
| AI | 6102 | Training, inference, feature extraction |
| TaskWorker | — | GPU task queue |
| ResearchWorker | — | Research sessions and article writing |

Check the services:

```bash
curl -f http://127.0.0.1:6100/health
curl -f http://127.0.0.1:6101/health
curl -f http://127.0.0.1:6102/health
```

Logs are in `logs/backend.log`. `deploy/hot-reload.sh frontend|backend|gateway|...` restarts a part
of the system after a code change.

## 6. nginx and HTTPS

Browsers reach PathLab through nginx. Copy a template and replace the placeholders (server name,
certificate paths and the absolute path of `app/`):

- `deploy/nginx/pathlab.conf` — HTTPS
- `deploy/nginx/pathlab-http-only.conf` — HTTP for a private network

| Path | Target |
| --- | --- |
| `/` | `app/src/renderer/dist` (single-page app) |
| `/api/` | Gateway `127.0.0.1:6100/` |
| `/preprocessing/` | `127.0.0.1:6101/` |
| `/ai/` | `127.0.0.1:6102/api/ai/` |

## 7. Run as a service

`deploy/systemd/pathlab.service` is a systemd unit template. Replace the placeholder paths and user,
set `PATHLAB_PYTHON`, `PATHLAB_OPENCODE_BIN` and other variables in its `Environment=` lines or the
`EnvironmentFile`, then:

```bash
sudo cp deploy/systemd/pathlab.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pathlab
```

Do not run `deploy/start.sh` while the systemd service is active; the script refuses to start a
second copy.

## 8. First sign-in

1. Open the site and sign in as `admin`.
2. **Settings → General**: set the language-model endpoint, API key and model (any
   OpenAI-compatible service, or a local vLLM server), and a Hugging Face token for gated models.
3. **Settings → Users**: create accounts. Roles are `admin` (everything, including user and system
   settings), `pathologist` (all research features) and `guest` (data and chat, no GPU jobs).
4. **Data → Upload**: register slides or patches and their labels.

Foundation-model weights are downloaded on first use into `<storage>/extractor_checkpoints`.
Gated models (for example UNI, CONCH, Virchow) require accepting their license on Hugging Face with
the account whose token you configured.

## GPUs

By default the server detects healthy GPUs at start-up and excludes devices that fail a probe. To
pin devices, set `CUDA_VISIBLE_DEVICES=0,1` in `server/.env`. The task queue estimates memory per
job and leases devices; see `app/server/task_worker/GPU-SCHEDULING.md`.

## Upgrading

1. Stop the service.
2. Back up PostgreSQL and the storage directory.
3. `git pull`, then `pip install -r server/requirements.txt` in a new virtual environment and
   `npm ci`.
4. Start the service. The schema version is checked at start-up; if a release changes the schema,
   its notes describe the migration.

Moving an installation to another server is described in `app/deploy/guides/MIGRATION.md`.

## Tests

```bash
npm run test:run                                   # frontend (Vitest)
pip install -r server/requirements-test.txt
cd server && python -m pytest tests/ -q --ignore=tests/test_ai_extractors_pretrained.py
```

Backend tests that use PostgreSQL read `DATABASE_URL` and work in temporary schemas.
`test_ai_extractors_pretrained.py` downloads model weights and needs a GPU; run it separately.
