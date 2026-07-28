# PathLab Paper Agent Quick Start

PathLab Paper Agent is the paper-generation runtime inside PathLab. It turns
completed experiment tasks into evidence-bounded manuscript drafts, figures,
tables, citations, validation reports, rendered PDFs, and downloadable export
bundles.

The user-facing feature is exposed through the PathLab web app under `/papers`.
The implementation lives in this standalone `uv` project so paper-generation
code, tests, templates, and development tooling stay separate from the Gateway
compatibility layer.

This README is the practical setup guide for developers and operators. It also
summarizes the paper-generation workflow so teammates can understand what the
web UI is doing without reading the whole agent implementation.

---

## 1. Repository Locations

From the git root:

```text
pathlab/pathlab-client/
  package.json                         # frontend/Electron dependencies
  deploy/start.sh                      # fixed-port web/backend launcher
  server/
    main.py                            # starts Gateway/Preprocessing/AI
    gateway/paper_generation/          # thin /papers API compatibility bridge
    task_worker/jobs/paper_generation.py
    paper_agent/                       # this standalone Paper Agent project
```

Important Paper Agent subdirectories:

```text
paper_agent/
  docs/                                # design plans, phase plans, notes
  src/pathlab_paper_agent/
    api/                               # FastAPI routes mounted by Gateway/dev server
    agents/                            # outline, plotting, literature, section writing
    citations/                         # manual DOI/arXiv/BibTeX parsing and syncing
    collector/                         # source task artifact collection
    renderers/                         # LaTeX rendering and export packaging
    stages/                            # pipeline stage implementations
    templates/                         # MICCAI and Nature Scientific Reports assets
    validators/                        # claim, consistency, citation, metric, LaTeX guards
  tests/                               # agent + gateway-interface tests
  pyproject.toml                       # the only uv project for paper generation
  uv.lock
```

Gateway and TaskWorker keep only thin compatibility bridges at
`server/gateway/paper_generation/` and
`server/task_worker/jobs/paper_generation.py` so the front-end `/papers` API and
worker handler names remain stable. New Paper Agent implementation should live
under `server/paper_agent/`.

Run git commands from the repository root, not from this directory:

```bash
cd /path/to/PathLab
```

---

## 2. Supported Developer Modes

Use one of these modes depending on the task.

| Mode | Use when | Entry |
|---|---|---|
| Full PathLab web app | Testing the frontend paper-generation UI and Gateway routes | `pathlab/pathlab-client/deploy/start.sh` then open `/papers` |
| Standalone Paper Agent CLI | Debugging stages, render/export, citation sync, validators | `uv run pathlab-paper-agent ...` from `server/paper_agent` |
| Standalone Paper Agent dev server | Testing `/papers` routes without the full Gateway process | `uv run pathlab-paper-agent serve ...` |
| Unit tests | Reviewing isolated Paper Agent logic | `uv run pytest` from `server/paper_agent` |
| Stage smoke run | Replaying one stage against a local run directory | `uv run pathlab-paper-agent run-stage ...` |

The web app and standalone CLI share the same core package. Production-style
PathLab runs use Gateway + TaskWorker; the worker invokes the standalone Paper
Agent command as a subprocess.

---

## 3. System Prerequisites

Minimum for backend/Paper Agent development:

```bash
# Ubuntu/Debian style package names
sudo apt-get update
sudo apt-get install -y \
  build-essential git curl bash pkg-config \
  python3 python3-venv python3-pip \
  nodejs npm \
  redis-server postgresql postgresql-client
```

Additional dependencies:

| Dependency | Needed for |
|---|---|
| `uv` | Creating and running the standalone Paper Agent Python environment |
| LaTeX distribution, for example TeX Live | Rendering generated manuscripts to PDF |
| Redis + PostgreSQL | Full PathLab web app and worker execution |
| OpenAI-compatible LLM relay or OpenRouter | Outline, literature, section writing, and refinement agents |
| PubMed / Semantic Scholar / OpenAlex keys | Higher-rate citation and literature retrieval |

For macOS development, install Python 3.12, Node, Redis, PostgreSQL, `uv`, and a
LaTeX distribution such as MacTeX or BasicTeX plus the required packages.

---

## 4. Python Environment

Paper Agent expects Python `>=3.12,<3.13` and is managed by `uv`.

Recommended setup:

```bash
cd pathlab/pathlab-client/server/paper_agent
uv sync
```

Verify the package entrypoint:

```bash
uv run pathlab-paper-agent --help
```

Run the test suite:

```bash
cd pathlab/pathlab-client/server/paper_agent
uv run pytest
```

Notes:

- Do not commit `.venv/`; it is intentionally ignored.
- Paper Agent dependencies are declared in `paper_agent/pyproject.toml`.
- Gateway imports remain stable through `server/gateway/paper_generation/`, but
  implementation changes belong in this package.

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

This script starts the PathLab web stack and serves the frontend through the
Gateway. After it starts, open:

```text
http://127.0.0.1:6100/papers
```

Default local admin credentials are currently:

```text
username: admin
password: admin
```

The experiment-task detail page also provides a "New Paper" entry. When opened
from a task, the web app routes to:

```text
/papers/new?task_id=<source-task-id>
```

The selected experiment is prefilled as the source task for the new paper.

---

## 6. Environment Files and Secrets

Never commit real secrets. Keep API keys in ignored files or shell environment.

### 6.1 PathLab backend env

The full web app reads the shared backend environment from:

```text
pathlab/pathlab-client/server/.env
```

Start from the project `.env.example` and configure the normal PathLab database,
Redis, JWT, and admin settings there.

### 6.2 Paper Agent local env

Standalone Paper Agent CLI/dev-server runs can load:

```text
pathlab/pathlab-client/server/paper_agent/.env
```

Start from:

```text
pathlab/pathlab-client/server/paper_agent/.env.example
```

The highest-precedence Paper Agent LLM override requires all three values:

```bash
PAPER_GEN_LLM_BASE_URL=https://your-openai-compatible-relay/v1
PAPER_GEN_LLM_API_KEY=replace-with-local-secret
PAPER_GEN_LLM_MODEL=gpt-5.5
```

Common optional values:

```bash
PAPER_GEN_LLM_REASONING_EFFORT=none
PAPER_GEN_LLM_STREAM=true
PAPER_GEN_LLM_TIMEOUT_S=300

SEMANTIC_SCHOLAR_API_KEY=
PUBMED_API_KEY=
PUBMED_EMAIL=your_email@example.com
OPENALEX_API_KEY=
OPENALEX_MAILTO=your_email@example.com
```

Lock down the local env file:

```bash
chmod 600 pathlab/pathlab-client/server/paper_agent/.env
```

### 6.3 External service credentials

| Secret/env | Required for | Where to put |
|---|---|---|
| `PAPER_GEN_LLM_BASE_URL` | OpenAI-compatible paper-generation relay | `paper_agent/.env` or service environment |
| `PAPER_GEN_LLM_API_KEY` | Paper-generation LLM calls | `paper_agent/.env` or service environment |
| `PAPER_GEN_LLM_MODEL` | Paper-generation model selection | `paper_agent/.env` or service environment |
| `OPENROUTER_API_KEY` | Fallback OpenRouter provider | shared backend env or service environment |
| `SEMANTIC_SCHOLAR_API_KEY` | Higher-rate Semantic Scholar retrieval | `paper_agent/.env` or service environment |
| `PUBMED_API_KEY` / `PUBMED_EMAIL` | Higher-rate PubMed retrieval | `paper_agent/.env` or service environment |
| `OPENALEX_API_KEY` / `OPENALEX_MAILTO` | OpenAlex retrieval | `paper_agent/.env` or service environment |

---

## 7. Standalone Commands

Run a whole paper-generation job:

```bash
cd pathlab/pathlab-client/server/paper_agent
uv run pathlab-paper-agent run \
  --paper-id paper_dev_001 \
  --uploads-dir /tmp/pathlab_uploads
```

Run one stage:

```bash
uv run pathlab-paper-agent run-stage \
  --paper-id paper_dev_001 \
  --stage collecting \
  --uploads-dir /tmp/pathlab_uploads
```

Start the dev-only HTTP server:

```bash
uv run pathlab-paper-agent serve \
  --host 127.0.0.1 \
  --port 6200 \
  --uploads-dir /tmp/pathlab_uploads
```

`serve` is for local development only. Production-style PathLab runs use
Gateway + TaskWorker.

---

## 8. Paper Generation Workflow

The Paper Agent creates one paper run from one or more completed experiment
tasks. A normal user-facing flow is:

```text
choose source tasks -> create paper -> generate outline -> approve outline
-> generate figures/tables/citations/sections -> validate/refine -> render PDF
-> download PDF or export bundle
```

### 8.1 Source tasks

Each paper must have at least one source task.

| Role | Meaning | Typical use |
|---|---|---|
| `main` | Main experiment | The primary task that supplies the central dataset, metrics, and results |
| `baseline` | Baseline comparison | A comparison model or method |
| `ablation` | Ablation experiment | A controlled variant, such as removing one module |
| `external_validation` | External validation | A separate cohort or external test task |

If only one task is selected, use `main`.

### 8.2 Templates

The public create API expects exactly one target template per paper run.

