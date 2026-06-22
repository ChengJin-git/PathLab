# PathScientist Quick Start

PathScientist is the autonomous computational pathology research agent inside
PathLab. It turns a user goal such as "train a Gleason grading model" into a
staged workflow:

```text
prompt -> task grounding -> literature search -> dataset discovery/acquisition
       -> data readiness -> feature extraction -> MIL training -> review/synthesis
```

This README is the practical setup guide for developers. For deeper design
notes, see `docs/architecture.md`, `docs/dataset_acquisition.md`, and
`docs/PROJECT_SUMMARY.md`.

For a deployment-server handoff, start with
`../../../docs/pathscientist-deployment-quickstart.md`. This README is longer
and includes developer workflows that are not required for a production-style
PathLab web deployment.

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
HF_TOKEN=...                    # gated HF models, if needed
PATHLAB_CKPT_DIR=/path/to/ckpts # durable model checkpoint cache
CUDA_VISIBLE_DEVICES=0,1        # GPU filtering
```

### 6.2 PathScientist local env

The standalone PathScientist launcher loads:

```text
pathlab/pathlab-client/server/backend/pathscientist/.env.local
```

Important limitation: the loader only accepts `PATHSCIENTIST_*` keys. Put
`HF_TOKEN`, `KAGGLE_*`, `GDC_TOKEN`, etc. in your shell environment or backend
`server/.env`, not in this `.env.local`, unless the code is changed to load
those prefixes.

A safe `.env.local` template:

```bash
PATHSCIENTIST_LLM_PROFILE=codex-relay
PATHSCIENTIST_LLM_MODEL=gpt-5.5
PATHSCIENTIST_LLM_WIRE_API=responses
PATHSCIENTIST_LLM_BASE_URL=https://your-relay.example/v1
PATHSCIENTIST_LLM_API_KEY=replace-with-local-secret

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
| `PATHSCIENTIST_LLM_API_KEY` | LLM helper calls and skill/model selection when not using existing Codex config | `pathscientist/.env.local` |
| `PATHSCIENTIST_LLM_BASE_URL` | OpenAI-compatible relay endpoint | `pathscientist/.env.local` |
| `HF_TOKEN` | gated Hugging Face model downloads | shell or `server/.env` |
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
export HF_TOKEN=...
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

Check:

```bash
env | grep '^PATHSCIENTIST_LLM_'
cat pathlab/pathlab-client/server/backend/pathscientist/.env.local
```

For relay usage, `PATHSCIENTIST_LLM_MODEL`, `PATHSCIENTIST_LLM_BASE_URL`, and
`PATHSCIENTIST_LLM_API_KEY` must resolve. `PATHSCIENTIST_LLM_PROFILE` defaults
to `codex-relay` in `start.sh`.

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
export HF_TOKEN=...
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

## 18. What To Update When You Change PathScientist

When changing behavior, update the nearest operational doc:

| Change type | Update |
|---|---|
| stage/control flow | `docs/architecture.md` |
| dataset provider/acquisition | `docs/dataset_acquisition.md` |
| new env var/default | this README + `start.sh` comments |
| feature extractor/checkpoint behavior | this README + extractor docs/tests |
| frontend PathScientist UI | `pathlab/pathlab-client/docs/plans/` or frontend README if user-facing |
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
