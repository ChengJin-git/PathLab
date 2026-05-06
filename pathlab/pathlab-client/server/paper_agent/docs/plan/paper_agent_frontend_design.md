# Paper Agent Frontend Design

> 创建日期：2026-05-06
> 最后更新：2026-05-06（同步 backend prep plan 的单模板决策：去掉 PDF Preview 的 template switcher，create 向导改为单选）
> 状态：proposal
> 配套文档：`paper_agent_backend_prep_for_frontend.md`

This doc proposes the front-end design for the standalone paper-generation
agent. It is grounded in (a) PathLab's existing renderer codebase, (b) the
backend API already shipped under `pathlab_paper_agent`, and (c) UI patterns
from comparable long-running multi-stage agent products.

---

## 1. TL;DR

Reuse PathLab's existing renderer stack (React 18 + React Router v6 +
Tailwind 4 + Radix + TanStack Query). Rewrite `/papers/:paper_id` from the
current "status card + flat artifact list + stage log" into a three-column
workspace: **left stage checklist (Manus-style `todo.md`)**, **middle tabbed
artifact workspace (Devin-style)**, **right side panel for log + validation +
source tasks**. Gate the long autopilot run on a single Outline approval
step (Devin / Copilot Workspace pattern), and offer section-scoped
regeneration in the section editor (ChatGPT Canvas pattern). All other
stages run autopilot but expose a per-stage Re-run button.

The current `PaperRunDetailPage.tsx` is 119 lines, so rewriting it is cheap.

---

## 2. Tech-stack alignment

The PathLab renderer already ships everything we need; do not introduce new
top-level dependencies.

| Need | Existing source |
|------|----------------|
| Multi-stage progress | `components/taskDetail/ProgressSection.tsx` |
| Background task widget | `components/BackgroundTaskPanel.tsx` |
| Status badge maps | `constants/status.ts` (`TASK_DETAIL_STATUS_BADGES`) |
| Tabs / dialogs / popovers | Radix UI (already imported) |
| Modal shell | `components/ui/modal-shell.tsx` |
| Markdown + math rendering | `react-markdown` + KaTeX |
| Rich-text section editing | TipTap (already imported) |
| Server-state polling | `useQuery({ refetchInterval })` (already used in `PaperRunDetailPage.tsx:19`) |
| Icons | `lucide-react` |
| Download | `downloadApiFile()` from `api/client.ts` |

Net new components: outline JSON editor, LaTeX section editor with
selection-to-regenerate, figure grid, citation list, validation panel, PDF
preview iframe wrapper.

---

## 3. Routes

Current renderer has `/papers` (list + create combined) and
`/papers/:paper_id`. Proposal:

```
/papers                       List of paper runs
/papers/new                   Create wizard (split out from list)
/papers/:paper_id             Run detail (rewritten)
/papers/:paper_id?tab=...     Deep-link to a workspace tab
                              (?tab=outline | sections | figures | ...)
```

Splitting `/papers/new` gives the create wizard full canvas for source-task
preview, template selection, and `user_idea` input — currently the embedded
form gets cramped.

---

## 4. Information architecture for `/papers/:paper_id`

```
┌───────────────────────────────────────────────────────────────────────┐
│ PageHeader: title, status badge, Cancel, Export                       │
├──────────────┬───────────────────────────────────────┬────────────────┤
│ Stage        │ Artifact Workspace (Tabs)             │ Right Panel    │
│ Checklist    │  Outline | Sections | Figures |       │                │
│  (~ 240px)   │  Tables | Citations | Validation |    │  Stage log     │
│              │  PDF Preview                          │  (latest 8)    │
│  ✓ collect   │ ┌───────────────────────────────────┐ │                │
│  ✓ evidence  │ │                                   │ │  Validation    │
│  ⟳ outline   │ │  active tab content               │ │  summary       │
│  · plot      │ │                                   │ │                │
│  · litrev    │ │                                   │ │  Source tasks  │
│  · sections  │ │                                   │ │  (chips)       │
│  · validate  │ │                                   │ │                │
│  · refine    │ │                                   │ │  Cancel /      │
│  · render    │ │                                   │ │  Delete run    │
│  · export    │ └───────────────────────────────────┘ │                │
└──────────────┴───────────────────────────────────────┴────────────────┘
```

