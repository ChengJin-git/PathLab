# Get Started: Local Service Startup

This guide starts PathLab locally for development. PathLab is an Electron +
React app with a Python sidecar backend. The sidecar starts Gateway,
Preprocessing, AI, and TaskWorker processes.

Local development requires PostgreSQL, Redis, and a stable `JWT_SECRET` before
`server/main.py` can start cleanly.

## 1. Prerequisites

- Node.js >= 18
- Python >= 3.10 with `pip`
- PostgreSQL and Redis for local development
- OpenSlide system library for WSI processing

On macOS with Homebrew:

```bash
brew install openslide
```

From the repository root, enter the Electron app directory. All following
commands assume this working directory:

```bash
cd pathlab/pathlab-client
```

## 2. Install Project Dependencies

Install the Node dependencies:

```bash
npm install
```

Install the Python backend dependencies:

```bash
pip install -r server/requirements.txt
```

Use the Python environment intended for PathLab before running `pip install`.

## 3. Install Local Runtime Services

On macOS with Homebrew:

```bash
brew install postgresql@16 redis
brew services start postgresql@16
brew services start redis
```

Create the PostgreSQL user and database expected by PathLab's default
configuration:

```bash
createuser -s pathlab
createdb -O pathlab pathlab
psql -d pathlab -c "ALTER USER pathlab WITH PASSWORD 'pathlab';"
```

The default service URLs are:

```text
DATABASE_URL=postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab
REDIS_URL=redis://localhost:6379/0
```

## 4. Export Required Environment Variables

Set these in the same terminal where you start the backend:

```bash
export DATABASE_URL="postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab"
export REDIS_URL="redis://localhost:6379/0"
export JWT_SECRET="dev-local-secret-change-this"
```

For repeated local development, put equivalent values in your shell profile or
source them from a local, gitignored environment file.

For zsh on macOS, add them to `~/.zshrc`:

```bash
cat >> ~/.zshrc <<'EOF'
export DATABASE_URL="postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab"
export REDIS_URL="redis://localhost:6379/0"
export JWT_SECRET="dev-local-secret-change-this"
EOF

source ~/.zshrc
```

For bash, use `~/.bashrc` instead:

```bash
cat >> ~/.bashrc <<'EOF'
export DATABASE_URL="postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab"
export REDIS_URL="redis://localhost:6379/0"
export JWT_SECRET="dev-local-secret-change-this"
EOF

source ~/.bashrc
```

If you prefer a project-local file, create a gitignored file such as
`server/.env.local` and source it before starting the backend:

```bash
source server/.env.local
python server/main.py
```

## 5. Start The App

### Option A: Electron Development

Use this for normal local desktop development:

```bash
npm run dev
```

In development mode, Electron starts `server/main.py` for you and passes the
dynamic backend ports to the renderer through preload/IPC. Development mode
does not start embedded PostgreSQL or Redis, so keep your local services
running.

### Option B: Backend Only With Dynamic Ports

Use this when you only want to debug the Python sidecar:

```bash
python server/main.py
```

By default, `server/main.py` auto-discovers available ports for Gateway,
Preprocessing, and AI.

### Option C: Backend Only With Fixed Ports

Use this for browser-style debugging or deployment-style local testing:

```bash
PATHLAB_DEBUG=1 python server/main.py
```

Fixed-port mode uses:

```text
Gateway: 6100
Preprocessing: 6101
AI: 6102
TaskWorker: no HTTP port
```

### Option D: Verified Browser Workflow With Fixed Ports

Use this workflow when you want to run the Web UI in a browser and log in
locally with the known admin account.

Start the backend in the `pathlab` conda environment:

```bash
cd PathLab/pathlab/pathlab-client/server

PATHLAB_DEBUG=1 \
GATEWAY_PORT=6100 \
PREPROCESSING_PORT=6101 \
AI_PORT=6102 \
DEFAULT_ADMIN_PASSWORD=admin \
PATHLAB_SKIP_TRAINING_RAG_PREWARM=1 \
python main.py
```

Then start the Vite frontend in another terminal:

```bash
cd PathLab/pathlab/pathlab-client/src/renderer

npm exec vite -- --host 0.0.0.0 --port 5173 --config vite.config.ts
```

