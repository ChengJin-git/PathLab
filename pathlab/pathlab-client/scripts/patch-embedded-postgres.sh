#!/bin/bash
set -euo pipefail

TARGET="node_modules/@embedded-postgres/linux-x64/dist/index.js"

if [ ! -f "$TARGET" ]; then
    echo "SKIP: $TARGET not found"
    exit 0
fi

python3 - <<'PYEOF'
import sys

target = "node_modules/@embedded-postgres/linux-x64/dist/index.js"
with open(target, "r") as f:
    content = f.read()

old_line = "const __dirname = path.dirname(fileURLToPath(import.meta.url));"
new_line = (
    "const _asarFixedUrl = import.meta.url.replace(/([\\/\\\\])app\\.asar\\1/g, '$1app.asar.unpacked$1'); "
    "const __dirname = path.dirname(fileURLToPath(_asarFixedUrl));"
)

if old_line in content:
    content = content.replace(old_line, new_line)
    with open(target, "w") as f:
        f.write(content)
    print(f"Patched: {target}")
elif new_line in content or "_asarFixedUrl" in content:
    print(f"Already patched: {target}")
else:
    print(f"ERROR: Unexpected content in {target}", file=sys.stderr)
    sys.exit(1)
PYEOF
