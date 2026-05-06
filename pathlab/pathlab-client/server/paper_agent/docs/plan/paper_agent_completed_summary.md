# Paper Agent Completed Work Summary

> 创建日期：2026-05-06
> 最后更新：2026-05-06
> 状态：snapshot
> 配套文档：paper_agent_backend_prep_for_frontend.md

This document summarizes what the PathLab Paper Agent has already implemented.
It is intended as a handoff reference before frontend work and follow-up backend
contract work.

---

## 1. Current end-to-end capability

The paper agent can already run a full paper-generation pipeline from a PathLab
experiment bundle to LaTeX/PDF/export artifacts:

```text
collecting
-> building_evidence
-> outlining
-> plotting
-> literature_review
-> section_writing
-> validating
-> refining
-> rendering
-> exporting
-> completed
```

At a high level, the implemented system can:

- collect experiment artifacts into a paper run directory;
- build evidence locks, public evidence, tables, and immutable LaTeX locked
  blocks;
- generate a PaperOrchestra-style outline;
- generate or register paper figures;
- search and verify literature references;
- write final manuscript sections under evidence/citation/metric constraints;
- run deterministic validation guards;
- run a critic/revision refinement loop;
- render MICCAI or Nature Scientific Reports LaTeX;
- compile/export submission bundles.

The standalone runtime lives under:

```text
pathlab/pathlab-client/server/paper_agent/
```

Gateway and TaskWorker now keep thin compatibility bridges instead of owning the
paper-agent implementation.

---

## 2. Runtime, environment, and entrypoints

Completed:

- `paper_agent/` is a standalone `uv` project with its own `pyproject.toml`,
  `uv.lock`, `.python-version`, and `.env.example`.
- The service can be run independently for step-by-step testing.
- CLI/dev entrypoints are available:
  - `uv run pathlab-paper-agent --help`
  - `uv run pathlab-paper-agent run --paper-id ...`
  - `uv run pathlab-paper-agent run-stage --paper-id ... --stage ...`
  - `uv run pathlab-paper-agent serve --host 127.0.0.1 --port 6200`
- The default paper-generation LLM configuration is set to:
  - model: `gpt-5.5`
  - reasoning effort: `xhigh`
  - timeout: `300s`
- Paper-specific LLM env vars are isolated from the rest of PathLab:
  - `PAPER_GEN_LLM_BASE_URL`
  - `PAPER_GEN_LLM_API_KEY`
  - `PAPER_GEN_LLM_MODEL`
  - `PAPER_GEN_LLM_REASONING_EFFORT`
  - `PAPER_GEN_LLM_TIMEOUT_S`
- Literature-search provider env vars are supported:
  - `SEMANTIC_SCHOLAR_API_KEY`
  - `PUBMED_API_KEY`
  - `PUBMED_EMAIL`
  - `OPENALEX_API_KEY`
  - `OPENALEX_MAILTO`
- A dedicated LaTeX Docker image layout exists under `docker/paper-latex/`.
- Docker-backed PDF/export smoke verification passed on 2026-05-06:
  - `pathlab/paper-latex:latest` hello-world compile passed;
  - MICCAI and Nature Scientific Reports PDFs compiled with return code `0`;
  - bundle dry-run validation passed for both templates;
  - extracted PDF text contained References with no unresolved citation markers.

---

## 3. Filesystem and artifact contract

Completed run layout:

```text
uploads/paper_generation/{paper_id}/
  manifest.json
  config.json
  inputs/
  evidence/
  tables/
  locked_blocks/
  figures/
  citations/
  drafts/
    intro_rw_draft/
    sections/
    snapshots/
  validation/
  final/{template_id}/
  exports/
```

Completed storage/security work:

- `PaperRunPaths` is the single source of truth for run paths.
- `paper_id` validation prevents path traversal through run IDs.
- `/files` uses a strict allowlist plus manifest public/downloadable checks.
- Private artifacts are intentionally blocked, including:
  - `evidence/evidence_lock.private.json`
  - `inputs/source_tasks.json`
  - `drafts/intro_rw_draft/*`
  - validation guard internals
  - snapshots
- Public/downloadable artifacts include:
  - `manifest.json`
  - `config.json`
  - `drafts/outline.json`
  - `drafts/sections/*.tex`
  - `figures/*`
  - `tables/*`
  - `citations/refs.bib`
  - `citations/coverage_report.json`
  - `validation/warnings.md`
  - `final/{template_id}/*`
  - `exports/*.zip`

---

## 4. API and Gateway integration

Completed API surface:

| Endpoint | Status |
|---|---|
| `POST /papers` | create DB row, scaffold run, enqueue worker best-effort |
| `GET /papers` | paginated run list scoped to caller |
| `GET /papers/{id}` | run detail with artifacts, structured stage log, and validation summary |
| `GET /papers/{id}/sections` | public editable section list with hash/mtime |
| `POST /papers/{id}/sections/{name}/regenerate` | synchronous section regeneration |
| `DELETE /papers/{id}` | delete DB row and filesystem run |
| `GET /papers/{id}/files?path=...` | allowlisted file download |

