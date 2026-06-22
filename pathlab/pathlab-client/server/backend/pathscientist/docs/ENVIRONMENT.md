# PathScientist — Environment Configuration & Migration Guide

> Living reference for setting up, configuring, and **migrating** the PathScientist runtime environment.
> Companion to: `README.md` (quick start) and `docs/plan/2026-06-17-pathscientist-sandbox-migration-runbook.md`
> (the detailed apptainer build). This doc is the single place that answers *"what makes PathScientist run, and what
> do I carry to a new machine?"*
> Paths relative to `server/backend/pathscientist/` unless noted; `<client>` = `pathlab/pathlab-client`.

## 0. The environment in one picture

PathScientist needs **six** things wired together:

| # | Component | What it is | Portable? |
|---|---|---|---|
| 1 | **Code** | the repo on the active branch | git (carry) |
| 2 | **Python venv** | uv venv, py3.12, torch(cuXXX) + OpenHands SDK + ML stack | **rebuild per host** (CUDA-specific) |
| 3 | **LLM endpoint** | `.env.local` → `PATHSCIENTIST_LLM_*` (relay/model/key) | copy `.env.local` (secret) |
| 4 | **Sandbox** | apptainer binary + `pathlab-sandbox.sif` image | **rebuild per host** (or copy sif if same arch) |
| 5 | **Env config** | `PATHSCIENTIST_*` vars (`start.sh` defaults + `.env.local`) | mix: defaults travel, paths/secrets reconfigure |
| 6 | **Data roots** | dataset cache, model checkpoints, base/workspace dir | copy/re-point (large) |

## 1. Current reference environment (jhcpu5, `pathscientistv0.1.1dev`)

| Thing | Value |
|---|---|
| Host / GPUs | `jhcpu5` · 7× NVIDIA RTX 3090 |
| OS | Ubuntu 22.04.5, kernel 5.15 |
| Branch | `pathscientistv0.1.1dev` |
| Python venv | **uv, Python 3.12.13, torch 2.12.0+cu130** *(currently **MISSING** — see §7.1, rebuild it)* |
| Apptainer | `1.5.1` at `/usr/bin/apptainer` *(resolved via `shutil.which`, see §4)* |
| Sandbox image | `server/backend/auto_research_old/pathlab-sandbox.sif` (built); wired via `.env.local` `PATHSCIENTIST_SANDBOX_IMAGE` |
| LLM | `gpt-5.5` via `codex-relay`, `https://relay.1hui.wang/v1`, wire `responses` |
| Base dir (workspaces) | `<client>/uploads/pathscientist` (start.sh default) |
| Dataset cache | `/project/llmponco/wangyihui/original_data/pathlab_test_data` |
| Web ports | `6100/6101/6102` (gateway / preprocessing / AI) |

## 2. Setup from scratch (or after a migration)

### 2.1 Code
```bash
git clone <repo> ~/PathLab && cd ~/PathLab
git checkout pathscientistv0.1.1dev
```

### 2.2 Python venv  ⚠️ (this is what's missing right now)
The standalone launcher hard-requires `server/backend/pathscientist/.venv`. **torch must match the host's CUDA** —
do not copy a venv across machines.
```bash
cd ~/PathLab/pathlab/pathlab-client/server/backend/pathscientist
uv venv .venv --python 3.12
uv pip install -r ../../requirements.txt          # OpenHands SDK + ML stack
# GPU torch matching the host driver (jhcpu5 ⇒ cu130; pick the index for your CUDA):
uv pip install torch==2.12.0 torchvision --index-url https://download.pytorch.org/whl/cu130
uv pip install kaggle                              # optional, for Kaggle/PANDA
```
Sanity:
```bash
.venv/bin/python -c "import torch, openhands.sdk; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.device_count())"
```
> `requirements.txt` pins `torch>=2.9` and `openhands-sdk @ git+…@<commit>`; the GPU build must be installed from the
> matching CUDA wheel index (the bare requirement resolves to a CPU build otherwise).

### 2.3 LLM config — `.env.local`
The loader **only reads `PATHSCIENTIST_*` keys** from `.env.local`. Put non-`PATHSCIENTIST_` secrets
(`HF_TOKEN`, `KAGGLE_*`, `GDC_TOKEN`) in the **shell env** or `server/.env`, not here.
```bash
# server/backend/pathscientist/.env.local   (chmod 600; MUST be git-ignored — see §7.4)
PATHSCIENTIST_LLM_PROFILE=codex-relay
PATHSCIENTIST_LLM_MODEL=gpt-5.5
PATHSCIENTIST_LLM_WIRE_API=responses
PATHSCIENTIST_LLM_BASE_URL=https://relay.1hui.wang/v1
PATHSCIENTIST_LLM_API_KEY=<secret>
# sandbox (see §2.4)
PATHSCIENTIST_SANDBOX=auto
PATHSCIENTIST_SANDBOX_IMAGE=/abs/path/to/pathlab-sandbox.sif
PATHSCIENTIST_SANDBOX_CGROUPS=auto
```