| Template id | Display name | Assets |
|---|---|---|
| `miccai` | MICCAI / LNCS | `llncs.cls`, `splncs04.bst` |
| `nature_scientific_reports` | Nature Scientific Reports | `wlscirep.cls`, `naturemag.bst` |

### 8.3 Pipeline stages

Paper runs use these stage labels:

```text
created -> collecting -> building_evidence -> outlining -> plotting
-> literature_review -> section_writing -> validating -> refining
-> rendering -> exporting -> completed
```

Failure and cancellation states:

```text
failed
cancelled
```

When the outline is generated, the run may pause as:

```text
awaiting_outline_approval
```

After the user approves the outline, the remaining stages continue in the
background.

---

## 9. User-Facing Paper Features

The web UI is designed for clinicians, students, teachers, and researchers who
may not want to edit raw LaTeX.

### 9.1 Outline approval

The run stops after outline generation so the user can review the paper
structure before the agent writes the full manuscript. If outline generation
fails, check the model API settings, network/proxy, firewall, and whether the
source task has enough experiment data.

### 9.2 Section editing

The section editor presents manuscript paragraphs directly instead of raw LaTeX
where possible. User edits are synchronized back into the section `.tex` files
and are picked up by the next render/export run.

Expected behavior:

- Edited words are marked in orange in the editor.
- Users can return from PDF preview to section editing for manual fixes.
- Tables and locked evidence blocks remain evidence-controlled.
- After editing, rerender the PDF before checking the final manuscript.

### 9.3 Citation management

The citation panel supports manually adding:

- DOI
- arXiv URL
- BibTeX entry

After a citation is added, the UI shows its generated key and title. Users can
copy the key and paste it into the desired manuscript location in the section
editor. During rerendering, the key is converted into a LaTeX citation and the
PDF reference order is recalculated.

Deleting a citation should:

1. ask the user for confirmation,
2. remove the citation from the citation library,
3. remove matching citation keys from section text,
4. mark downstream PDF/export artifacts stale,
5. require rerendering so the PDF and numbering update.

Required citations are references demanded by the outline or generation plan.
They are protected because removing them can leave generated claims without the
expected literature support.

### 9.4 Validation and refinement

Validation guards check whether the generated manuscript is supported by the
locked experiment evidence and citation state.

Common blocking guard names:

| Guard/problem | Meaning |
|---|---|
| `claim_guard` | A generated claim is not supported by the available evidence |
| `unsupported_baseline_comparison_claim` | The text claims baseline comparison, but no baseline source task supports it |
| `unsupported_external_validation_claim` | The text claims external validation, but no external-validation source task supports it |
| `citation_guard` | Required citation coverage or citation format is missing |
| `latex_guard` | The generated LaTeX cannot be compiled safely |

If automatic refinement is rejected, weaken or remove the unsupported sentence in
section editing, then rerender/export again.

### 9.5 PDF preview and downloads

The PDF preview tab shows the rendered manuscript. Users can:

- preview the PDF,
- select text and request local regeneration,
- return to section editing for manual changes,
- download only the PDF,
- download the PDF plus the full export bundle.

Download names should include:

```text
<paper-title>(<source-role>)-<source-task-id>.pdf
<paper-title>(<source-role>)-<source-task-id>.zip
```

For multi-source papers, include enough source-role/source-task information to
distinguish the main, baseline, ablation, and external-validation inputs.

### 9.6 Related papers on experiment tasks

Experiment task details show related paper records between execution progress
and realtime logs.

Expected pagination:

- the embedded related-paper area shows 3 papers per page,
- "View all papers" opens all papers generated from that experiment,
- the full related-paper list shows 10 papers per page.

---

## 10. Limits and Deletion Rules

Each source experiment task can be associated with at most 20 paper runs.

This limit counts paper run records, not only successfully completed PDFs.
Failed, pending, or incomplete paper runs can therefore consume the quota until
they are deleted.

Experiment task deletion has two modes:

| Mode | Behavior |
|---|---|
| Standard delete | Deletes the task and normal task outputs, but keeps generated papers |
| Delete task and all outputs | Deletes the task, its outputs, and papers generated from that task |

Deleting one paper run removes that paper record and its generated artifacts.

---

## 11. API Surface

The mounted Gateway route prefix is:

```text
/papers
```