Breakpoints:

- `≥ 1280px`: full three-column layout.
- `768–1279px`: collapse right panel into a drawer toggled from header.
- `< 768px`: stack — checklist as accordion above tabs.

### 4.1 Left column — `<StageChecklist>`

Drives the "todo.md" pattern. Source of truth is `manifest.stage_log` plus
`current_stage`. Each row:

- icon: pending dot / running spinner / done check / failed `x`
- stage label (`PaperRunStage` enum, but rendered as friendly text)
- one-line latest message: take the last `stage_log` entry whose
  `stage === row.stage`
- hover: `Re-run` button (calls `POST /papers/:id/stages/:stage:run`)

Clicking a row sets `?tab=...` according to:

| stage | tab |
|-------|-----|
| collecting / building_evidence | Tables |
| outlining | Outline |
| plotting | Figures |
| literature_review | Citations |
| section_writing / refining | Sections |
| validating | Validation |
| rendering / exporting | PDF Preview |

### 4.2 Middle column — Artifact Workspace tabs

Each tab is a thin component over the GET `/papers/:id/files?path=...`
endpoint. Tabs are **always present** even if their stage hasn't run — empty
state shows "Not generated yet" with the responsible stage name.

| Tab | Stage producer | Content | Key interaction |
|-----|---------------|---------|----------------|
| **Outline** | `outlining` | `outline.json` rendered as editable tree (sections → paragraphs → required_cites) | "Approve outline" gate — pipeline does not advance to plotting/litrev/section_writing without approval. Edits go through `PUT /papers/:id/outline`. |
| **Sections** | `section_writing` / `refining` | LaTeX source + rendered preview, side-by-side. Left nav lists 8 sections (abstract → conclusion). | (a) `Regenerate section` button per section. (b) Highlight a paragraph → popover with `Regenerate this paragraph` + optional note input. (c) Diff viewer when comparing pre/post-refinement. |
| **Figures** | `plotting` | Card grid from `figures/manifest.json`: thumbnail, status badge (`ready` / `pending_generation` / `missing`), caption preview. | Click → modal with full image + caption. Only `ready` figures expose Download. |
| **Tables** | `building_evidence` | The 5 locked-block tables rendered as LaTeX + a fall-back HTML view. | Read-only — these are deterministic per the M3 contract. |
| **Citations** | `literature_review` | Two columns: `selected_refs` (used in paper) and `required_cites` (must be cited per outline). Each ref shows status against the A2 contract. | Read-only. Failed contract items are highlighted red and link to the section that omits them. |
| **Validation** | `validating` (and after `refining`) | 6 M10 guard cards (PHI, citation, metric, locked-block, table, figure). Plus M11 hybrid score and `warnings.md` rendering. | Click a guard failure → jumps to the offending section in the Sections tab with its line range highlighted. |
| **PDF Preview** | `rendering` / `exporting` | iframe loading `final/{template}/main.pdf` via the files endpoint, where `template` is the run's single `selected_templates[0]`. Below: `Download bundle` for `exports/{template}_bundle.zip`. | Falls back to "Compile pending" placeholder when `main.pdf` is missing. |

### 4.3 Right column — fixed side panel

- **Stage log**: the most recent 8 `stage_log` entries; `View all` opens a
  modal scrollable history.
- **Validation summary**: 6 guards as colored dots + M11 hybrid score
  one-liner ("HybridScore 87 (rubric 92, guards 1)").
- **Source tasks**: chips showing `task_id` and `role` from
  `config.source_tasks`. Clicking a chip opens the corresponding
  `/task/:task_id` page.
