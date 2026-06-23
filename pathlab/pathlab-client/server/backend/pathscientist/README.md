# PathScientist Quick Start

PathScientist is the autonomous computational pathology research agent inside
PathLab. It turns a user goal such as "train a Gleason grading model" into a
staged workflow:

```text
prompt -> task grounding -> literature search -> dataset discovery/acquisition
       -> data readiness -> feature extraction -> MIL training -> review/synthesis
```

This README is the practical setup guide for developers and operators. For
deeper design notes, see `docs/architecture.md`, `docs/dataset_acquisition.md`,
and `docs/PROJECT_SUMMARY.md`.

This README also consolidates the operator-facing deployment quickstart and the
Apptainer sandbox reference. Developer workflows are in the earlier sections;
operators can jump to "Deployment Quickstart".

---

## 1. Repository Locations

From the git root:

```text
pathlab/pathlab-client/
  package.json                         # frontend/Electron dependencies
  deploy/start.sh                      # fixed-port web/backend launcher
  server/
    requirements.txt                   # Python backend + PathScientist deps
    requirements-test.txt              # pytest deps
    main.py                            # starts Gateway/Preprocessing/AI
    backend/pathscientist/             # this package
```

Important PathScientist subdirectories:

```text
pathscientist/
  start.sh                             # standalone CLI launcher
  run.py                               # batch entry: python -m pathscientist.run
  cli.py                               # interactive entry: python -m pathscientist
  config.py                            # PATHSCIENTIST_* env resolution
  orchestrator/                        # stage machine and execution planning
  dataset/                             # discovery/acquisition/readiness/labels
  literature/                          # local seed + online + RAG retrieval
  domain/templates/                    # generated execution templates
  domain/templates/common/extractors/  # feature extractor registry/checkpoints
  runtime/                             # sandbox, session, filesystem guards
  tests/                               # PathScientist pytest suite
```

Run git commands from the repository root, not from this directory:

```bash
cd /home/<service-user>/PathLab
```

---

## 2. Supported Developer Modes

Use one of these modes depending on the task.

| Mode | Use when | Entry |
|---|---|---|
| Full PathLab web app | Testing the frontend PathScientist UI and Gateway routes | `pathlab/pathlab-client/deploy/start.sh` then open `/pathscientist` |
| Standalone PathScientist CLI | Debugging orchestration, acquisition, RAG, execution planning | `server/backend/pathscientist/start.sh` |
| Unit tests | Reviewing/fixing isolated backend logic | `pytest` from `pathlab-client/server` or `server/backend/pathscientist` |
| Smoke/dry run | Testing grounding/acquisition without training | `PATHSCIENTIST_STOP_BEFORE_EXECUTION=1 ./start.sh -q ...` |

The web app and standalone CLI share the same core Python package, but their
defaults are not identical. `start.sh` in this directory applies developer
friendly PathScientist defaults, while the Gateway route applies its own web
session defaults in `server/gateway/routes/pathscientist.py`.

---

## 3. System Prerequisites

Minimum for backend/PathScientist development on Linux:

```bash
# Ubuntu/Debian style package names
sudo apt-get update
sudo apt-get install -y \
  build-essential git curl bash pkg-config \
  python3 python3-venv python3-pip \
  nodejs npm \
  redis-server postgresql postgresql-client \
  libopenslide-dev openslide-tools \
  libgl1 libglib2.0-0
```

Additional optional dependencies:

| Dependency | Needed for |
|---|---|
| CUDA + NVIDIA driver | Real feature extraction/training on GPU |
| Apptainer/Singularity | `PATHSCIENTIST_SANDBOX=auto|apptainer` execution isolation on HPC |
| Nginx | Production-style fixed-port deployment |
| Kaggle CLI | PANDA and other Kaggle datasets |
| Hugging Face access/token | Gated pathology foundation models |

For cluster development, prefer the site-provided CUDA/Apptainer modules rather
than installing system packages yourself.

---

## 4. Python Environment

PathScientist's standalone launcher expects a virtualenv at:

```text
pathlab/pathlab-client/server/backend/pathscientist/.venv
```

Recommended setup from this directory:

```bash
cd pathlab/pathlab-client/server/backend/pathscientist

# Option A: stdlib venv
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r ../../requirements.txt
python -m pip install -r ../../requirements-test.txt

# Optional: Kaggle CLI for PANDA/Kaggle downloads
python -m pip install kaggle
```

If your environment uses `uv`:

```bash
cd pathlab/pathlab-client/server/backend/pathscientist
uv venv .venv --python 3.12
uv pip install -r ../../requirements.txt
uv pip install -r ../../requirements-test.txt
uv pip install kaggle
```

Notes:

- `../../requirements.txt` is `pathlab/pathlab-client/server/requirements.txt`.
- It includes heavy ML packages, OpenHands SDK, LanceDB/RAG dependencies, and
  model/tooling dependencies used by PathLab backend code.
- `server/requirements-pdf-marker.txt` is optional. Do not install it into the
  main PathScientist/OpenHands environment unless you intentionally accept its
  OpenAI/Anthropic/Pillow pins for a dedicated PDF parsing worker.
