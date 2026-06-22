# PathScientist Sandbox — Status & Migration Runbook

> Date: 2026-06-17
> Type: Runbook (migration / enablement)
> Purpose: PathScientist ships an apptainer sandbox, but it is **not active on `jhcpu5`** (apptainer absent →
>   `auto` falls back to **local, unsandboxed** execution). This doc records the current state, the feasibility
>   findings on this host, and a concrete, runnable path to migrate to a working sandbox.
> Paths relative to `server/backend/pathscientist/` unless noted.

## 0. TL;DR

- **Now:** no isolation. The code agent's generated scripts run as plain host processes (`yihui`), in the **same uv
  venv as PathScientist itself**, with full host network and direct access to all 7× RTX 3090. This is the live
  reality of review findings F-A2 / F-A6.
- **Sandbox code exists** (`runtime/sandbox.py::ApptainerSandbox`) but is apptainer-only, and apptainer/docker are not
  usable here (no sudo).
- **Migration is feasible without admin**: rootless user namespaces are enabled and `/etc/subuid`+`/etc/subgid` already
  map `yihui`, so apptainer can run rootless and **build images with `--fakeroot`** once the apptainer binary is present.

## 1. Current state (verified on jhcpu5, 2026-06-17)

| Probe | Result |
|---|---|
| `apptainer` / `singularity` | **not installed**, no module system, not under `/cm/local/apps` |
| `PATHSCIENTIST_SANDBOX` (start.sh default) | `auto` → `ApptainerSandbox.check_available()` = False → **local** |
| `.sif` images | none anywhere reachable; no build recipe (`.def`/Dockerfile) in repo |
| `docker` | binary present but daemon **not usable** (no docker group) |
| `sudo` | **no** (password required) |
| kernel / OS | Ubuntu 22.04.5, 5.15.0; `unprivileged_userns_clone=1`, `max_user_namespaces` huge → **rootless OK** |
| `fakeroot` | present (`/usr/bin/fakeroot`) |
| `/etc/subuid` `/etc/subgid` | **`yihui:886432:65536`** in both → **`apptainer build --fakeroot` will work** |
| venv | uv-managed Python 3.12.13, **torch 2.12.0+cu130** (CUDA 13.0), `cuda.is_available()=True`, 7 devices, 6.6G, only in `~/PathLab` worktree |

How PathScientist resolves the sandbox (`runtime/sandbox.py`):
- binary: `APPTAINER_BIN` env, else `/cm/local/apps/apptainer/current/bin/apptainer` (missing here).
- image: `PATHSCIENTIST_SANDBOX_IMAGE` / `PATHLAB_SANDBOX_IMAGE` env, else `auto_research_old/pathlab-sandbox-transformers.sif` → `pathlab-sandbox.sif`.
- `check_available()` requires: `APPTAINER_BIN` exists **AND** `apptainer --version` returns 0 **AND** the default image file exists.
- `auto` mode uses the sandbox iff `check_available()`; `apptainer` mode forces it; `local` never uses it.

## 2. Target architecture

```
PathScientist (host venv)  ──run_experiment──▶  apptainer exec --nv  <pathlab-sandbox.sif>
                                                  ├─ container: python3.12 + torch(cu130) + extractor deps  (image)
                                                  ├─ --nv: host GPU driver injected  (3090 × N)
                                                  ├─ binds (rw): workspace, output, dataset cache, model caches
                                                  └─ binds (ro, after hardening): /project,/tmp,/data, common/ templates
```
The image only carries the **Python environment** the agent's training/extraction scripts import — data, WSIs, and
model checkpoints are **bind-mounted** by `_build_exec_cmd`, so the `.sif` stays lean (~6–8 GB) and reusable.

## 3. Migration steps (runnable)

### Step 1 — Get an apptainer binary (pick one)
**1a. Admin installs (cleanest, one line for whoever has root):**
```bash
sudo apt-get update && sudo apt-get install -y apptainer   # or the .deb from github.com/apptainer/apptainer/releases
```
**1b. No admin — rootless via micromamba (works here; userns is on):**
```bash
cd ~ && curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba
~/bin/micromamba create -y -n sandbox -c conda-forge apptainer
export APPTAINER_BIN="$HOME/micromamba/envs/sandbox/bin/apptainer"
"$APPTAINER_BIN" --version            # confirm it runs
```
(subuid/subgid are already mapped for `yihui`, so `--fakeroot` builds work with either install.)

