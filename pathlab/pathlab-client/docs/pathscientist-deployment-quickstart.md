# PathScientist Deployment Quickstart

This is the operator-facing quickstart for deploying PathScientist as part of
the PathLab web app on a new Linux server. It is intentionally shorter than the
developer README and the migration notes: follow this file first, then use the
linked references only when you need detail.

## 0. What You Are Deploying

PathScientist runs inside the PathLab fixed-port web deployment:

```text
browser -> Gateway :6100 -> Preprocessing :6101
                       \-> AI :6102
                       \-> PathScientist sessions
```

Runtime state is split across:

- PostgreSQL: users, settings, PathLab metadata, and PathScientist session records.
- Redis: queue and async coordination.
- `PATHLAB_UPLOADS_DIR`: the PathLab data repository. PathScientist also uses
  this as its default dataset cache in the web route.
- `PATHSCIENTIST_BASE_DIR`: PathScientist workspaces, logs, conversations, and
  compact run artifacts. Defaults to `pathlab-client/uploads/pathscientist`.
- `PATHLAB_CKPT_DIR` / Hugging Face cache: foundation-model checkpoints.
- Apptainer image: isolated runtime for generated feature extraction, training,
  and external validation scripts.

The deployment script uses ports `6100/6101/6102`. Do not mix these with any
temporary development ports such as `6200/6201/6202/6203`.

## 1. System Packages

On Ubuntu/Debian-style hosts, install the base services and WSI libraries:

```bash
sudo apt-get update
sudo apt-get install -y \
  build-essential git curl bash pkg-config \
  python3 python3-venv python3-pip \
  nodejs npm \
  redis-server postgresql postgresql-client \
  libopenslide-dev openslide-tools \
  libgl1 libglib2.0-0
```

For real PathScientist runs, the server also needs a working NVIDIA driver/CUDA
stack. For sandboxed execution, install Apptainer or provide a site module that
makes `apptainer --version` work for the service user. The frontend build needs
Node.js 18 or newer; if the OS package is older, install Node from your site
module, NodeSource, nvm, or another approved source.

## 2. Code Checkout

```bash
git clone <repo-url> /home/<service-user>/PathLab
cd /home/<service-user>/PathLab
git checkout pathscientistv0.1.1dev
cd pathlab/pathlab-client
```

Run git commands from `/home/<service-user>/PathLab`; run web deployment
commands from `/home/<service-user>/PathLab/pathlab/pathlab-client`.

## 3. Python Environment

Create the PathScientist virtualenv at the path expected by both the standalone
launcher and `deploy/start.sh`:

```bash
cd /home/<service-user>/PathLab/pathlab/pathlab-client/server/backend/pathscientist

# Install uv if the server does not already provide it.
python3 -m pip install --user uv
export PATH="$HOME/.local/bin:$PATH"

uv venv .venv --python 3.12
uv pip install -r ../../requirements.txt
uv pip install -r ../../requirements-test.txt
uv pip install kaggle
```

If Python 3.12 is not available through the system package manager, install it
through the site module stack, pyenv, conda, or another approved host-specific
method before creating the venv.

Install a CUDA-enabled Torch build that matches the server. Do this after the
requirements if the generic dependency resolver installed the wrong build:

```bash
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

Replace `cu128` with the wheel index supported by the target driver. Do not copy
a `.venv` from another machine.

Verify the environment:

```bash
cd /home/<service-user>/PathLab/pathlab/pathlab-client/server/backend
OPENHANDS_SUPPRESS_BANNER=1 pathscientist/.venv/bin/python - <<'PY'
import importlib
for mod in ["openhands.sdk", "fastapi", "torch", "kaggle"]:
    importlib.import_module(mod)
    print("OK", mod)
import torch
print("cuda", torch.cuda.is_available(), torch.version.cuda, torch.__version__)
PY
```

## 4. Frontend Dependencies

```bash
cd /home/<service-user>/PathLab/pathlab/pathlab-client
node --version   # must be v18 or newer
npm install
```

`deploy/start.sh` will build the frontend to `src/renderer/dist` every time it
starts.

## 5. PostgreSQL And Redis

Create the database and user used by `DATABASE_URL`:

```bash
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='pathlab'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE pathlab LOGIN PASSWORD 'pathlab'"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='pathlab'" | grep -q 1 || \
  sudo -u postgres createdb -O pathlab pathlab
```

Verify both services:

```bash
psql postgresql://pathlab:pathlab@localhost:5432/pathlab -c 'select 1;'
redis-cli ping
```

## 6. PathLab Server Environment

Create `pathlab/pathlab-client/server/.env` and keep it out of git:

```bash
cd /home/<service-user>/PathLab/pathlab/pathlab-client
cp .env.example server/.env
chmod 600 server/.env
```

Edit `server/.env` and set at least:

```bash
DATABASE_URL=postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab
REDIS_URL=redis://localhost:6379/0
INTERNAL_API_KEY=<random-secret>
JWT_SECRET=<stable-random-secret>
APP_SALT=<stable-random-secret>
DEFAULT_ADMIN_PASSWORD=<initial-admin-password>

