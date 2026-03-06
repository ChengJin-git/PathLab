# Deep Research Source Snapshot

This directory stores a vendored source snapshot for the Deep Research backend
used by PathLab.

Current source origin:
- `pathlab/pathlab-client/server/.venv/lib/python3.13/site-packages/src`

Snapshot sync command:

```bash
mkdir -p server/backend/deep-research/src
rsync -a --delete \
  server/.venv/lib/python3.13/site-packages/src/ \
  server/backend/deep-research/src/
find server/backend/deep-research/src -type d -name '__pycache__' -prune -exec rm -rf {} +
find server/backend/deep-research/src -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
```
