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

# --- Patch 2: embedded-postgres env inheritance + Error rejections ---
TARGET2="node_modules/embedded-postgres/dist/index.js"

if [ ! -f "$TARGET2" ]; then
    echo "SKIP: $TARGET2 not found"
    exit 0
fi

python3 - <<'PYEOF2'
import sys

target = "node_modules/embedded-postgres/dist/index.js"
with open(target, "r") as f:
    content = f.read()

patches = [
    # Patch env stripping on initdb spawn (line ~136)
    (
        "], Object.assign(Object.assign({}, permissionIds), { env: { LC_MESSAGES: LC_MESSAGES_LOCALE } }));",
        "], Object.assign(Object.assign({}, permissionIds), { env: Object.assign(Object.assign({}, globalThis.process.env), { LC_MESSAGES: LC_MESSAGES_LOCALE }) }));",
        2  # expect exactly 2 occurrences (initdb + postgres spawns)
    ),
    # Patch string rejection → Error rejection (initdb exit)
    (
        "reject(`Postgres init script exited with code ${code}. Please check the logs for extra info. The data directory might already exist.`);",
        "reject(new Error(`Postgres init script exited with code ${code}. Please check the logs for extra info. The data directory might already exist.`));",
        1
    ),
    # Patch empty rejection → Error rejection (postgres early exit)
    (
        "reject();",
        "reject(new Error('Postgres process exited unexpectedly'));",
        1
    ),
]

already_patched_markers = [
    "Object.assign({}, globalThis.process.env)",
    "reject(new Error(`Postgres init script",
    "reject(new Error('Postgres process exited unexpectedly'",
]

if any(m in content for m in already_patched_markers):
    print(f"Already patched: {target}")
    sys.exit(0)

for old, new, expected_count in patches:
    actual_count = content.count(old)
    if actual_count == 0:
        print(f"ERROR: Expected to find pattern not found in {target}:\n  {old}", file=sys.stderr)
        sys.exit(1)
    if actual_count != expected_count:
        print(f"WARNING: Expected {expected_count} occurrences, found {actual_count} for:\n  {old}", file=sys.stderr)
    content = content.replace(old, new)

with open(target, "w") as f:
    f.write(content)
print(f"Patched: {target}")
PYEOF2