- If this venv was created by `uv`, `python -m pip` may be unavailable. Use
  `uv pip install ...` from this directory, or run `python -m ensurepip --upgrade`
  before using `python -m pip`.
- For real feature extraction/training on GPU, install a CUDA-enabled Torch
  build matching the machine driver before the rest of the requirements. A CPU
  Torch build is enough for CLI, route, and acquisition tests, but not for H800
  feature extraction.
- `pip check` may report CONCH metadata conflicts (`timm`, `tokenizers`,
  `transformers`). This is a known upstream metadata issue for the optional
  CONCH extractor in the shared PathScientist environment; keep OpenHands and
  the default extractor stack on the modern versions and validate CONCH with
  extractor-specific smoke tests if you plan to use it.
- Do not commit `.venv/`; it is intentionally ignored.

Quick dependency sanity check:

```bash
cd pathlab/pathlab-client/server/backend
OPENHANDS_SUPPRESS_BANNER=1 pathscientist/.venv/bin/python - <<'PY'
import importlib
for mod in ["openhands.sdk", "openhands.tools", "fastapi", "torch", "kaggle"]:
    importlib.import_module(mod)
    print("OK", mod)
import torch
print("cuda", torch.cuda.is_available(), torch.version.cuda, torch.__version__)
PY
```

---

## 5. Frontend / Web App Setup

From `pathlab/pathlab-client`:

```bash
cd pathlab/pathlab-client
npm install
```

Production-like fixed-port startup:

```bash
cd pathlab/pathlab-client
./deploy/start.sh
```

This script:

1. cleans old services on ports `6100/6101/6102`,
2. ensures Redis is running,
3. installs Node dependencies if `node_modules/` is missing,
4. builds the frontend to `src/renderer/dist`,
5. starts `server/main.py`, which launches Gateway, Preprocessing, and AI.

After it starts, open:

```text
http://127.0.0.1:6100/pathscientist
```

Default local admin credentials are currently:

```text
username: admin
password: admin
```

For SSH tunneling from a local laptop to a cluster node, forward at least the
Gateway port. If you also run a Vite dev server, forward that port too:

```bash
ssh -N \
  -L 127.0.0.1:16100:<cluster-node-ip>:6100 \
  -L 127.0.0.1:15173:<cluster-node-ip>:5173 \
  <user>@<login-host>
```

Then visit `http://127.0.0.1:16100/pathscientist` for the built Gateway-served
frontend, or `http://127.0.0.1:15173/pathscientist` for a dev Vite frontend if
one is running.

---

## 6. Environment Files and Secrets

Never commit real secrets. Keep them in ignored files or shell environment.

### 6.1 PathLab backend env

PathLab backend reads:

```text
pathlab/pathlab-client/server/.env
```

Start from `pathlab/pathlab-client/.env.example` and configure at least:

```bash
DATABASE_URL=postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab
REDIS_URL=redis://localhost:6379/0
INTERNAL_API_KEY=change-me
JWT_SECRET=change-me
APP_SALT=change-me
DEFAULT_ADMIN_PASSWORD=admin
```

Optional but common:

```bash
HF_TOKEN=...                    # standalone/service fallback only; Web inherits PathLab Settings
PATHLAB_CKPT_DIR=/path/to/ckpts # durable model checkpoint cache
CUDA_VISIBLE_DEVICES=0,1        # GPU filtering
```

### 6.2 PathScientist local env

Normal Web sessions started from PathLab do not require separate
`PATHSCIENTIST_LLM_*` values. The Gateway inherits the PathLab global Settings
LLM/HF credentials (`openrouter_base_url`, `openrouter_api_key`,
`huggingface_token`), forwards the Hugging Face token as `HF_TOKEN`, and applies
the PathScientist runtime defaults (`gpt-5.5`, `codex-relay`, `responses`).

The standalone PathScientist launcher loads:

```text
pathlab/pathlab-client/server/backend/pathscientist/.env.local
```

Important limitation: the loader only accepts `PATHSCIENTIST_*` keys. Put
`KAGGLE_*`, `GDC_TOKEN`, etc. in your shell environment or backend `server/.env`,
not in this `.env.local`, unless the code is changed to load those prefixes.
For Web sessions, put the Hugging Face token in PathLab Settings; use `HF_TOKEN`
only as a standalone CLI/headless or service-environment fallback.

A safe standalone CLI `.env.local` template:

```bash
# Standalone CLI/headless only. Web sessions inherit PathLab Settings instead.
# PATHSCIENTIST_LLM_PROFILE=codex-relay
# PATHSCIENTIST_LLM_MODEL=gpt-5.5
# PATHSCIENTIST_LLM_WIRE_API=responses
# PATHSCIENTIST_LLM_BASE_URL=https://your-relay.example/v1
# PATHSCIENTIST_LLM_API_KEY=replace-with-local-secret

PATHSCIENTIST_BASE_DIR=/path/to/uploads/autoresearch
PATHSCIENTIST_DATASET_CACHE_DIR=/path/to/pathlab-data
PATHSCIENTIST_LITERATURE_ONLINE=1
PATHSCIENTIST_AUTO_ACQUIRE_DATA=1
PATHSCIENTIST_DOWNLOAD_POLICY=all
PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB=500
PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS=1
PATHSCIENTIST_GENERATE_PAPER_DRAFT=0
```