### 2.4 Sandbox (apptainer + image)
Full build steps: `docs/plan/2026-06-17-pathscientist-sandbox-migration-runbook.md`. Summary:
- **Binary:** any apptainer on `PATH` is now auto-found — `sandbox.py:_resolve_apptainer_bin()` resolves
  `env APPTAINER_BIN → shutil.which("apptainer") → /cm/local/...`. On jhcpu5 it picks `/usr/bin/apptainer` (1.5.1).
- **Image:** build once with `apptainer build --fakeroot pathlab-sandbox.sif pathlab-sandbox.def` (subuid/subgid +
  rootless userns required — present on jhcpu5). Place at `server/backend/auto_research_old/pathlab-sandbox.sif` (the
  default the code probes) **or** point `PATHSCIENTIST_SANDBOX_IMAGE` at it (already done in `.env.local`).
- **Engage:** `PATHSCIENTIST_SANDBOX=auto` uses the sandbox iff `ApptainerSandbox.check_available()` (binary runs **and**
  image exists). Verify:
  ```bash
  .venv/bin/python -c "import sys; sys.path.insert(0,'..'); from pathscientist.runtime.sandbox import ApptainerSandbox as A; print('available:', A.check_available())"
  ```
  A real run should log `[sandbox] apptainer exec …` (not local). If it logs local, the sandbox isn't engaging — check
  the binary + image.

### 2.5 Data roots (large; re-point per host)
```bash
export PATHSCIENTIST_DATASET_CACHE_DIR=/path/to/pathlab-data     # durable data root (checked before download)
export PATHLAB_CKPT_DIR=/path/to/pathlab-checkpoints             # extractor checkpoints
export HF_HOME=/path/to/hf-cache; export HF_TOKEN=...            # gated HF models
# base/workspace dir defaults to <client>/uploads/pathscientist; override with PATHSCIENTIST_BASE_DIR
```

### 2.6 Run
```bash
# Standalone CLI (debug orchestration/acquisition/execution):
cd ~/PathLab/pathlab/pathlab-client/server/backend/pathscientist && ./start.sh -q "Train a Gleason MIL model"
# Web app (gateway on :6100):
cd ~/PathLab/pathlab/pathlab-client && ./deploy/start.sh        # then open http://127.0.0.1:6100/pathscientist
```

## 3. Environment variable reference (current `start.sh` defaults)

| Variable | Default | Purpose |
|---|---|---|
| `PATHSCIENTIST_LLM_{PROFILE,MODEL,WIRE_API,BASE_URL,API_KEY}` | codex-relay / gpt-5.5 / responses / relay.1hui.wang | LLM endpoint (the only required secrets) |
| `PATHSCIENTIST_SANDBOX` | `auto` | `auto`\|`apptainer`\|`local` (auto ⇒ apptainer if available, else local) |
| `PATHSCIENTIST_SANDBOX_IMAGE` | — | abs path to the `.sif` (else the `auto_research_old/` default) |
| `APPTAINER_BIN` | (auto via `which`) | override the apptainer binary path |
| `PATHSCIENTIST_BASE_DIR` | `<client>/uploads/pathscientist` | session workspaces / output / persistence |
| `PATHSCIENTIST_DATASET_CACHE_DIR` | `/project/llmponco/.../pathlab_test_data` | durable data root (reuse before download) |
| `PATHLAB_CKPT_DIR` / `HF_HOME` / `HF_TOKEN` | — | extractor checkpoints / HF cache / gated models (shell, not `.env.local`) |
| `PATHSCIENTIST_AUTO_ACQUIRE_DATA` | `1` | auto dataset discovery+download |
| `PATHSCIENTIST_DOWNLOAD_POLICY` | **`all`** | `public_only`\|`manual_only`\|`public_or_manual`\|`all`\|`disabled` ⚠️ `all` is permissive (§7.3) |
| `PATHSCIENTIST_MAX_DOWNLOAD_SIZE_GB` / `_ALLOW_LARGE_DOWNLOADS` | `500` / `1` | download size cap (note: weakly enforced — see security plan B-SIZE) |
| `PATHSCIENTIST_FEATURE_EXTRACTOR_MODE` / `_FEATURE_EXTRACTOR` | `auto` / (virchow2 when fixed) | feature extractor selection |
| `PATHSCIENTIST_{TIMEOUT,QUICK_CHECK_TIMEOUT,FEATURE_EXTRACTION_*TIMEOUT}` | 3600 / 3600 / 3600 | execution timeouts (s) |
| `PATHSCIENTIST_LITERATURE_ONLINE` / `_RAG` | `1` / off | online paper search / RAG |
| `PATHSCIENTIST_STOP_BEFORE_EXECUTION` | off | dry-run through pre-training stages |
| `CUDA_VISIBLE_DEVICES` | (host) | GPU selection |