# Durable PathLab data repository. PathScientist web sessions use this as the
# default dataset cache unless PATHSCIENTIST_DATASET_CACHE_DIR is explicitly set.
PATHLAB_UPLOADS_DIR=/data/pathlab/uploads

# Foundation model checkpoints / Hugging Face cache.
PATHLAB_CKPT_DIR=/data/pathlab/checkpoints
HF_HOME=/data/pathlab/hf-cache
# Web sessions inherit PathLab Settings huggingface_token.
# Standalone/service fallback only:
# HF_TOKEN=<optional-huggingface-token>

# Optional GPU selection.
CUDA_VISIBLE_DEVICES=0,1
```

Use real random values for `INTERNAL_API_KEY`, `JWT_SECRET`, and `APP_SALT` in
any shared or long-lived deployment. `JWT_SECRET` must stay stable across
restarts or existing login sessions will be invalidated.

## 7. LLM And Hugging Face Settings

For the web UI, PathScientist inherits PathLab global LLM and Hugging Face
credentials from the PathLab Settings page. Do not configure a separate
`PATHSCIENTIST_LLM_*` block or require `HF_TOKEN` for normal Web/Gateway sessions:

- `openrouter_base_url` is reused as the OpenAI-compatible base URL.
- `openrouter_api_key` is reused as the API key.
- `huggingface_token` is forwarded into PathScientist and exposed as `HF_TOKEN`
  for gated foundation model downloads.
- PathScientist still runs its own default model, currently `gpt-5.5`, because
  the OpenHands/Codex runtime requires a compatible model profile.

After the first login, open Settings and save the LLM base URL, API key, and
Hugging Face token. Only for headless or standalone CLI use that bypasses the
Gateway, create
`server/backend/pathscientist/.env.local` instead:

```bash
PATHSCIENTIST_LLM_PROFILE=codex-relay
PATHSCIENTIST_LLM_MODEL=gpt-5.5
PATHSCIENTIST_LLM_WIRE_API=responses
PATHSCIENTIST_LLM_BASE_URL=https://your-relay.example/v1
PATHSCIENTIST_LLM_API_KEY=<secret>
```

Only `PATHSCIENTIST_*` keys are loaded from `.env.local`. Put `KAGGLE_*` and
`GDC_TOKEN` in `server/.env` or the service environment. Use `HF_TOKEN` there
only for standalone/headless fallback; Web sessions use PathLab Settings.

## 8. Data Repository Layout

Use `PATHLAB_UPLOADS_DIR` as the main durable PathLab data repository. A
PathLab/PathScientist dataset should be registered in the database and should
point to a durable directory with this general layout:

```text
<dataset-root>/
  WSIs/                  # raw slides, or symlinks to raw slides
  labels.csv             # slide labels when available
  splits.csv             # optional train/val/test split table
  patches/               # coordinate files, for example <slide>_coords.h5
  pt_files/
    virchow2/            # feature tensors, for example <slide>.pt
    uni2/
```

Rules of thumb:

- If labels are missing but metadata exists, PathScientist may try to infer a
  task-specific label view before training.
- If raw WSIs exist but features are missing, PathScientist should extract
  features first and persist them under the dataset root for reuse.
- If features already exist under `pt_files/<extractor>/`, future sessions can
  reuse them.

If you need a separate dataset cache, set `PATHSCIENTIST_DATASET_CACHE_DIR` in
`server/.env`. Otherwise the web route defaults it to `PATHLAB_UPLOADS_DIR`.

## 9. Apptainer Sandbox

The host backend still runs in the Python virtualenv. The Apptainer image is
used for generated feature extraction, training, and external validation code.

Build from `pathlab-client`:

```bash
cd /home/<service-user>/PathLab/pathlab/pathlab-client
mkdir -p .local/pathscientist/sandbox

APPTAINER_TMPDIR=/tmp apptainer build --fakeroot --force \
  .local/pathscientist/sandbox/pathlab-sandbox.sif \
  server/backend/pathscientist/runtime/containers/pathlab-sandbox.def
```

If `/tmp` is small, use a larger local disk for `APPTAINER_TMPDIR`.

Add the sandbox config to `server/backend/pathscientist/.env.local` or to the
service environment:

```bash
PATHSCIENTIST_SANDBOX=auto
PATHSCIENTIST_SANDBOX_IMAGE=/home/<service-user>/PathLab/pathlab/pathlab-client/.local/pathscientist/sandbox/pathlab-sandbox.sif
PATHSCIENTIST_SANDBOX_CGROUPS=0
```

Use `PATHSCIENTIST_SANDBOX=apptainer` when you want startup/runs to fail loudly
if Apptainer is unavailable. `PATHSCIENTIST_SANDBOX_CGROUPS=0` is useful on
hosts where user cgroup CPU/memory limits are rejected.

Verify:

```bash
cd /home/<service-user>/PathLab/pathlab/pathlab-client
apptainer exec --nv .local/pathscientist/sandbox/pathlab-sandbox.sif \
  python -c "import torch; print(torch.__version__); print(torch.cuda.is_available(), torch.cuda.device_count())"