Lock down the file:

```bash
chmod 600 pathlab/pathlab-client/server/backend/pathscientist/.env.local
```

### 6.3 External service credentials

| Secret/env | Required for | Where to put |
|---|---|---|
| PathLab Settings `openrouter_api_key` | Web PathScientist LLM calls | PathLab Settings / database |
| PathLab Settings `openrouter_base_url` | Web PathScientist OpenAI-compatible relay endpoint | PathLab Settings / database |
| PathLab Settings `huggingface_token` | Web PathScientist gated Hugging Face model downloads | PathLab Settings / database |
| `PATHSCIENTIST_LLM_API_KEY` | Standalone CLI/headless LLM calls only | `pathscientist/.env.local` or shell |
| `PATHSCIENTIST_LLM_BASE_URL` | Standalone CLI/headless OpenAI-compatible relay endpoint only | `pathscientist/.env.local` or shell |
| `HF_TOKEN` | standalone CLI/headless or service fallback for gated Hugging Face downloads | shell or `server/.env` |
| `PATHLAB_CKPT_DIR` | durable local checkpoint directory | shell or `server/.env` |
| `KAGGLE_USERNAME` + `KAGGLE_KEY` | Kaggle CLI auth | shell |
| `KAGGLE_API_TOKEN` | modern Kaggle bearer token / KGAT token | shell |
| `KAGGLE_CONFIG_DIR` | location of `kaggle.json` | shell |
| `GDC_TOKEN` / `GDC_TOKEN_PATH` | controlled-access TCGA/GDC files | shell |
| `PATHSCIENTIST_RAG_EMBEDDING_*` | dense RAG embeddings | `pathscientist/.env.local` |

---

## 7. Database and Redis

For local development, create a PostgreSQL user/database matching
`DATABASE_URL`:

```bash
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='pathlab'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE pathlab LOGIN PASSWORD 'pathlab'"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='pathlab'" | grep -q 1 || \
  sudo -u postgres createdb -O pathlab pathlab
```

Verify connectivity with:

```bash
psql postgresql://pathlab:pathlab@localhost:5432/pathlab -c 'select 1;'
redis-cli ping
```

`server/main.py` initializes tables during Gateway startup. For test-only route
work, many tests mock DB/Redis and do not require a live database.

---

## 8. Standalone CLI Quick Start

From this directory:

```bash
cd pathlab/pathlab-client/server/backend/pathscientist
./start.sh
```

Batch mode:

```bash
./start.sh -q "Train a Gleason grading MIL model for prostate WSI"
```

Dry run through acquisition/pre-execution, without training:

```bash
PATHSCIENTIST_STOP_BEFORE_EXECUTION=1 \
./start.sh -q "Find or download PANDA and prepare a Gleason grading MIL task"
```

Disable automatic data acquisition:

```bash
PATHSCIENTIST_AUTO_ACQUIRE_DATA=0 \
./start.sh -q "Review literature for Gleason grading WSI MIL"
```

Force a fixed feature extractor:

```bash
PATHSCIENTIST_FEATURE_EXTRACTOR_MODE=fixed \
PATHSCIENTIST_FEATURE_EXTRACTOR=virchow2 \
./start.sh -q "Extract features from /path/to/Dataset/WSIs and train ABMIL"
```

Prefer local execution over Apptainer:

```bash
PATHSCIENTIST_SANDBOX=local ./start.sh -q "..."
```

The launcher changes directory to `server/backend` and runs either:

```bash
.venv/bin/python -m pathscientist          # interactive
.venv/bin/python -m pathscientist.run ...  # batch
```

---

## 9. Web UI Quick Start

1. Start backend/frontend build:

```bash
cd pathlab/pathlab-client
./deploy/start.sh
```

2. Open:

```text
http://127.0.0.1:6100/pathscientist
```

3. Start a new session with a prompt such as:

```text
I want to train a Gleason score grading model from WSI. I do not provide data.
Please research suitable datasets, avoid duplicate downloads if local data is
already available, prepare labels/splits, extract pathology foundation model
features, and then train a MIL classifier.
```

4. To test only pre-training functionality, use a prompt that explicitly stops
before execution:

```text
I want to train a Gleason score grading model from WSI. Do literature grounding,
dataset discovery, local data check, acquisition planning, label/split readiness,
and feature extractor/MIL selection, but stop before feature extraction or
training.
```

`PATHSCIENTIST_BASE_DIR` is the AutoResearch root. In the web app it defaults
to the Settings uploads directory plus `autoresearch`, for example
`<settings uploads>/autoresearch`. Session workspaces live under the dedicated
`autoresearch_sessions` subdirectory:

```text
<PATHSCIENTIST_BASE_DIR>/autoresearch_sessions/session_<id>/
  .dataset/
  .pathscientist/
  logs/

<PATHSCIENTIST_BASE_DIR>/conversations/<conversation_id>/
```

---

## 10. Dataset Cache Layout

`PATHSCIENTIST_DATASET_CACHE_DIR` is the unified durable data root. Acquisition
checks this root before downloading, and downloads should land here rather than
inside a throwaway workspace.