### Step 2 — Build the `.sif` (rootless, `--fakeroot`)
Create `auto_research_old/pathlab-sandbox.def` (the image must match the host venv: python3.12 + **torch cu130** +
the extractor stack from `server/requirements.txt`):
```singularity
Bootstrap: docker
From: nvidia/cuda:13.0.0-cudnn-runtime-ubuntu22.04

%post
    export DEBIAN_FRONTEND=noninteractive
    apt-get update && apt-get install -y software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa && apt-get update
    apt-get install -y python3.12 python3.12-venv python3.12-dev python3-pip \
        openslide-tools libopenslide0 libgl1 libglib2.0-0 git curl
    python3.12 -m pip install --upgrade pip
    # match the agent venv exactly (torch cu130 + extractor deps)
    python3.12 -m pip install torch==2.12.0 torchvision --index-url https://download.pytorch.org/whl/cu130
    python3.12 -m pip install \
        "numpy==1.26.4" "pillow>=12.1.0" "opencv-python>=4.11,<4.12" "openslide-python>=1.4.2" \
        "timm>=1.0.24" "transformers>=4.57.0" "einops>=0.8.1" "einops-exts>=0.0.4" \
        "scikit-learn>=1.5.1" "h5py>=3.11.0" "pandas>=2.2.2"

%environment
    export PYTHONUNBUFFERED=1
    export TORCH_CUDNN_V8_API_DISABLED=1

%runscript
    exec python3.12 "$@"
```
Build (needs a few GB free — check `df -h ~ /tmp` first; set `APPTAINER_TMPDIR` to a roomy fs if `~` is small):
```bash
cd ~/PathLab/pathlab/pathlab-client/server/backend/auto_research_old
APPTAINER_TMPDIR=/project/.../tmp "$APPTAINER_BIN" build --fakeroot pathlab-sandbox.sif pathlab-sandbox.def
```
> Note: `bash -lc` calls inside the container reference `python`; the image's `python` should resolve to 3.12.
> If using `python3.12`, either symlink `python`→`python3.12` in `%post` or set the run path accordingly — the
> agent's scripts are invoked as `python {script}` (see `sandbox.py:143`), so a bare `python` must exist in the image.

### Step 3 — Point PathScientist at it
Put the image at the default path (Step 2 already does) **or** set env. In `pathscientist/.env.local` / your launcher:
```bash
export APPTAINER_BIN="$HOME/micromamba/envs/sandbox/bin/apptainer"   # only if not at the /cm/local default
export PATHSCIENTIST_SANDBOX_IMAGE="/home/yihui/PathLab/.../auto_research_old/pathlab-sandbox.sif"
export PATHSCIENTIST_SANDBOX=apptainer       # or leave 'auto' — it auto-engages once check_available() passes
```
> `.env.local` only loads `PATHSCIENTIST_*` keys, so `APPTAINER_BIN` must go in the shell env / `start.sh`, not `.env.local`.

### Step 4 — Verify
```bash
# (a) raw container sees the GPUs:
"$APPTAINER_BIN" exec --nv "$PATHSCIENTIST_SANDBOX_IMAGE" python -c "import torch;print(torch.cuda.is_available(), torch.cuda.device_count())"
# (b) PathScientist agrees the sandbox is available:
~/PathLab/.../.venv/bin/python -c "from pathscientist.runtime.sandbox import ApptainerSandbox as A; print('available:', A.check_available())"
# (c) a real, tiny end-to-end run lands inside the container (look for '[sandbox] apptainer exec' in logs):
PATHSCIENTIST_SANDBOX=apptainer ./start.sh -q "Create a 3-slide subset and run a 2-epoch MIL smoke test." --quick
```