Completed integration points:

- Gateway route compatibility is preserved through
  `server/gateway/paper_generation/routes.py`.
- TaskWorker compatibility is preserved through
  `server/task_worker/jobs/paper_generation.py`.
- New implementation code lives in `server/paper_agent/src/pathlab_paper_agent`.
- Frontend contract schemas are exported for public artifacts, stage logs,
  validation summaries, `drafts/outline.json`, and `figures/manifest.json`.
- `/files` requires both allowlist membership and public/downloadable manifest
  registration before serving frontend-visible artifacts.

Current template policy:

- Public API expects exactly one target template per paper-writing run.
- Supported user-facing choices:
  - `miccai`
  - `nature_scientific_reports`
- Internal renderer/export tests may still construct multi-template configs for
  regression coverage.

---

## 5. Evidence construction

Completed:

- Collector output is converted into a scrubbed evidence bundle.
- Private evidence is stored in `evidence/evidence_lock.private.json`.
- Public evidence is stored in `evidence/evidence_public.json`.
- Human-readable evidence summary is stored in `evidence/experimental_log.md`.
- Evidence generation supports role-tagged tasks:
  - main
  - baseline
  - ablation
  - external validation
- PHI/private source details are scrubbed before LLM-facing stages.
- Deterministic locked LaTeX blocks are generated:
  - `locked_blocks/dataset_block.tex`
  - `locked_blocks/method_block.tex`
  - `locked_blocks/results_block.tex`
  - `locked_blocks/external_block.tex`
  - `locked_blocks/metrics_macros.tex`
  - `locked_blocks/evidence_gaps.tex`
- Template-specific locked blocks are also generated under:
  - `locked_blocks/miccai/`
  - `locked_blocks/nature_scientific_reports/`
- Paper-ready tables are generated under `tables/`, including dataset and result
  tables when evidence exists.

---

## 6. PaperOrchestra-style agents

The implementation follows the PaperOrchestra multi-agent structure, with
PathLab-specific evidence locks and deterministic guards.

### 6.1 Outline Agent

Completed:

- Prompt: `prompts/outline_v1.txt`
- Agent: `agents/outline_agent.py`
- Produces `drafts/outline.json`.
- Preserves PaperOrchestra fields:
  - `plotting_plan`
  - `macro_lit_search`
  - `micro_lit_clusters`
  - `section_plan`
- Adds PathLab extensions:
  - selected templates
  - claim plan
  - table plan
  - guard requirements
  - template styles
- Reads evidence, tables manifest, figures manifest, idea, and template style.
- PHI/private identifiers are checked before prompt/output use.

### 6.2 Plotting Agent

Completed:

- Prompt: `prompts/plotting_caption_v1.txt`
- Agent: `agents/plotting_agent.py`
- Produces `figures/manifest.json`.
- Supports deterministic plotting for available experiment artifacts.
- Registers ready figures with:
  - `figure_id`
  - `path`
  - `caption`
  - `status`
- Section writer is required to include every ready figure.

### 6.3 Literature Review Agent

Completed:

- Prompts:
  - `prompts/lit_search_v1.txt`
  - `prompts/intro_rw_draft_v1.txt`
- Agent: `agents/literature_review_agent.py`
- Stage: `stages/literature.py`
- Search sources:
  - Semantic Scholar
  - PubMed
  - OpenAlex
- LLM expands outline literature fields into concrete search queries.
- Deterministic search clients execute API queries.
- Candidate references are verified and deduplicated.
- Final outputs:
  - `citations/discovery_pool.json`
  - `citations/verified_pool.json`
  - `citations/selected_refs.json`
  - `citations/required_cites.json`
  - `citations/coverage_report.json`
  - `citations/refs.bib`
  - `drafts/intro_rw_draft/introduction.tex`
  - `drafts/intro_rw_draft/related_work.tex`
- Coverage gate enforces:
  - required cites are used;
  - no orphan citation keys;
  - selected reference coverage threshold.
- Manual candidate seeding is supported through `discovery_pool.json` when an
  external API is rate-limited.

### 6.4 Section Writing Agent

Completed:

- Prompt: `prompts/section_writing_v1.txt`
- Agent: `agents/section_writing_agent.py`
- Writes final section files under `drafts/sections/`.
- Uses `drafts/intro_rw_draft/*` as source material only.
- Enforces placeholder contracts:
  - citations: `[CITE:key]`
  - metrics: `{{m:metric_key}}`
- Renders placeholders deterministically to LaTeX citations and locked metric
  values.
- Rejects raw `\cite{}` before rendering.
- Rejects raw metric-like numbers before rendering.
- Repairs missing required locked-block inputs when safe.
- Enforces that ready figures and known tables are included correctly.
- Uses template-specific `section_guidelines` from `style.json`.

### 6.5 Content Refinement Agent

Completed:

- Prompts:
  - `prompts/refinement_critic_v1.txt`
  - `prompts/refinement_revise_v1.txt`
- Agent: `agents/content_refinement_agent.py`
- Stage: `stages/refining.py`
- Runs critic -> revise -> deterministic guards.
- Uses a hybrid score combining:
  - rubric scores;
  - guard status;
  - guard error count.