Main endpoints:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/papers` | Create a paper run |
| `GET` | `/papers` | List paper runs |
| `GET` | `/papers/{paper_id}` | Get paper-run details |
| `PUT` | `/papers/{paper_id}/outline` | Update or approve the outline |
| `POST` | `/papers/{paper_id}/render-export` | Rerender edited sections and rebuild exports |
| `GET` | `/papers/{paper_id}/sections` | List section drafts |
| `PUT` | `/papers/{paper_id}/sections/{section_name}` | Update one section |
| `POST` | `/papers/{paper_id}/sections/{section_name}/regenerate` | Queue or run section regeneration |
| `GET` | `/papers/{paper_id}/citations` | View citation library |
| `POST` | `/papers/{paper_id}/citations` | Add manual citation |
| `DELETE` | `/papers/{paper_id}/citations/{key}` | Delete citation and sync sections |
| `GET` | `/papers/{paper_id}/regen/{regen_id}` | Poll regeneration job status |
| `POST` | `/papers/{paper_id}/regen/{regen_id}:reject` | Reject a regeneration candidate |
| `POST` | `/papers/{paper_id}/regen/{regen_id}:cancel` | Cancel a regeneration job |
| `DELETE` | `/papers/{paper_id}` | Delete a paper run |
| `GET` | `/papers/{paper_id}/files` | List or download paper files |
| `GET` | `/papers/{paper_id}/files/{path}` | Download a specific artifact |

---

## 12. Runtime Contract

The run directory is rooted under the configured uploads directory:

```text
uploads/paper_generation/<paper_id>/
```

The scaffold and pipeline write the stable v1 paper-run directory shape:

```text
paper_generation/<paper_id>/
  evidence/
  locked_blocks/
  drafts/
    sections/
  figures/
  tables/
  validation/
  final/<template>/
  exports/
```

Important generated artifacts include:

| Artifact | Purpose |
|---|---|
| `manifest.json` | Current run status, stage, artifacts, source tasks, regenerate jobs |
| `outline.json` | Generated and approved paper outline |
| `evidence/evidence_lock.json` | Evidence available to the manuscript |
| `drafts/sections/*.tex` | Editable section source |
| `validation/*_guard.json` | Validation guard reports |
| `final/<template>/main.pdf` | Rendered manuscript PDF |
| `exports/*.zip` | Downloadable source/output bundle |

The initial scaffold can run without LLM completion for integration testing, but
real outline, literature, section writing, refinement, and plotting behavior
requires a working LLM provider and valid source task evidence.

---

## 13. Troubleshooting

### 13.1 Outline generation fails

Check:

- `paper_agent/.env` exists for standalone runs or the service environment has
  the required `PAPER_GEN_LLM_*` values,
- `PAPER_GEN_LLM_BASE_URL`, `PAPER_GEN_LLM_API_KEY`, and
  `PAPER_GEN_LLM_MODEL` are all set together,
- the machine can reach the relay through the current proxy/firewall,
- the source experiment task has enough metrics, labels, tables, or analysis
  artifacts for evidence collection.

### 13.2 Validation rejects a candidate

This usually means the model wrote a claim the experiment record does not
support. For example, a sentence about external validation requires an
`external_validation` source task; a sentence about outperforming a baseline
requires a `baseline` source task.

Fix by adding the needed source task or editing the sentence to make a weaker,
evidence-bounded claim.

### 13.3 PDF keeps rendering or does not appear

Check:

- LaTeX is installed and available on `PATH`,
- template assets exist in `src/pathlab_paper_agent/templates/`,
- section files do not contain invalid LaTeX,
- citation keys exist in the citation library,
- referenced figures and tables exist,
- TaskWorker is running for full web-app execution.

### 13.4 PDF preview returns 401

The signed file URL token or login session may be stale. Refresh the page or log
in again, then reopen the paper detail page.

### 13.5 PDF text cannot be matched to source

PDF text selection can differ from source text because of line breaks,
hyphenation, ligatures, template formatting, and citation rendering. If exact
matching fails, use the section editor as the manual fallback.

### 13.6 Edited section is not reflected in the PDF

Confirm:

- the section update was saved,
- citation keys in the text are valid,
- `/papers/{paper_id}/render-export` completed successfully,
- the browser is showing the latest PDF artifact and not a stale preview.

---

## 14. Development References

Frontend pages:

```text
pathlab/pathlab-client/src/renderer/src/pages/PaperGenerationPage.tsx
pathlab/pathlab-client/src/renderer/src/pages/NewPaperPage.tsx
pathlab/pathlab-client/src/renderer/src/pages/PaperRunDetailPage.tsx
```

Backend worker entrypoints:

```text
pathlab/pathlab-client/server/task_worker/main.py
pathlab/pathlab-client/server/task_worker/jobs/paper_generation.py
```

Gateway bridge:

```text
pathlab/pathlab-client/server/gateway/paper_generation/
```

Template source notes:

```text
pathlab/pathlab-client/server/paper_agent/src/pathlab_paper_agent/templates/SOURCES.md
```
