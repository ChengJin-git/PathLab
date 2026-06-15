---
name: codebase-explorer
description: >
  Recursively analyze and document an entire code repository — modules, submodules, classes, and methods.
  USE FOR: understanding unfamiliar codebases before adding features; generating a navigable wiki of what every module and function does;
  onboarding to a new project; quickly locating which file/function to modify for a given feature.
  Starts by reading README.md to anchor module-level understanding, then drills into each file.
  Produces a structured CODEBASE_MAP.md with module summaries, function signatures, and "where to edit" tags.
  DO NOT USE FOR: running tests, writing new code, or refactoring.
  INVOKES: file system tools (find, read), scripts/parse-structure.py, references/output-template.md.
---

# Codebase Explorer

Recursively parse an entire code repository, summarize every module and method, and produce a CODEBASE_MAP.md that acts as a living navigation guide for future development.

---

## Step 0 — Anchor with README

Before reading any code, always read `README.md` (and any `docs/` or `wiki/` folders) first:

1. Run: `cat README.md 2>/dev/null || echo "No README found"`
2. Extract: project purpose, main entry point, key modules listed, architecture overview, tech stack.
3. Record these as the **Module Context Header** at the top of CODEBASE_MAP.md.
4. If there are sub-READMEs in subdirectories (e.g. `src/module/README.md`), queue them for reading when visiting that directory.

---

## Step 1 — Map the Directory Tree

Run the helper script to get the full structure:

```bash
python3 .codex/skills/codebase-explorer/scripts/parse-structure.py --root . --output /tmp/tree.json
```

This outputs a JSON tree of all files grouped by directory, excluding common noise directories (node_modules, __pycache__, .git, dist, build, .venv).

If the script is unavailable, fall back to:
```bash
find . -type f \( -name "*.py" -o -name "*.ts" -o -name "*.js" -o -name "*.go" -o -name "*.rs" -o -name "*.java" \) \
  | grep -v -E "(node_modules|__pycache__|\.git|dist|build|\.venv|\.next)" \
  | sort > /tmp/file-list.txt
cat /tmp/file-list.txt
```

---

## Step 2 — Recursive Module Analysis

For each directory that contains source files:

1. **Check for a local README** — if present, read it and use it as the module description.
2. **Identify the module's role** from its directory name, imports, and exports.
3. **For each file in the module:**
   a. Read the file.
   b. Extract: imports/dependencies, exported classes/functions/constants, internal helper functions.
   c. For each function/method, extract: name, parameters, return type (if typed), one-line purpose derived from docstring, body logic, or naming.
   d. Tag functions with one of: `[ENTRY]` (main entry point), `[API]` (exposed interface), `[CORE]` (key business logic), `[UTIL]` (utility/helper), `[CONFIG]` (configuration), `[TEST]` (test code).

4. If a file is >500 lines, read it in chunks. Focus on:
   - Top-level imports
   - Class/function definitions (skip bodies initially)
   - Module-level docstrings and comments

---

## Step 3 — Build CODEBASE_MAP.md

Write the output file using the template at `references/output-template.md`.

Structure:
```
# CODEBASE_MAP.md

## Project Overview
(From README.md — purpose, stack, entry points)

## Directory Structure
(Annotated tree — one line per directory with its role)

## Module Breakdown
### /src/module-name
**Role:** What this module does in the system
**Key files:**
- `filename.py` — one-sentence description

#### Functions & Classes
| Symbol | Type | Tag | Description |
|--------|------|-----|-------------|
| `MyClass` | class | [CORE] | Handles X by doing Y |
| `my_func(a, b)` | function | [API] | Returns Z given A and B |

**Where to edit when you want to:**
- Add a new route → `router.py: register_route()`  
- Change auth logic → `middleware/auth.py: verify_token()`
- Modify DB schema → `models/user.py: User class`
```

Prioritize the **"Where to edit when you want to"** section — this is the highest-value output for future development.

---

## Step 4 — Cross-Reference Index

At the end of CODEBASE_MAP.md, append a flat index:

```markdown
## Quick Lookup Index

| I want to... | File | Symbol |
|---|---|---|
| Add an API endpoint | src/routes/api.py | register_route() |
| Change the data model | src/models/ | (class per entity) |
| Modify LLM prompts | src/prompts/ | SYSTEM_PROMPT, USER_TEMPLATE |
```

Ask the user: "What are the 5 most common features you'd want to add to this project?" and pre-fill the index with their answers.

---

## Step 5 — Output

Save `CODEBASE_MAP.md` to the repository root.
Print a summary: total modules parsed, total functions documented, and the top 3 "hottest" files (most imports / most referenced).

Tell the user: "To navigate: search CODEBASE_MAP.md for the feature area you want to modify. The 'Where to edit' sections will guide you to the exact file and function."

---

## Notes

- For very large repos (>200 files), process the most important modules first: look for files named `main`, `app`, `index`, `server`, `router`, `core`, `pipeline` — these are the architectural spine.
- For monorepos, treat each top-level package as its own module with its own README pass.
- If you encounter generated files (migrations, proto stubs, compiled output), note them but don't document their internals.