PYTHONPATH=server/backend \
PATHSCIENTIST_SANDBOX_IMAGE=$PWD/.local/pathscientist/sandbox/pathlab-sandbox.sif \
server/backend/pathscientist/.venv/bin/python - <<'PY'
from pathscientist.runtime.sandbox import ApptainerSandbox
print(ApptainerSandbox.check_available())
PY
```

The second command should print `True`. A real PathScientist session should log
an Apptainer command rather than local `python` execution.

## 10. Start The Web App

```bash
cd /home/<service-user>/PathLab/pathlab/pathlab-client
./deploy/start.sh
```

The script will:

1. stop old services on `6100/6101/6102`,
2. ensure Redis is running,
3. install Node dependencies if needed,
4. build the frontend,
5. start `server/main.py`, which launches Gateway, Preprocessing, and AI.

Check health:

```bash
curl -fsS http://127.0.0.1:6100/health
curl -fsS http://127.0.0.1:6101/health
curl -fsS http://127.0.0.1:6102/health
```

Open:

```text
http://127.0.0.1:6100/pathscientist
```

The initial admin account is created on first run. The password comes from
`DEFAULT_ADMIN_PASSWORD`; if that variable is missing, `server/main.py` defaults
it to `admin` for local development.

## 11. SSH Tunnel For Remote Testing

From your laptop:

```bash
ssh -N -L 127.0.0.1:16100:127.0.0.1:6100 <service-user>@<server-host>
```

Then open:

```text
http://127.0.0.1:16100/pathscientist
```

Forward only the Gateway port for the built deployment. A separate Vite dev
server is optional and is not part of this quickstart.

## 12. Smoke Test

Use a small registered dataset first. Example prompt:

```text
Use a small registered WSI dataset as internal training data.
Train an ABMIL slide-level classification model.
If features are missing, extract features first.
Run only a quick smoke test with a small number of epochs.
```

After the run starts, verify:

- the session log shows dataset grounding and data readiness before training,
- feature extraction runs before training when features are missing,
- the sandbox command appears when Apptainer is enabled,
- the UI shows training progress and final metrics,
- durable features/model artifacts land outside the temporary workspace.

## 13. Operations Commands

```bash
# Full restart
cd /home/<service-user>/PathLab/pathlab/pathlab-client
./deploy/start.sh

# Hot reload backend or frontend
./deploy/hot-reload.sh backend
./deploy/hot-reload.sh frontend

# Logs
tail -f logs/backend.log

# Process/port check
ss -tlnp | grep -E ':6100|:6101|:6102'
```

## 14. Do Not Commit

Keep these local only:

```text
server/.env
server/backend/pathscientist/.env.local
.local/pathscientist/
uploads/
logs/
*.sif
kaggle.json
*token*.txt
.venv/
node_modules/
```

The repo `.gitignore` already excludes these paths. Recheck `git status` before
committing from a deployment server.

## 15. Troubleshooting

| Symptom | Check |
|---|---|
| `Invalid username or password` | Confirm which database `DATABASE_URL` points to and whether the admin user was created with the expected `DEFAULT_ADMIN_PASSWORD`. |
| `System is under maintenance` | Gateway is reachable but settings/maintenance state or backend health is wrong. Check `logs/backend.log` and `/health`. |
| `127.0.0.1 refused to connect` | Gateway is not running or the SSH tunnel points to the wrong port/host. Check `ss -tlnp` on the server. |
| `No LLM model configured` | Web: save PathLab Settings LLM base URL/API key. CLI: set `PATHSCIENTIST_LLM_*` in `.env.local`. |
| Sandbox falls back to local | Check `apptainer --version`, `PATHSCIENTIST_SANDBOX_IMAGE`, and `ApptainerSandbox.check_available()`. |
| `/data/...` missing in a session log | The prepared dataset mount was not passed to the sandbox, or the run used local mode. |
| Features are re-extracted every run | Confirm features are written to the durable dataset root under `pt_files/<extractor>/`, not only to the session workspace. |
| Huge unexpected download | Review `PATHSCIENTIST_AUTO_ACQUIRE_DATA`, `PATHSCIENTIST_DOWNLOAD_POLICY`, `PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB`, and provider credentials. |

## 16. References

- `server/backend/pathscientist/README.md`: developer guide and examples.
- `deploy/README.md`: fixed-port deployment script details, Nginx, and systemd templates.
- `docs/pathscientist-apptainer-sandbox.md`: Apptainer build and migration details.
- `server/backend/pathscientist/docs/dataset_acquisition.md`: provider and download policy behavior.
- `server/backend/pathscientist/docs/ENVIRONMENT.md`: detailed migration notes and environment-variable reference.