- **Destructive actions**: Cancel run (only when status in `pending` or
  `running`) and Delete run, both with Confirm modals.

---

## 5. User flow

```
/papers/new
  ├─ Pick source tasks (multi-select from /task-list)
  ├─ Pick template (single-select: miccai | nature_scientific_reports)
  ├─ Optional user_idea text area
  └─ POST /papers
     → redirect to /papers/:paper_id

/papers/:paper_id
  ├─ Stage 1 collecting       (deterministic, ~seconds; auto)
  ├─ Stage 2 building_evidence (deterministic, ~seconds; auto)
  ├─ Stage 3 outlining         (LLM)
  │     │
  │     └─ When done, UI surfaces "Approve outline" CTA on the Outline tab.
  │        The pipeline does NOT auto-advance. User can:
  │           • inspect the outline JSON tree
  │           • edit titles, paragraph briefs, required_cites
  │           • click Approve → triggers stages 4-9
  │
  ├─ Stage 4 plotting           (LLM + python; auto after approval)
  ├─ Stage 5 literature_review  (LLM)
  ├─ Stage 6 section_writing    (LLM)
  ├─ Stage 7 validating         (deterministic guards)
  ├─ Stage 8 refining           (LLM, M11 hybrid loop)
  ├─ Stage 9 rendering          (LaTeX docker compile)
  └─ Stage 10 exporting         (zip bundle + bundle dry-run)

At any time:
  • Hover a stage row → Re-run that stage
  • Sections tab → highlight a paragraph → Regenerate this paragraph
  • Header → Cancel run (Confirm modal, destructive)
```

The Outline approval gate is the only forced human-in-the-loop step. All
other stages are autopilot but reversible via per-stage Re-run.

---

## 6. New components

| Component | Reuses | New code |
|-----------|--------|---------|
| `<StageChecklist>` | ProgressSection icons | 9-stage list, per-row Re-run, deep-link to tab |
| `<OutlineEditor>` | — | JSON tree (consider `react-arborist` or hand-rolled), Approve gate |
| `<SectionEditor>` | TipTap, react-markdown | LaTeX ↔ rendered split, selection-to-regenerate popover, diff view |
| `<FigureGrid>` | Card | Thumbnail grid + status badges + lightbox modal |
| `<CitationList>` | Badge | `selected` vs `required` columns, A2-contract status |
| `<ValidationPanel>` | Card | 6 guard cards, expandable warnings.md |
| `<PdfPreview>` | — | iframe wrapper for the run's single template + fallback state |
| `<RegeneratePopover>` | Radix Popover | Note input + scope toggle (paragraph/section), submits to regenerate API |
| `<RunWorkspaceLayout>` | — | Three-column layout shell, breakpoint logic |

---

## 7. Backend API gaps

Current `api/papers.ts` covers list / get / delete / files. To support the
proposed UI, Gateway needs:

```
POST   /papers/:id/stages/:stage:run
       Body: {} (idempotent re-run of one stage)
       Response: 202 { paper_id, queued_stage }

POST   /papers/:id/sections/:name:regenerate
       Body: {
         target_paragraph?: number,
         user_note?: string,
         target_section?: string  # for cross-section moves
       }
       Response: 202 { paper_id, regen_id }

PUT    /papers/:id/outline
       Body: { outline: <OutlineJSON> }
       Response: 200 { paper_id, approved: bool }

POST   /papers/:id:cancel
       Response: 200 { paper_id, cancelled: bool }
```

The single-section regenerate logic is already implemented in
`pathlab_paper_agent/regenerate.py` (including the
`non_target_revisions_discarded` audit field added during M12b review). The
HTTP endpoint just needs to wire it to the worker.

The manifest itself can already be fetched as
`GET /papers/:id/files?path=manifest.json` — no new endpoint needed.

---

## 8. Phased rollout

### v1.5 — make the existing surface look like a product (~1 week)