Preferred WSI dataset layout:

```text
<PATHSCIENTIST_DATASET_CACHE_DIR>/
  PANDA/
    WSIs/                         # raw slides
    labels.csv or train.csv
    splits.csv
    patches/                      # coordinates: <slide>_coords.h5
    pt_files/
      virchow2/                   # features: <slide>.pt
      uni2/
  TCGA-NSCLC/
    WSIs/                         # optional aggregate raw slides or symlinks
    labels.csv
    splits.csv
    patches/
    pt_files/
      virchow2/
  TCGA-LUAD/
    WSIs/
    pt_files/virchow2/
  TCGA-LUSC/
    WSIs/
    pt_files/virchow2/
```

Rules:

- If `pt_files/<extractor>/` is complete and labels/splits are present, the
  system can skip raw slide download and feature extraction.
- If raw slides exist under `WSIs/` but features are missing, the execution plan
  should schedule feature extraction.
- Coordinates belong in `patches/`, not under `pt_files/`.
- Feature outputs should be durable under the dataset root so future sessions
  can reuse them.

---

## 11. Dataset Download Providers

See `docs/dataset_acquisition.md` for full details. Current practical matrix:

| Provider | What works | Credential |
|---|---|---|
| `direct_http` | direct file URLs such as zip/tar/h5 | none |
| `zenodo` | resolvable record/file URLs | none |
| `huggingface` | `snapshot_download` datasets/models | optional `HF_TOKEN` |
| `kaggle` | competitions/datasets via Kaggle CLI, including PANDA | `KAGGLE_USERNAME`+`KAGGLE_KEY`, `KAGGLE_API_TOKEN`, or `kaggle.json` |
| `scidb` | SciDB detail/download file URLs | none for public datasets |
| `gdc` / `tcia` | TCGA project ids, GDC manifests, explicit GDC file URLs | optional `GDC_TOKEN` for controlled access |

### PANDA / Kaggle test

Pre-flight:

```bash
python -m pip install kaggle
export KAGGLE_USERNAME=...
export KAGGLE_KEY=...
# or:
export KAGGLE_API_TOKEN=KGAT_...
```

Prompt:

```bash
PATHSCIENTIST_AUTO_ACQUIRE_DATA=1 \
PATHSCIENTIST_DOWNLOAD_POLICY=manual_only \
PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB=500 \
PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS=1 \
./start.sh -q "I want to train a Gleason score grading model from WSI. Find or download PANDA if needed, organize labels and splits, then stop before training." \
  --stop-before-execution
```

### TCGA / GDC test

Public/open GDC slide files do not require a token. Controlled-access files do.

```bash
export GDC_TOKEN_PATH=/path/to/gdc-user-token.txt
# or export GDC_TOKEN=...

PATHSCIENTIST_AUTO_ACQUIRE_DATA=1 \
PATHSCIENTIST_DOWNLOAD_POLICY=all \
PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB=1000 \
PATHSCIENTIST_ALLOW_LARGE_DOWNLOADS=1 \
./start.sh -q "Download TCGA-LUAD and TCGA-LUSC diagnostic slide images for an NSCLC subtype MIL task and prepare project-subtype labels." \
  --stop-before-execution
```

---

## 12. Literature Search and RAG

Default literature grounding uses:

- local curated seed papers,
- online metadata search providers (`openalex,europepmc,semantic_scholar,pubmed`),
- optional RAG over local papers.

Online literature search is enabled by `start.sh` unless overridden:

```bash
PATHSCIENTIST_LITERATURE_ONLINE=1
PATHSCIENTIST_LITERATURE_ONLINE_MAX_RESULTS=10
PATHSCIENTIST_LITERATURE_ONLINE_TIMEOUT=15
```

Disable online search:

```bash
PATHSCIENTIST_LITERATURE_ONLINE=0 ./start.sh -q "..."
```

Build RAG from seed data only:

```bash
cd pathlab/pathlab-client/server/backend
pathscientist/.venv/bin/python -m pathscientist.rag_ingest --from-seed-data
```

Build RAG from local papers:

```bash
cd pathlab/pathlab-client/server/backend
PATHSCIENTIST_BASE_DIR=/path/to/uploads/autoresearch \
pathscientist/.venv/bin/python -m pathscientist.rag_ingest \
  --from-seed-data \
  --corpus-dir /path/to/papers
```

Check RAG status:

```bash
pathscientist/.venv/bin/python -m pathscientist.rag_ingest --status
```

Run with RAG:

```bash
cd pathlab/pathlab-client/server/backend/pathscientist
PATHSCIENTIST_RAG=1 ./start.sh -q "Review SOTA for Gleason grading WSI MIL"
```

RAG dense embeddings default to an OpenAI-compatible endpoint. Override if your
cluster does not expose the default endpoint:

```bash
PATHSCIENTIST_RAG_EMBEDDING_MODEL=...
PATHSCIENTIST_RAG_EMBEDDING_BASE_URL=http://host:port/v1
PATHSCIENTIST_RAG_EMBEDDING_API_KEY=...
```

---

## 13. Feature Extraction and Model Checkpoints

Feature extraction uses PathLab's extractor registry under:

```text
domain/templates/common/extractors/
```

Supported extractor names include:

```text
resnet50, vit_l_16, uni, uni2, conch, conch15, virchow, virchow2,
plip, phikon, phikon2, patho_clip, openmidnight, H-Optimus-1,
H-Optimus-0, mSTAR, GPFM, SmartCCS, SmartCyto, CytoFM
```

Checkpoint resolution order:

1. `PATHLAB_CKPT_DIR/<ExtractorName>/...`, if `PATHLAB_CKPT_DIR` is set.
2. local extractor checkpoint directory under this package.
3. Hugging Face cache under `HUGGINGFACE_HUB_CACHE` or `HF_HOME`.
4. Hugging Face download, if online and allowed.

Important gated/local cases:

| Extractor | Checkpoint behavior |
|---|---|
| `uni`, `uni2`, `conch`, `conch15`, `virchow`, `virchow2` | may require Hugging Face access/token depending on repo access |
| `H-Optimus-1`, `H-Optimus-0`, `Phikon`, `PLIP` | downloaded as model directories |
| `SmartCCS` | requires local `SmartCCS/CCS_vitl_100M.pth` |
| `SmartCyto` | requires local `SmartCyto/smartcyto_vl.pt` and may need compatible `timm` |
| `CytoFM` | requires local `CytoFM/vitl-16-cytofm-v1.pth` |

Recommended durable checkpoint root:

```bash
export PATHLAB_CKPT_DIR=/path/to/pathlab-checkpoints
export HF_HOME=/path/to/huggingface-cache
# Web sessions inherit PathLab Settings huggingface_token.
# Standalone CLI/headless fallback:
# export HF_TOKEN=...
```

Feature extraction output convention:

```text
<dataset_root>/patches/<slide_id>_coords.h5
<dataset_root>/pt_files/<extractor>/<slide_id>.pt
```

The current default execution path is conservative: one feature extraction
process unless explicitly configured otherwise. This avoids multiple workers
racing on the same slide/output path.

---

## 14. Common Prompts

Pre-training dry run for Gleason/PANDA:

```text
I want to train a Gleason score grading model from WSI. I do not provide data.
Research the literature, infer the organ/task, find suitable public or manual
datasets, check the configured local data root before downloading, prepare a
readiness plan with labels/splits/features, choose the feature extractor and
MIL model from evidence, and stop before actual feature extraction/training.
```

Full local-data feature extraction + MIL smoke test:

```text
Use the dataset at /path/to/Dataset. It has WSIs and labels. Create a 5-slide
subset for smoke testing. Extract virchow2 features into the dataset's pt_files
layout, save coordinates under patches, then train a small MIL classifier just
to verify the end-to-end pipeline runs.
```

TCGA NSCLC acquisition/label setup:

```text
I want an NSCLC subtype classification task using TCGA-LUAD and TCGA-LUSC WSI.
Check local data and existing virchow2 features first. If missing, acquire the
GDC slide images. Generate project-subtype labels and grouped splits. Stop
before training.
```

Dataset-only download test:

```text
Download and organize the PANDA prostate cancer grading dataset if it is not
already present in the configured data root. Create the training labels/splits
and report the prepared dataset paths. Do not train.
```

---

## 15. Tests and Verification

From `pathlab/pathlab-client/server`:

```bash
cd pathlab/pathlab-client/server
OPENHANDS_SUPPRESS_BANNER=1 backend/pathscientist/.venv/bin/python -m pytest \
  tests/test_pathscientist_process_registry.py \
  tests/test_pathscientist_routes.py \
  backend/pathscientist/tests/test_dataset_providers_kaggle.py \
  backend/pathscientist/tests/test_dataset_providers_gdc.py \
  -q
```

From `pathlab/pathlab-client/server/backend/pathscientist`:

```bash
cd pathlab/pathlab-client/server/backend/pathscientist
.venv/bin/python -m pytest tests -q
```

Focused useful tests:

```bash
.venv/bin/python -m pytest tests/test_dataset_acquisition_gleason_panda.py -q
.venv/bin/python -m pytest tests/test_literature_grounding.py -q
.venv/bin/python -m pytest tests/test_wsi_artifact_layout_conventions.py -q
.venv/bin/python -m pytest tests/test_feature_extraction_worker_template.py -q
.venv/bin/python -m pytest tests/test_extractor_checkpoint_resolution.py -q
```

Frontend tests live at `pathlab/pathlab-client/test` and run through Vitest:

```bash
cd pathlab/pathlab-client
npm run test:run
```

Known practical note: Vitest can hang in some cluster/headless environments.
If it does, record the command and environment instead of claiming frontend
tests passed.

---

## 16. Runtime Artifacts

Do not commit generated artifacts. Important ignored paths include:

```text
pathscientist/.venv/
pathscientist/.env.local
pathscientist/output/
pathscientist/sota_cache.json
pathlab/pathlab-client/logs/
pathlab/pathlab-client/server/.env
pathlab/pathlab-client/server/uploads/
*.sif
kaggle.json
*.token
```

Useful runtime files for debugging a session:

```text
<PATHSCIENTIST_BASE_DIR>/autoresearch_sessions/session_<id>/.dataset/acquisition_plan.json
<PATHSCIENTIST_BASE_DIR>/autoresearch_sessions/session_<id>/.dataset/local_discovery.json
<PATHSCIENTIST_BASE_DIR>/autoresearch_sessions/session_<id>/.dataset/manifest.json
<PATHSCIENTIST_BASE_DIR>/autoresearch_sessions/session_<id>/.dataset/download_progress.json
<PATHSCIENTIST_BASE_DIR>/autoresearch_sessions/session_<id>/.pathscientist/execution_brief.md
<PATHSCIENTIST_BASE_DIR>/autoresearch_sessions/session_<id>/logs/completions/
<PATHSCIENTIST_BASE_DIR>/conversations/<conversation_id>/base_state.json
```

Gateway/web session registries and event logs are also under the resolved
PathScientist base directory.

Web PathScientist sessions also best-effort sync structured metadata into the
existing PostgreSQL `auto_research_*` tables:

```text
auto_research_sessions     # session owner, question, stage/status, best metric, summaries, recovery pointers
auto_research_experiments  # per-run run_id, metrics, compact config/path metadata
auto_research_events       # replay/audit events keyed by session_id + sequence
```

For web sessions, `auto_research_sessions` stores recovery pointers such as
`conversation_id`, `persistence_dir`, `workspace_path`, `resume_available`,
`event_source_version`, and compact `recovery_metadata`. `auto_research_events`
has a unique `(session_id, sequence)` key so Gateway event replay can be written
idempotently.

The database is an index, replay, and metadata layer. The authoritative
PathScientist/OpenHands conversation still lives on disk: `base_state.json`,
OpenHands event files, terminal/tool output, workspace files, reusable
datasets/features, and model/run artifacts stay under `PATHSCIENTIST_BASE_DIR`
or `PATHSCIENTIST_DATASET_CACHE_DIR`. PostgreSQL stores paths and compact
summaries rather than copying those artifacts into JSON fields.

---

## 17. Troubleshooting

### `Python venv not found at .../.venv`

Create the local venv and install requirements:

```bash
cd pathlab/pathlab-client/server/backend/pathscientist
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r ../../requirements.txt -r ../../requirements-test.txt
```

### `No LLM model configured` or skill/model selection fails

For Web sessions, check PathLab global Settings first. PathScientist inherits
`openrouter_base_url` and `openrouter_api_key` through the Gateway, then applies
its own model/profile defaults.

For standalone CLI/headless runs, check:

```bash
env | grep '^PATHSCIENTIST_LLM_'
cat pathlab/pathlab-client/server/backend/pathscientist/.env.local
```

In standalone relay usage, `PATHSCIENTIST_LLM_MODEL`,
`PATHSCIENTIST_LLM_BASE_URL`, and `PATHSCIENTIST_LLM_API_KEY` must resolve.
`PATHSCIENTIST_LLM_PROFILE` defaults to `codex-relay` in `start.sh`.

### Kaggle says credentials are missing

Use one of:

```bash
export KAGGLE_USERNAME=...
export KAGGLE_KEY=...
```

or:

```bash
mkdir -p ~/.kaggle
chmod 700 ~/.kaggle
cp /path/to/kaggle.json ~/.kaggle/kaggle.json
chmod 600 ~/.kaggle/kaggle.json
```

or:

```bash
export KAGGLE_API_TOKEN=KGAT_...
```

Remember: `pathscientist/.env.local` does not load `KAGGLE_*` keys.

### GDC/TCGA controlled files fail

Public diagnostic slide files may work without a token. Controlled-access files
need:

```bash
export GDC_TOKEN_PATH=/path/to/gdc-user-token.txt
# or export GDC_TOKEN=...
```

### Feature extractor checkpoint not found

Set a durable checkpoint/cache location and make sure the expected files exist:

```bash
export PATHLAB_CKPT_DIR=/path/to/pathlab-checkpoints
export HF_HOME=/path/to/hf-cache
# Web sessions inherit PathLab Settings huggingface_token.
# Standalone CLI/headless fallback:
# export HF_TOKEN=...
```

For local-only extractors, place files exactly as requested by the error, e.g.:

```text
$PATHLAB_CKPT_DIR/SmartCCS/CCS_vitl_100M.pth
$PATHLAB_CKPT_DIR/SmartCyto/smartcyto_vl.pt
$PATHLAB_CKPT_DIR/CytoFM/vitl-16-cytofm-v1.pth
```

### Backend starts but the page is blank or stale

Rebuild frontend and restart fixed-port services:

```bash
cd pathlab/pathlab-client
./deploy/hot-reload.sh frontend
./deploy/hot-reload.sh backend
```

or run the full launcher:

```bash
./deploy/start.sh
```

### Session uses wrong data path

Check these values in the backend process environment:

```bash
env | grep '^PATHSCIENTIST_\|^PATHLAB_CKPT_DIR\|^HF_HOME'
```

The durable data root should be `PATHSCIENTIST_DATASET_CACHE_DIR`. New dataset
features should land under:

```text
<dataset_root>/pt_files/<extractor>/
<dataset_root>/patches/
```

### Agent downloads data even though features already exist

Verify all three are present and readable:

```text
labels/splits file
pt_files/<selected_extractor>/*.pt
manifest/readiness evidence in .dataset/
```

If the selected extractor is `virchow2`, existing `pt_files/uni2` does not
count as complete for this run.

---

## 18. Deployment Quickstart

This is the operator-facing quickstart for deploying PathScientist as part of
the PathLab web app on a new Linux server. Setup steps (system packages,
Python venv, PostgreSQL/Redis, frontend deps, LLM/HF settings, dataset
layout) are covered in the developer sections above; this section focuses on
the deployment-specific flow and references those sections as needed.

### 18.1 What You Are Deploying

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

### 18.2 Code Checkout

```bash
git clone <repo-url> /home/<service-user>/PathLab
cd /home/<service-user>/PathLab
git checkout pathscientistv0.1.1dev
cd pathlab/pathlab-client
```

Run git commands from `/home/<service-user>/PathLab`; run web deployment
commands from `/home/<service-user>/PathLab/pathlab/pathlab-client`.

### 18.3 Server Environment

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

### 18.4 Start The Web App

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

### 18.5 SSH Tunnel For Remote Testing

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

### 18.6 Smoke Test

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

### 18.7 Operations Commands

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

### 18.8 Do Not Commit

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

### 18.9 Deployment Troubleshooting

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

---

## 19. Apptainer Sandbox Reference

This section records the portable PathScientist runtime setup used on
`jhcpu5.cse.ust.hk`. The backend still runs on the host Python environment.
The Apptainer image is only used for generated training, feature extraction,
and external-test scripts.

### 19.1 Files

- Definition file: `server/backend/pathscientist/runtime/containers/pathlab-sandbox.def`
- jhcpu5 active image path: `.local/pathscientist/sandbox/pathlab-sandbox.sif`
- Directory sandbox fallback path: `.local/pathscientist/sandbox/pathlab-sandbox`
- PathScientist sandbox config file: `server/backend/pathscientist/.env.local` or the service environment
- Runtime selector: `server/backend/pathscientist/runtime/sandbox.py`

### 19.2 Build On A New Server

Install Apptainer first, then build from the repo root:

```bash
cd /home/<service-user>/PathLab/pathlab/pathlab-client
mkdir -p .local/pathscientist/sandbox
APPTAINER_TMPDIR=/tmp apptainer build --fakeroot --force \
  .local/pathscientist/sandbox/pathlab-sandbox.sif \
  server/backend/pathscientist/runtime/containers/pathlab-sandbox.def
```

If `/tmp` is small, set `APPTAINER_TMPDIR` to a large local disk:

```bash
mkdir -p /home/<service-user>/.apptainer-tmp
APPTAINER_TMPDIR=/home/<service-user>/.apptainer-tmp apptainer build --fakeroot --force \
  .local/pathscientist/sandbox/pathlab-sandbox.sif \
  server/backend/pathscientist/runtime/containers/pathlab-sandbox.def
```

### 19.3 SIF And Directory Sandbox

Apptainer supports both immutable `.sif` files and directory sandbox images. On
`jhcpu5`, the full dependency build and `%test` passed, but the first SIF
compression failed in `mksquashfs` with exit 139. A later attempt to compress
the working directory sandbox also failed because fakeroot left a root-owned
apt cache subdirectory and an extra `--mksquashfs-args -no-progress` conflicted
with Apptainer's built-in progress flag.

The fix was:

1. Remove/recreate the unreadable apt cache directory inside the directory sandbox.
2. Set Apptainer mksquashfs compression to one processor and 4G memory in
   `/etc/apptainer/apptainer.conf`.
3. Repack the directory sandbox without extra `--mksquashfs-args`.

Current active runtime uses the SIF image:

```bash
PATHSCIENTIST_SANDBOX_IMAGE=/home/<service-user>/PathLab/pathlab/pathlab-client/.local/pathscientist/sandbox/pathlab-sandbox.sif
```

Keep the directory sandbox as a rebuild fallback:

```bash
APPTAINER_TMPDIR=/home/<service-user>/.apptainer-tmp apptainer build --fakeroot --sandbox --force \
  .local/pathscientist/sandbox/pathlab-sandbox \
  server/backend/pathscientist/runtime/containers/pathlab-sandbox.def
```

If SIF compression works on a target server, use the `.sif` command above. If
it fails at `mksquashfs`, use the directory sandbox and point
`PATHSCIENTIST_SANDBOX_IMAGE` to that directory. The directory sandbox is
larger and mutable, but PathScientist still runs scripts with
`apptainer exec --writable-tmpfs`, so normal session writes stay ephemeral
unless an explicit bind mount is writable.

### 19.4 Configure PathScientist

Add these values to `server/backend/pathscientist/.env.local`:

```bash
PATHSCIENTIST_SANDBOX=auto
PATHSCIENTIST_SANDBOX_IMAGE=/absolute/path/to/pathlab-client/.local/pathscientist/sandbox/pathlab-sandbox.sif
PATHSCIENTIST_SANDBOX_CGROUPS=0
```

`auto` means PathScientist will use Apptainer when both the binary and image
are available, and otherwise fall back to local execution. Use
`PATHSCIENTIST_SANDBOX=apptainer` when you want missing sandbox setup to fail
loudly.