- Saves snapshots before candidate revisions.
- Rejects revisions that fail deterministic guards.
- Writes `validation/refinement_log.json`.

---

## 7. Citation chain

Completed citation modules:

- `citations/semantic_scholar.py`
- `citations/pubmed.py`
- `citations/openalex.py`
- `citations/verifier.py`
- `citations/ref_selector.py`
- `citations/bib_generator.py`
- `citations/coverage_gate.py`
- `citations/orphan_cite_gate.py`

Completed behavior:

- Semantic Scholar Graph API search client.
- PubMed E-utilities search + summary client.
- OpenAlex works search client.
- Candidate normalization into `CitationCandidate`.
- Dedup by:
  - S2 paper ID;
  - DOI;
  - PMID;
  - OpenAlex ID;
  - normalized title.
- Year cutoff support.
- Title-similarity verification for claimed titles.
- Stable BibTeX generation.
- No-network deterministic fixtures for tests.

---

## 8. Templates and venue-specific writing

Completed templates:

- `templates/miccai/`
  - LNCS-style MICCAI rendering.
- `templates/nature_scientific_reports/`
  - Scientific Reports rendering with `wlscirep` style.

Completed template behavior:

- Template registry is centralized in `templates/registry.json`.
- Each template has `style.json`.
- Each template defines:
  - section order;
  - required sections;
  - style constraints;
  - section-level writing guidelines.
- Section guidelines are written for:
  - abstract;
  - introduction;
  - related work;
  - methods;
  - experiments;
  - results;
  - discussion;
  - conclusion.
- Nature-specific rendering rules include unnumbered sections and abstract
  placement before `\begin{document}`.
- MICCAI and Nature can be tested independently; public API generation is
  currently single-template to avoid mixed writing style.

---

## 9. Validation and safety guards

Completed deterministic guards:

- `metric_guard`
- `identifier_guard`
- `latex_guard`
- `citation_guard`
- `claim_guard`
- `consistency_guard`

Completed safety behavior:

- Private paths, case IDs, task IDs, source IDs, and raw provenance are blocked
  from LLM prompts and outputs.
- Metric values must originate from evidence lock placeholders.
- Citation keys must originate from selected/verified references.
- Locked blocks prevent the LLM from rewriting dataset/model/result facts.
- Figure/table contracts prevent invented asset references.
- Validation warnings are summarized in `validation/warnings.md`.

---

## 10. Rendering, compilation, and exports

Completed:

- Jinja2-based LaTeX renderer for venue templates.
- Final output directories:
  - `final/miccai/`
  - `final/nature_scientific_reports/`
- Template assets are copied into each final directory.
- Sections, tables, figures, refs, and locked blocks are assembled into final
  LaTeX trees.
- Docker-based LaTeX compile support exists.
- `latexmk -pdf` is used for non-interactive compilation.
- Export bundles are written under `exports/`.
- Bundle validation extracts ZIPs safely and dry-runs LaTeX compilation.
- Export logic excludes private/internal artifacts from submission bundles.

---

## 11. Testing and verification

Completed test coverage areas:

- Gateway API/interface tests.
- Storage and allowlist tests.
- Collector and evidence tests.
- Locked-block golden tests.
- Outline agent tests.
- Plotting tests.
- Citation chain tests.
- Literature Review Agent tests.
- Section Writing Agent tests.
- Deterministic guard tests.
- Refinement loop tests.
- Template rendering/export tests.
- End-to-end no-network smoke pipeline.

Last verified full local test run:

```text
uv run pytest -q
259 passed, 1 skipped
```

Lint:

```text
uv run ruff check src tests
All checks passed
```

---

## 12. Historical formal run

A formal model preview run has been completed with `gpt-5.5` + `xhigh` using a
virtual WSI-quality experiment fixture.

Produced artifacts included:

- MICCAI final PDF;
- Nature Scientific Reports final PDF;
- MICCAI export bundle;
- Nature Scientific Reports export bundle;
- passing deterministic guards;
- successful LaTeX compile.

This run was useful as a quality preview, but the current public API policy is
single-template per user-selected paper run.

---

## 13. Completed frontend-facing pieces

Already available for frontend consumption:

- create/list/detail paper-run routes;
- section list route;
- section text, content hash, editable flag, updated time;
- file download route with public/private boundary;
- artifact index in manifest;
- stage log entries;
- rendered PDFs and export ZIP artifacts when pipeline reaches rendering/exporting.

Still not completed for frontend contract hardening:

- `GET /papers/{id}.validation_summary` is still not populated.
- `stage_log` does not yet expose `started_at`, `finished_at`, or duration.
- `OutlineDocument` and `FigureManifest` are not yet exported as public Pydantic
  schemas for frontend type generation.
- Outline approve/pause/resume is not implemented.
- Regenerate is still synchronous.
- Per-stage rerun endpoint is not implemented.
- Cancel endpoint is not implemented.

These remaining items are tracked separately in
`docs/plan/paper_agent_backend_prep_for_frontend.md`.