- Split `/papers` (list) and `/papers/new` (create wizard).
- Rewrite `PaperRunDetailPage` into the three-column layout.
- `<StageChecklist>` read-only (no Re-run button yet).
- Tabs: Outline (read-only JSON view), Sections (read-only), PDF Preview,
  Validation, Stage log.
- No plan-approval gate — pipeline runs autopilot end-to-end.
- No new backend endpoints required.

Outcome: users can see structured progress, inspect each artifact, and
download the PDF / bundle without touching the manifest themselves.

### v2.0 — bidirectional interaction (~2 weeks)

- `<OutlineEditor>` + Approve gate (requires PUT `/papers/:id/outline`).
- `<SectionEditor>` with selection-to-regenerate popover (requires
  `/sections/:name:regenerate`).
- Per-stage Re-run buttons (requires `/stages/:stage:run`).
- Cancel run (requires `:cancel`).

Outcome: the agent feels collaborative — user shapes the outline, then
selectively regenerates anything that comes out wrong.

### v2.5 — beyond MVP (when needed)

- Integrate paper runs into the global `BackgroundTaskPanel` so users can
  navigate away and still see live progress.
- TipTap collaborative editing for multi-author review.
- (Future) Side-by-side comparison view of two paper runs targeting different templates — only relevant if the single-template policy is later relaxed.
- M11 critic-loop visualization (show each iteration's hybrid score over
  time as a small sparkline).

---

## 9. Reference UIs and what we copy from each

| Pattern | Source | Where it lives in our design |
|---------|--------|------------------------------|
| `todo.md` real-time checklist | Manus | Left column `<StageChecklist>` |
| Plan-first execution gate | Devin + Copilot Workspace + Claude Code Plan Mode | Outline tab Approve button |
| Tabbed artifact workspace | Devin (Shell / Browser / Editor / Planner) | Middle column 7 tabs |
| Highlight-to-regenerate | ChatGPT Canvas | `<SectionEditor>` selection popover |
| Selectable plan rows + "Regenerate selected" | Copilot Workspace | `<StageChecklist>` per-row Re-run |
| File-system-as-UI (artifacts persist on disk) | PaperOrchestra | We already have `GET /files?path=...` — keep treating manifest + locked blocks + sections as durable artifacts the user can diff externally |
| Critic loop visible (not a black box) | Sakana AI Scientist v2 | Validation tab shows M11 hybrid score per iteration; figures show retry history |

Anti-patterns we explicitly avoid:

- **Devin's cramped diff viewer** — give `<SectionEditor>` ≥ 800px middle
  column at large breakpoints; mobile pushes it to a single full-width
  view.
- **AI Scientist v1's log-only progress** — stage log is a *secondary*
  surface in the right panel, not the primary one.
- **Burying private artifacts in the public file list** — current
  `PaperRunDetailPage.tsx:74` correctly says "Private evidence and raw
  prompts are never shown here". Preserve that contract: only artifacts
  flagged `visibility=public` in the manifest are listed/downloadable.

---

## 10. Open questions

1. **Outline JSON schema for editing**: do we expose the full
   `OutlineJSON` (paragraphs + briefs + required_cites) or a simplified
   view? The full version is rich but error-prone to hand-edit.
2. **TipTap vs raw textarea for LaTeX sections**: TipTap is overkill for
   LaTeX source. We probably want a CodeMirror-style editor for the
   source pane and a separate render pane. Need to confirm whether
   pulling in CodeMirror is acceptable.
3. **Where does the Approve gate live in the worker**: today
   `complete_run()` runs all stages back-to-back. Adding a gate means the
   worker stops after `outlining` and waits for an approval marker file
   or DB flag. This is a backend design question that blocks v2.0.
4. **Multi-paper run concurrency**: should the global
   `BackgroundTaskPanel` aggregate paper runs alongside training jobs,
   or keep them in a paper-specific surface?

These are tracked as v2.0 prep work; v1.5 doesn't depend on any of them.