`.env.local` overrides apply only for `PATHSCIENTIST_*` keys; shell env wins over `.env.local`; CLI flags win over both.

## 4. Run modes & python resolution
- **Standalone `start.sh`** exports `PATH="$VENV_DIR/bin:$PATH"`, so the agent's `python <script>` resolves to the venv.
  (The host has **no bare `python`** — only `python3`=system 3.10 — so this PATH export is load-bearing; see §7.2.)
- **Web `deploy/start.sh`** auto-selects python: `PATHLAB_PYTHON` override → **pathscientist venv** → project venv →
  conda → system. Ports `6100/6101/6102`. ⚠️ Confirm it also puts the venv on `PATH` for child experiment processes
  (§7.2), or have `run_script` use `sys.executable`.

## 5. Migration checklist (machine → machine)

**Carry over (copy):**
- [ ] **Code** — via git (branch + the committed docs).
- [ ] **`.env.local`** — securely (it holds the LLM key); `chmod 600`; ensure it's git-ignored on the target.
- [ ] **Dataset cache** (`PATHSCIENTIST_DATASET_CACHE_DIR`) — copy or re-point; large, reuse to avoid re-download.
- [ ] **Model checkpoints** (`PATHLAB_CKPT_DIR`, `HF_HOME`/HF cache) — copy or re-point.
- [ ] **Credentials** — `HF_TOKEN`, `KAGGLE_*`, `GDC_TOKEN` (shell/`server/.env`, **not** `.env.local`).

**Rebuild on the target (do NOT copy):**
- [ ] **`.venv`** — `uv venv` + requirements + **CUDA-matched torch** (a copied venv breaks on a different driver/CUDA).
- [ ] **`.sif`** — `apptainer build --fakeroot` on the target (or copy only if same CPU arch + apptainer present).
- [ ] **Workspaces / output / `.evidence`** under `PATHSCIENTIST_BASE_DIR` — ephemeral, regenerate.

**Reconfigure (machine-specific):**
- [ ] `CUDA_VISIBLE_DEVICES`, `PATHSCIENTIST_BASE_DIR`, dataset/ckpt paths, web ports.
- [ ] `APPTAINER_BIN` only if apptainer isn't on `PATH` (else auto-found).

**Verify after migration:** §2.2 sanity import (torch+cuda) → §2.4 `check_available()` → a `STOP_BEFORE_EXECUTION` dry
run → one real quick-check run showing `[sandbox] apptainer exec`.

## 6. Do-not-commit / ignored
`.venv/`, `.env.local`, `*.sif`, `output/`, `sota_cache.json`, `<client>/logs/`, `server/.env`, `uploads/`,
`*.token`, `kaggle.json`. (Confirm `.env.local` + `*.sif` are in `.gitignore` — see §7.4.)

## 7. Known gotchas / current issues
1. **The `.venv` is currently MISSING** on jhcpu5 (lost in the consolidation). Rebuild it (§2.2) — `start.sh` fails and
   the sandbox can't be verified without it.
2. **No bare `python` on the host** (only `python3`=3.10, no torch). Local execution works only because `start.sh`
   exports the venv on `PATH`. **Verify the web path** (`deploy/start.sh`) does the same for child experiment processes,
   or the gateway's runs hit `python: command not found`. Cleanest fix: have `runtime/workspace.run_script` invoke
   `sys.executable` instead of bare `python`.
3. **`download_policy=all` + 500 GB cap + auto-acquire on** = effectively unrestricted internet dataset fetch from a
   run. Combine with the security plan's `B-NET`/`B-SIZE`/SSRF guards before exposing widely; tighten to `public_only`
   for shared/untrusted use.
4. **`.env.local` holds a live LLM key and must be git-ignored** (security plan `E-SEC2`). Verify before any migration
   that copies the tree, and rotate if it ever landed in git.
5. **Sandbox binary** is now resolved via `shutil.which` (good) — but if you move to a host where apptainer is at a
   non-standard path and not on `PATH`, set `APPTAINER_BIN` explicitly.

## 8. Related docs
- `README.md` — operational quick start (modes, prompts, tests).
- `docs/plan/2026-06-17-pathscientist-sandbox-migration-runbook.md` — apptainer install + `.sif` build detail.
- `docs/plan/2026-06-18-pathscientist-web-security-remediation-plan.md` — the security hardening this env should adopt.
- `docs/dataset_acquisition.md` — dataset providers + cache layout.