## 4. Don't just flip it on — harden while migrating
Enabling apptainer closes the "runs on bare host" gap, but the sandbox still has the review weaknesses. Address them
in the same migration so you don't trade one false sense of safety for another:
- **F-A6 — no network isolation + broad rw binds** (`sandbox.py:199-272`): add `--net --network none` for non-download
  runs (gate egress for acquisition behind an allowlist), and bind `/project`,`/tmp`,`/data` + model caches **`:ro`**.
- **F-A1 — `TerminalTool` is unsandboxed** (`agent.py:306`): it bypasses the container entirely (runs on the host). Cage
  it (route through the sandbox) or restrict/remove it — otherwise the sandbox is moot for shell actions.
- **F-A8 — host-side git/checkpoint** (`workspace.py`): these always run on the host; the checkpoint-name injection fix
  (plan `A8`) still matters even with apptainer on.
- **Separate the agent venv from the orchestrator venv** (see §5) so an agent `pip install` can't corrupt PathScientist.

## 5. Fallback — if apptainer can't be stood up, harden local mode
If you must stay on `local`:
- **Split environments**: give the agent's scripts their own venv (not the 6.6G orchestrator venv) so a script can't
  mutate OpenHands/PathScientist deps. Today `workspace.run_script` runs bare `python {script}` resolved from PATH — it
  hits the orchestrator venv via `start.sh`'s `export PATH=.venv/bin:$PATH`.
- **Resource limits**: wrap local runs in a cgroup (systemd-run --user --scope -p MemoryMax= -p CPUQuota=) so a runaway
  script can't OOM the box.
- **Network**: restrict egress (the agent has full host network in local mode).
- **Disable/cage `TerminalTool`** and keep the FileEditor allowlist meaningful.
- **Use `sys.executable`, not bare `python`** in the local branch (see §6 gotcha #2).

## 6. Operational gotchas to carry across the migration
1. **venv only in `~/PathLab`** — the `PathLab_fix_pathscientist_sessions` worktree has **no `.venv`**; `start.sh` there
   fails ("Python venv not found"). Build/symlink a venv per worktree, or run from `~/PathLab`.
2. **bare `python` does not exist on this host** (only `python3` = system 3.10, no torch). Local-mode `python {script}`
   works **only** because `start.sh:119` does `export PATH=.venv/bin:$PATH`. **Verify the web path:** `deploy/start.sh`
   launches `$PYTHON main.py` but should also `export PATH=<venv>/bin:$PATH`, or the gateway's experiment subprocesses
   hit `python: command not found`. Safer fix: have `run_script` invoke `sys.executable` instead of bare `python`.
3. **`download_policy=all`, `max_download_size_gb=500`, `auto_acquire=1`** (start.sh) — combined with review B-NET/B-SIZE
   this is effectively unrestricted internet fetch from inside the run; tighten before/with the sandbox.
4. **`.env.local` holds a live LLM API key and is not git-ignored** (review E-SEC2) — gitignore + rotate before any
   migration that copies the tree.
5. **Image/CUDA match**: the `.sif` must carry torch built for a CUDA the host driver supports (host runs cu130 today).
   `--nv` injects the driver; keep the image's CUDA ≤ host driver capability.

## 7. Verification checklist
- [ ] `apptainer --version` runs (Step 1).
- [ ] `apptainer build --fakeroot pathlab-sandbox.sif ...` succeeds (subuid mapping confirmed present).
- [ ] `apptainer exec --nv <sif> python -c "import torch;print(torch.cuda.is_available())"` → `True`.
- [ ] `ApptainerSandbox.check_available()` → `True`.
- [ ] A quick run logs `[sandbox] apptainer exec` (not local) and produces metrics.
- [ ] Hardening applied: `--net none` default, `:ro` shared binds, TerminalTool caged, agent venv separated.
- [ ] Web path: `deploy/start.sh` exports the venv on PATH (or `run_script` uses `sys.executable`).

## 8. Status note for the master plan
Sandboxing is currently **implemented but inert on production hardware**. Until §3 is done, treat the system as
**unsandboxed** for threat-modeling, and read review findings F-A2/F-A6/F-A7 as *active*, not theoretical.
