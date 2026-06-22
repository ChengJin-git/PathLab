# PathScientist Apptainer Sandbox

This document records the portable PathScientist runtime setup used on `jhcpu5.cse.ust.hk`.
The backend still runs on the host Python environment. The Apptainer image is only used for generated training, feature extraction, and external-test scripts.

For the full server deployment order, start with
[`pathscientist-deployment-quickstart.md`](pathscientist-deployment-quickstart.md). This file focuses only on the sandbox image.

## Files

- Definition file: `server/backend/pathscientist/runtime/containers/pathlab-sandbox.def`
- jhcpu5 active image path: `.local/pathscientist/sandbox/pathlab-sandbox.sif`
- Directory sandbox fallback path: `.local/pathscientist/sandbox/pathlab-sandbox`
- PathScientist config file: `server/backend/pathscientist/.env.local`
- Runtime selector: `server/backend/pathscientist/runtime/sandbox.py`

## Build On A New Server

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

## SIF And Directory Sandbox

Apptainer supports both immutable `.sif` files and directory sandbox images. On `jhcpu5`, the full dependency build and `%test` passed, but the first SIF compression failed in `mksquashfs` with exit 139. A later attempt to compress the working directory sandbox also failed because fakeroot left a root-owned apt cache subdirectory and an extra `--mksquashfs-args -no-progress` conflicted with Apptainer's built-in progress flag.

The fix was:

1. Remove/recreate the unreadable apt cache directory inside the directory sandbox.
2. Set Apptainer mksquashfs compression to one processor and 4G memory in `/etc/apptainer/apptainer.conf`.
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

If SIF compression works on a target server, use the `.sif` command above. If it fails at `mksquashfs`, use the directory sandbox and point `PATHSCIENTIST_SANDBOX_IMAGE` to that directory. The directory sandbox is larger and mutable, but PathScientist still runs scripts with `apptainer exec --writable-tmpfs`, so normal session writes stay ephemeral unless an explicit bind mount is writable.

## Configure PathScientist

Add these values to `server/backend/pathscientist/.env.local`:

```bash
PATHSCIENTIST_SANDBOX=auto
PATHSCIENTIST_SANDBOX_IMAGE=/absolute/path/to/pathlab-client/.local/pathscientist/sandbox/pathlab-sandbox.sif
PATHSCIENTIST_SANDBOX_CGROUPS=0
```

`auto` means PathScientist will use Apptainer when both the binary and image are available, and otherwise fall back to local execution. Use `PATHSCIENTIST_SANDBOX=apptainer` when you want missing sandbox setup to fail loudly.

`PATHSCIENTIST_SANDBOX_CGROUPS=0` disables Apptainer `--memory/--cpus` flags. Keep it on jhcpu5 because its user.slice cgroup rejects those limits at runtime. On a cluster where cgroup limits work, remove the variable or set it to `auto`.

`runtime/sandbox.py` resolves the Apptainer binary in this order:

1. `APPTAINER_BIN`
2. `apptainer` found on `PATH`
3. Legacy cluster path `/cm/local/apps/apptainer/current/bin/apptainer`

## Verify

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

## Runtime Mounts

PathScientist binds the following into the container:

- Session workspace: read/write, same absolute path inside the container
- Session output directory: read/write, same absolute path inside the container
- Prepared dataset mounts from acquisition, usually host dataset view to `/data/...`
- Existing host roots `/project`, `/tmp`, and `/data` when present
- Template `common/` utilities to `<workspace>/common:ro`
- Existing model caches under `~/.cache/torch`, `HF_HOME` or `~/.cache/huggingface`
- Kaggle config directory as `/kaggle:ro` when configured

This is why local execution can fail on `/data/...` paths while Apptainer execution works: `/data/...` is a container contract path backed by explicit binds.

## Migration Checklist

1. Install Apptainer and confirm `apptainer --version` works for the service user.
2. Confirm the service user has fakeroot mappings in `/etc/subuid` and `/etc/subgid`, or build the SIF as root/admin once.
3. Build `pathlab-sandbox.sif` from `pathlab-sandbox.def`.
4. Copy or recreate `.env.local` values for sandbox, LLM, HF, and Kaggle credentials.
5. Restart the backend process so `PATHSCIENTIST_SANDBOX_IMAGE` is loaded.
6. Run the two verification commands above.
7. Start a small PathScientist session and confirm logs show `[apptainer] python ...` instead of local `python ...`.

## Common Failures

- `check_available()` is `False`: image path does not exist, Apptainer is not on `PATH`, or `APPTAINER_BIN` points to a stale binary.
- `while setting cgroup limits ... cpu.max`: set `PATHSCIENTIST_SANDBOX_CGROUPS=0` and restart the backend.
- `127.0.0.1 refused to connect`: backend process is down; restart backend before testing the frontend.
- `/data/...` missing in a session log: the run is using local execution or the prepared dataset mount was not passed into the sandbox.
- `torch.cuda.is_available() == False`: retry with `apptainer exec --nv`; if still false, check NVIDIA driver/container integration on the host.
- `ModuleNotFoundError` inside training scripts: add the runtime dependency to `pathlab-sandbox.def`, rebuild the SIF or directory sandbox, and restart backend.
- SIF build from a directory sandbox reports permission errors under `var/cache/apt/archives/partial`: rebuild directly from `pathlab-sandbox.def`, or clean/chown that directory as an administrator before repacking.
- SIF compression crashes with `mksquashfs exit status 134` or `malloc(): corrupted top size`: reduce `/etc/apptainer/apptainer.conf` to `mksquashfs procs = 1` and `mksquashfs mem = 4G`, then rebuild without extra `--mksquashfs-args`.
