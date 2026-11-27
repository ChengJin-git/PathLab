# Moving a PathLab installation

This guide covers moving an existing installation — runtime environment and data — to another
server. For a new installation see [docs/installation.md](../../../docs/installation.md).

## Database and files

The code requires the schema version recorded in `current_schema.SCHEMA_VERSION`. Move the
PostgreSQL database with `pg_dump`/`pg_restore` and copy the complete storage root: result ZIPs and
the SQLite result catalog, features, coordinates, `.feature.json` files, the file library
(`chat-files/`, `knowledge-index/`), model checkpoints and the research workspaces including
`autoresearch/runtime/`. Stop writes first or use the SQLite backup API so that WAL files are not
copied mid-write.

Also move `server/.env` and `storage.json` (in the application-data directory) over a secure
channel. Keep the same `JWT_SECRET`. The database and manifests contain absolute paths, so keep the
storage mount path if possible. Pause or stop running research sessions and confirm their jobs have
exited before copying.

## Retrieval and OCR models

```bash
"$PATHLAB_PYTHON" deploy/prepare-knowledge.py --check
"$PATHLAB_PYTHON" deploy/prepare-ocr.py --check
```

Retrieval uses LanceDB 0.41.0, LlamaIndex Core 0.14.25, Sentence Transformers 6.2.0 and jieba
0.42.1; scanned PDF pages use RapidOCR 3.10.0 with the PP-OCRv6-small ONNX models in
`~/.local/share/PathLab/ocr-models` (or `PATHLAB_OCR_MODEL_DIR`). For offline servers copy the model
caches; `--check` verifies the pinned SHA-256 values. Requests never download models at run time.
The PDF worker only uses the ONNX CPU execution provider.

## OpenCode and PathTrove

```bash
python3 deploy/install-opencode.py --output "$HOME/.opencode/bin/opencode"
"$HOME/.opencode/bin/opencode" --version
```

The PathTrove data package is installed to `<storage>/autoresearch/pathtrove` by `deploy/start.sh`.
Copy that directory, or on an offline server install a downloaded package with
`"$PATHLAB_PYTHON" deploy/install-pathtrove-data.py --file pathtrove-data-2026.09.28.tar.gz`.

## Moving the Python environment as hashed wheels (optional)

Reinstalling from `server/requirements.txt` on the new server is the simplest route. To move an
environment that has already been verified exactly as it is, export it as a bundle:

```bash
"$PATHLAB_PYTHON" deploy/verify-runtime.py
"$PATHLAB_PYTHON" -m pip check
"$PATHLAB_PYTHON" deploy/runtime_bundle.py export \
  --bundle /path/to/runtime-bundle \
  --sandbox ~/.local/share/PathLab/sandbox/pathlab-sandbox.sif
```

`runtime_bundle.py` rebuilds wheels from the installed files (keeping code, binaries and metadata),
records hashes in `requirements.lock` and writes `manifest.json` with the PathLab commit, Python
version, platform, package versions and Git sources. It also includes OpenCode, `uv` and the sandbox
image. It never collects keys, datasets or application settings. The target directory must not
exist. Transfer the bundle over a trusted channel (rsync over SSH).

On the new server (same architecture, compatible glibc, NVIDIA driver and CPU features):

```bash
sudo bash deploy/install-system-deps.sh
bash deploy/install-runtime.sh /path/to/runtime-bundle ~/.local/share/PathLab/venv-new
source ~/.local/share/PathLab/venv-new/pathlab.env
"$PATHLAB_PYTHON" -m pip check
"$PATHLAB_PYTHON" deploy/verify-runtime.py
apptainer exec --nv "$AUTORESEARCH_SANDBOX_IMAGE" python -c \
  'import torch; print(torch.__version__, torch.ones(2, device="cuda"))'
```

The installer uses `uv` to obtain the exact Python version (on an offline server pass an existing
interpreter of the same version as the third argument), installs wheels with
`--no-index --no-deps --require-hashes`, runs `pip check` and the import checks, and only then
writes `pathlab.env`. The target virtual environment must be new. Keep the sandbox image in the
bundle directory.

## Start and verify

```bash
npm ci
bash deploy/start.sh
```

For systemd, convert the values in `pathlab.env` into `Environment=` lines (systemd does not accept
`export`) and make sure Apptainer is on `PATH`. Check the three `/health` endpoints, both workers,
OpenCode and one real GPU experiment; GPU behaviour must be re-measured on new hardware.