`PATHSCIENTIST_SANDBOX_CGROUPS=0` disables Apptainer `--memory/--cpus` flags.
Keep it on jhcpu5 because its user.slice cgroup rejects those limits at
runtime. On a cluster where cgroup limits work, remove the variable or set it
to `auto`.

`runtime/sandbox.py` resolves the Apptainer binary in this order:

1. `APPTAINER_BIN`
2. `apptainer` found on `PATH`
3. Legacy cluster path `/cm/local/apps/apptainer/current/bin/apptainer`

### 19.5 Verify

Run these checks after building:

```bash
apptainer exec --nv .local/pathscientist/sandbox/pathlab-sandbox \
  python -c "import torch; print(torch.__version__); print(torch.cuda.is_available(), torch.cuda.device_count())"

PYTHONPATH=server/backend PATHSCIENTIST_SANDBOX_IMAGE=$PWD/.local/pathscientist/sandbox/pathlab-sandbox \
  server/backend/pathscientist/.venv/bin/python - <<'PY'
from pathscientist.runtime.sandbox import ApptainerSandbox
print(ApptainerSandbox.check_available())
PY
```

Expected results:

- The first command imports Torch and reports whether GPUs are visible inside the container.
- The second command prints `True`.

### 19.6 Runtime Mounts

PathScientist binds the following into the container:

- Session workspace: read/write, same absolute path inside the container
- Session output directory: read/write, same absolute path inside the container
- Prepared dataset mounts from acquisition, usually host dataset view to `/data/...`
- Existing host roots `/project`, `/tmp`, and `/data` when present
- Template `common/` utilities to `<workspace>/common:ro`
- Existing model caches under `~/.cache/torch`, `HF_HOME` or `~/.cache/huggingface`
- Kaggle config directory as `/kaggle:ro` when configured

This is why local execution can fail on `/data/...` paths while Apptainer
execution works: `/data/...` is a container contract path backed by explicit
binds.

### 19.7 Migration Checklist

1. Install Apptainer and confirm `apptainer --version` works for the service user.
2. Confirm the service user has fakeroot mappings in `/etc/subuid` and `/etc/subgid`, or build the SIF as root/admin once.
3. Build `pathlab-sandbox.sif` from `pathlab-sandbox.def`.
4. Copy or recreate `.env.local` values for sandbox settings. Web LLM and Hugging Face credentials come from PathLab Settings; copy `PATHSCIENTIST_LLM_*` or set `HF_TOKEN` only for standalone CLI/headless fallback. Put Kaggle credentials in `server/.env` or the service environment.
5. Restart the backend process so `PATHSCIENTIST_SANDBOX_IMAGE` is loaded.
6. Run the two verification commands above.
7. Start a small PathScientist session and confirm logs show `[apptainer] python ...` instead of local `python ...`.

### 19.8 Common Failures

- `check_available()` is `False`: image path does not exist, Apptainer is not on `PATH`, or `APPTAINER_BIN` points to a stale binary.
- `while setting cgroup limits ... cpu.max`: set `PATHSCIENTIST_SANDBOX_CGROUPS=0` and restart the backend.
- `127.0.0.1 refused to connect`: backend process is down; restart backend before testing the frontend.
- `/data/...` missing in a session log: the run is using local execution or the prepared dataset mount was not passed into the sandbox.
- `torch.cuda.is_available() == False`: retry with `apptainer exec --nv`; if still false, check NVIDIA driver/container integration on the host.
- `ModuleNotFoundError` inside training scripts: add the runtime dependency to `pathlab-sandbox.def`, rebuild the SIF or directory sandbox, and restart backend.
- SIF build from a directory sandbox reports permission errors under `var/cache/apt/archives/partial`: rebuild directly from `pathlab-sandbox.def`, or clean/chown that directory as an administrator before repacking.
- SIF compression crashes with `mksquashfs exit status 134` or `malloc(): corrupted top size`: reduce `/etc/apptainer/apptainer.conf` to `mksquashfs procs = 1` and `mksquashfs mem = 4G`, then rebuild without extra `--mksquashfs-args`.

---

## 20. What To Update When You Change PathScientist

When changing behavior, update the nearest operational doc:

| Change type | Update |
|---|---|
| stage/control flow | `docs/architecture.md` |
| dataset provider/acquisition | `docs/dataset_acquisition.md` |
| new env var/default | this README + `start.sh` comments |
| feature extractor/checkpoint behavior | this README + extractor docs/tests |
| frontend PathScientist UI | frontend README if user-facing |
| known limitation | this README troubleshooting or `docs/PROJECT_MEMORY.md` |

Before commit, run at least:

```bash
cd /home/<service-user>/PathLab
git diff --check

cd pathlab/pathlab-client/server
OPENHANDS_SUPPRESS_BANNER=1 backend/pathscientist/.venv/bin/python -m pytest \
  tests/test_pathscientist_process_registry.py \
  tests/test_pathscientist_routes.py \
  backend/pathscientist/tests/test_dataset_providers_kaggle.py \
  backend/pathscientist/tests/test_dataset_providers_gdc.py \
  -q
```