Open the Web UI at:

```text
http://localhost:5173/
```

The Vite dev server proxies `/api` to the Gateway at
`http://127.0.0.1:6100`.

`PATHLAB_SKIP_TRAINING_RAG_PREWARM=1` skips the bundled training recommendation
RAG warmup during local startup. Without it, Gateway may spend a long time
parsing bundled PDFs with Marker before the app feels ready.

Use the local admin account:

```text
username: admin
password: admin
```

If the database already has users and the default admin auto-create path is
skipped, reset or upsert the local admin row so `username` and `email` are both
`admin`, the role is `admin`, the user is active/superuser/verified, and
`password_sha256` matches the SHA-256 hash of `admin`.

Verify the backend:

```bash
curl http://127.0.0.1:6100/health
```

Expected response:

```json
{"status":"ok","service":"gateway"}
```

Note that `http://127.0.0.1:6100` is the backend Gateway. In the current
codebase, Gateway does not serve the frontend `index.html` at `/`, so the root
path returns 404. Use `http://localhost:5173/` for the browser UI.

Stop both services with `Ctrl+C` in the backend and frontend terminal sessions.
If a port remains occupied, find the process:

```bash
lsof -nP -iTCP:6100 -sTCP:LISTEN
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

## 6. What Starts

`server/main.py` starts four backend processes:

- Gateway: initializes PostgreSQL and Redis, serves the public API, and
  coordinates frontend-facing backend routes.
- Preprocessing: serves WSI information, thumbnails, DZI descriptors, tiles,
  heatmap helpers, and related image-processing endpoints.
- AI: provides training, inference, feature extraction, and model-related
  internal endpoints.
- TaskWorker: consumes Redis task descriptors and runs long jobs, including
  training, inference, recovery, cancellation, and queue status publishing.

## 7. Packaged App vs Local Development

Packaged Electron builds start embedded PostgreSQL and Redis automatically,
then inject `DATABASE_URL` and `REDIS_URL` into the Python sidecar.

Local development does not use those embedded services. When running
`npm run dev` or `python server/main.py`, PostgreSQL and Redis must already be
running locally or reachable through your exported environment variables.

## 8. Deployment / Fixed-Port Script

For fixed-port web deployment, use:

```bash
./deploy/start.sh
```

The deployment script builds the frontend, sets `PATHLAB_DEBUG=1`, starts
`server/main.py`, and health-checks:

```text
http://127.0.0.1:6100/health
http://127.0.0.1:6101/health
http://127.0.0.1:6102/health
```

TaskWorker does not expose an HTTP health port; observe it through Redis queue
state and backend logs.

In some managed execution environments, `./deploy/start.sh` can complete its
health check but its background backend process may not remain alive after the
script returns. In that case, use Option D: keep `server/main.py` running in
the foreground and start the Vite frontend separately.

## 9. Tests

Run frontend tests:

```bash
npm run test:run
```

Install backend test dependencies:

```bash
pip install -r server/requirements-test.txt
```

Run backend tests, skipping pretrained-model tests:

```bash
python -m pytest server/tests/ -v -k "not pretrained"
```

Pretrained-model tests may require GPU access and model credentials, so run
them separately when needed.

## Quick Checks

Confirm PostgreSQL and Redis are listening:

```bash
nc -z localhost 5432
nc -z localhost 6379
```

Both commands should exit successfully before the backend can fully start.

## Troubleshooting

### `Connect call failed ('127.0.0.1', 5432)`

PostgreSQL is not running, is not listening on port `5432`, or the `pathlab`
database/user has not been created. Start PostgreSQL and verify
`DATABASE_URL`.

### Redis connection failures

Redis is not running on `localhost:6379`, or `REDIS_URL` points to the wrong
location. Start Redis and verify `REDIS_URL`.

### `JWT_SECRET not set`

This is a warning, not the database startup blocker. Set a stable local value:

```bash
export JWT_SECRET="dev-local-secret-change-this"
```

Without a stable `JWT_SECRET`, sessions are invalidated whenever the backend
restarts.

### `pynvml unavailable`

This is a GPU health-check warning, not the PostgreSQL startup blocker. The
backend falls back to PyTorch memory detection when `pynvml` is unavailable.
