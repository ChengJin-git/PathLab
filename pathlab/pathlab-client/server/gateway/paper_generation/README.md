# Paper Generation — dev environment

This folder contains the Gateway-facing API/repository glue for paper generation.
The standalone uv-managed paper agent now lives in `server/paper_agent/`.

The design and milestones live in [`docs/plan/paper_generation_agent_design.md`](../../../../../docs/plan/paper_generation_agent_design.md).

## Layout

```
paper_generation/
├── pyproject.toml           # uv project manifest (deps + dev groups)
├── uv.lock                  # uv lockfile (committed)
├── .venv/                   # uv-managed venv (gitignored)
│   └── lib/.../site-packages/
│       ├── _pathlab_root.pth   # auto-loaded; runs _pathlab_root.py
│       └── _pathlab_root.py    # walks up to add server/ to sys.path so
│                                 backend.* and gateway.* import without
│                                 setting PYTHONPATH manually
├── README.md                # this file
└── ...                      # the package itself (routes / agents / ...)
```

## Standalone dev runtime

```bash
cd pathlab/pathlab-client/server/paper_agent
uv sync
uv run pathlab-paper-agent serve --host 127.0.0.1 --port 6200
```

Gateway creates `/papers` runs and TaskWorker invokes the standalone CLI with
`uv run --project server/paper_agent pathlab-paper-agent run ...`.

## Legacy local test setup

```bash
cd pathlab/pathlab-client/server/gateway/paper_generation

# Create venv + install runtime deps
uv venv --python 3.12
uv sync

# Add dev / test deps (pytest, matplotlib, lifelines)
uv sync --group dev

# Set up cross-imports (one-time after every `uv sync` that recreates the venv)
bash scripts/install_pathlab_root_pth.sh
```

The cross-import setup script writes a `_pathlab_root.py` + `_pathlab_root.pth`
into the venv's `site-packages/`. Without this you'd have to prefix every
command with `PYTHONPATH=../../`.

## Usage

```bash
# Activate
source .venv/bin/activate

# OR run a one-off command
uv run python -c "from gateway.paper_generation.routes import router; print(router.prefix)"

# Tests
uv run pytest tests/ -v
```

## LLM provider — dev relay override

For development, paper-gen can route all LLM API calls through a private
OpenAI-compatible relay (e.g. `~/.codex` setup) **without touching PathLab
Settings UI**. This keeps the main chat assistant's OpenRouter/vLLM config
untouched.

```bash
# 1. Copy template
cp .env.example .env

# 2. Paste your API key from ~/.codex/auth.json
$EDITOR .env

# 3. Source before running tests / dev server
source .env
uv run pytest tests/test_llm_client.py
```

Three env vars together activate the override:

| Variable | Example |
|----------|---------|
| `PAPER_GEN_LLM_BASE_URL` | `https://relay.1hui.wang/openai/v1` |
| `PAPER_GEN_LLM_API_KEY`  | `cr_xxx...` (from `~/.codex/auth.json`) |
| `PAPER_GEN_LLM_MODEL`    | `claude-haiku-4-5` (or `gpt-5.5`, `gpt-5.4`) |

**Precedence**: `PAPER_GEN_LLM_*` (relay) → vLLM (if enabled) → OpenRouter
(from PathLab Settings or `OPENROUTER_*` env). Setting only `BASE_URL`
without `API_KEY` or `MODEL` is treated as misconfiguration and raises a
`RuntimeError` — fail-loud beats silently falling back to a different
backend.

**Wire protocol**: the provider always uses `stream=true` on the wire so
reasoning models (`gpt-5.x`) work. Streaming chunks are aggregated into a
single `LLMResponse.text` before returning, so callers don't need to care
about stream vs non-stream models.

**PHI safety**: the relay is an external service. PHI scrub (§3.6 of the
design doc) MUST run before any payload reaches `complete()`. The provider
trusts inputs are already PHI-clean.

## Why a separate venv?

PathLab's main `requirements.txt` is ~96 packages including `torch>=2.9`,
`segmentation_models_pytorch`, `Aslide`, `openslide-python`, `marker-pdf`,
`lancedb`, `transformers`, `timm` etc. — together ~5 GB.

Paper-gen needs none of those at runtime: it talks to PathLab via the
gateway (HTTP) and via the DB layer (which is pure SQLAlchemy). Keeping
the dev env minimal means:

- ~600 MB instead of ~5 GB
- 30 s install instead of 5–10 min
- Independent dep upgrades (e.g. bumping httpx for paper-gen doesn't
  require re-testing the WSI inference pipeline)
- CI for paper-gen can use this lockfile and skip GPU-related installs

In production (PyInstaller bundle) the paper-gen code runs inside the
same Python process as the rest of the sidecar, using the main
`requirements.txt`. This local venv is **dev-only**.

## Cross-imports — how `_pathlab_root.pth` works

`paper_generation` imports from `backend.*` (DB, common) and from
`gateway.routes.chat_llm_client` (shared LLM HTTP pool). Those modules
live in `server/`, two levels up from this folder. To make them importable
from this venv:

1. `_pathlab_root.py` is a tiny site-packages module that walks up from
   itself until it finds a directory containing both `backend/` and
   `gateway/`, then inserts that path at the front of `sys.path`.
2. `_pathlab_root.pth` contains the single line `import _pathlab_root`,
   which Python's `site.py` evaluates at startup, triggering the path
   insertion.

This is the same mechanism `pip install -e .` uses, just hand-rolled
because `backend/` doesn't have its own `pyproject.toml` to install
editable.

## Adding a dep

```bash
uv add 'somepackage>=1.0'           # runtime
uv add --group test 'pytest-x>=2'   # test only
uv add --group plotting '...'       # M6a plotting only
uv lock                             # refresh lockfile
```

## Running tests

```bash
uv run pytest tests/ -v
uv run pytest tests/test_routes.py::test_create_paper_run -v
```

(Tests directory will be created in M1 verification phase.)
