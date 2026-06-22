# PathScientist Platform Master Plan

> Date: 2026-04-05
> Status: Active master roadmap
> Role: This is the primary entry document for PathScientist planning
> Supersedes as the main navigation doc:
> - `server/backend/pathscientist/docs/plan/2026-04-02-auto-research-platform-design.md`
> - `server/backend/pathscientist/docs/plan/2026-04-02-auto-research-platform-implementation.md`
> - `server/backend/pathscientist/docs/plan/2026-04-02-openhands-pathscientist-refactor-plan.md`
> Related detailed plans:
> - `server/backend/pathscientist/docs/plan/2026-04-03-code-agent-implementation-plan.md`
> - `server/backend/pathscientist/docs/plan/2026-04-03-pathscientist-code-agent-gap-closure-plan.md`
> - `server/backend/pathscientist/docs/plan/2026-04-04-pathscientist-conversation-persistence-plan.md`
> - `server/backend/pathscientist/docs/plan/2026-04-05-vendor-openhands-sdk-plan.md`

## 1. Why This Document Exists

PathScientist planning has evolved in three layers:

1. product vision for an autonomous research platform,
2. an older implementation path based on `auto_research`,
3. an OpenHands-oriented refactor path.

Now that the PathScientist code agent foundation already exists under
`server/backend/pathscientist/`, those three documents should no longer be
treated as three parallel directions.

This document merges them into one current answer to four questions:

- what PathScientist is,
- what is already built,
- what still needs to be built,
- and in what order the remaining platform should be completed.

## 2. Product Definition

PathScientist is an OpenHands-based autonomous research platform for
computational pathology.

Its target user experience is:

1. a researcher gives a goal, dataset context, and constraints,
2. the system grounds itself in relevant methods and baselines,
3. the code agent edits and runs experiments in a persistent workspace,
4. the platform preserves artifacts, claims, and evidence across iterations,
5. and the system generates a report or paper draft backed by citations and run
   evidence.

In short:

> PathScientist is not just a code agent. It is a research operating system
> built around code execution, experiment memory, and evidence-grounded writing.

## 3. Architectural Decision

### 3.1 Canonical Codebase

The primary PathScientist implementation lives in:

- `server/backend/pathscientist/`

This is now the canonical runtime and product seed. New core work should target
this package first.

### 3.2 What Remains Valid From The OpenHands Refactor Direction

The strategic idea from the old OpenHands refactor plan remains correct:

- OpenHands should provide the agent-runtime model,
- PathScientist should remain a vertical research layer rather than a generic
  coding assistant,
- workspace, tools, conversation state, and execution contracts should follow
  OpenHands-like semantics.

### 3.3 What Has Changed Since The Old Refactor Plan

The old plan assumed a separate OpenHands fork at `../pathlab-openhands/`.
That is no longer the primary build path.

Current reality is:

- PathScientist already has a working in-repo package,
- the immediate need is platform completion, not repository relocation,
- and any future SDK vendoring or deeper loop customization should happen as an
  enabling infrastructure track inside the current package.

### 3.4 What The Old `auto_research` Tree Means Now

`server/backend/auto_research/` is no longer the mainline target architecture.
It remains:

- a reference source for reusable ideas and legacy behavior,
- a place to mine missing logic,
- but not the place where PathScientist should keep growing.

## 4. Consolidated Architecture

The merged platform architecture is:

### Layer 1: Project / Workspace / Session Layer

Responsibilities:

- persistent workspace and git history,
- session identity and conversation identity,
- experiment output directories,
- sandbox/runtime contract,
- resumable session state.

Current status:

- mostly implemented in the code agent foundation,
- still needs final hardening for resume correctness and API-facing session
  lifecycle.

### Layer 2: Code Agent Execution Layer

Responsibilities:

- edit files,
- validate scripts,
- run quick checks and full experiments,
- ratchet commits and reverts,
- inspect workspace and metrics,
- operate safely across concurrent sessions.

Current status:

- this is the most complete part of PathScientist today.

### Layer 3: Research Orchestrator Layer

Responsibilities:

- turn a user goal into stages,
- manage stop conditions and iteration budgets,
- coordinate literature grounding, coding, experimentation, and synthesis,
- allow human checkpoints.

Current status:

- not yet platform-complete,
- this is the next major functional gap after code-agent hardening.

### Layer 4: Evidence / Memory Layer

Responsibilities:

- persist run artifacts and logs,
- connect code diffs to metrics and conclusions,
- preserve failed and successful experiment history,
- expose inspectable records for later analysis and reporting.

Current status:

- partially seeded by workspace history and conversation persistence,
- but not yet a first-class research evidence model.

### Layer 5: Paper / Report Generation Layer

Responsibilities:

- summarize grounded findings,
- link claims to experiments and citations,
- generate report markdown and later LaTeX-ready assets,
- present limitations and reproducibility context.

Current status:

- still largely future work.

### Layer 6: Product Surface Layer

Responsibilities:

- CLI,
- API,
- streaming status,
- session management,
- later web UI.

Current status:

- basic CLI exists,
- platform-grade API and UI still need to be built.

## 5. Current State Of PathScientist

### 5.1 What Is Already Built

PathScientist already has a usable code-agent foundation:

- OpenHands-based agent assembly and tool loop
- workspace abstraction with git-backed ratchet behavior
- domain skills and templates for pathology tasks
- custom tools for validation, experiment execution, metrics, and workspace
  inspection
- session isolation and session-scoped tool dependency resolution
- checkpointing primitives
- conversation persistence direction and tests

This means the project has already crossed the "can the agent write and run
code?" threshold.

### 5.2 What Is In Progress But Not Fully Closed

The following tracks are active but should be treated as hardening work rather
than new platform layers:

- runtime correctness gap closure
- conversation persistence and resume correctness
- session-safe history / event inspection
- optional OpenHands SDK vendoring for future loop customization

### 5.3 What Is Still Missing At Platform Level

The main missing capabilities are no longer "basic code agent" items. They are:

- research-stage orchestration,
- evidence and artifact modeling,
- literature-backed grounding,
- paper/report generation,
- API and product surfaces.

## 6. Legacy Plan Mapping

### 6.1 `2026-04-02-auto-research-platform-design.md`

Keep:

- overall product vision,
- user journeys,
- layered architecture,
- research-agent role decomposition,
- evidence-before-narrative philosophy.

Supersede:

- any assumption that the platform still needs to be defined from zero.

This document remains the best source for "what PathScientist should become",
but not for "where current implementation work should go next".

### 6.2 `2026-04-02-auto-research-platform-implementation.md`

Keep:

- the capability backlog:
  - normalized session contracts,
  - unified sandbox semantics,
  - artifact and evidence persistence,
  - staged research flow,
  - evidence-driven paper generation.

Supersede:

- the assumption that `server/backend/auto_research/` is still the main target
  package.

This document is now a source of platform backlog items, not the primary
execution plan.

### 6.3 `2026-04-02-openhands-pathscientist-refactor-plan.md`

Keep:

- OpenHands-first direction,
- PathScientist-as-vertical-package reasoning,
- migration-in-layers mindset,
- runtime-contract discipline.

Supersede:

- the assumption that the project should now move into a separate OpenHands
  fork before continuing feature work.

This document should now be read as an architectural rationale document, not as
the main workstream.

## 7. Master Roadmap

### Phase 0: Code Agent Foundation

Status: mostly complete

Target outcome:

- one repo-scale code agent can inspect, edit, validate, run, and ratchet
  experiments in a persistent workspace.

Included work:

- agent runtime
- workspace contract
- domain skills/templates
- experiment tools
- session isolation

Remaining closure items:

- finish code-agent gap closure
- finish conversation persistence correctness
- make resume, inspection, and session lifecycle robust enough for higher-level
  orchestration

### Phase 1: Research Session And Orchestrator

Status: next major milestone

Target outcome:

- PathScientist can manage a full research session rather than only a coding
  conversation.

Must include:

- research objective contract
- project/session/run model
- explicit stage transitions
- stop conditions and human approval points
- orchestration across grounding, coding, experimentation, and synthesis

This phase turns the current code agent into a research operator.

### Phase 2: Evidence And Artifact System

Status: required after orchestrator basics exist

Target outcome:

- every run produces an inspectable evidence record.

Must include:

- run manifest
- artifact index
- metrics lineage
- claim-to-evidence links
- diff/log/metric association
- failure memory, not only success memory

This phase makes PathScientist scientifically auditable instead of merely
autonomous.

### Phase 3: Literature Grounding

Status: after orchestrator + evidence basics

Target outcome:

- the system can ground planning and writing in retrieved literature and known
  baselines.

Must include:

- paper ingestion and indexing
- structured baseline extraction
- citation-aware memory
- prompt/context injection tied to concrete sources

This phase prevents the platform from becoming a prompt-only optimizer.

### Phase 4: Report And Paper Generation

Status: after evidence and grounding are usable

Target outcome:

- a session can produce a report or draft paper with experiment-backed claims.

Must include:

- report schema
- section-by-section draft generation
- figure/table references
- limitations and reproducibility notes
- markdown export first, richer paper export later

This phase converts experiment history into research output.

### Phase 5: Product Surfaces

Status: parallelizable after Phase 1 starts, but should not outrun the core

Target outcome:

- PathScientist is operable as a platform rather than only as a local dev tool.

Must include:

- stable API
- session start/stop/resume endpoints
- streaming event surface
- project and run inspection views
- later web UI

### Phase 6: Infrastructure Independence

Status: optional enabling track

Target outcome:

- PathScientist can control its own agent loop and upstream dependencies.

Examples:

- vendoring the OpenHands SDK subset
- customizing stop-to-ask behavior
- task-mode switching
- deeper conversation-loop modifications

This is important, but it is an enabling track, not the main product milestone.

## 8. Recommended Immediate Sequence

Given the current project state, the recommended next build order is:

1. finish Phase 0 hardening
   - close runtime correctness gaps
   - close persistence/resume gaps
   - make session lifecycle trustworthy
2. build a minimal research orchestrator
   - objective intake
   - staged session state
   - experiment loop control
3. add a first-class evidence model
   - run artifacts
   - metrics lineage
   - claim/evidence links
4. add literature grounding
   - baseline retrieval
   - citation memory
5. build report/paper generation
   - evidence-backed markdown first
6. expose platform surfaces
   - API, streaming, and later UI

This sequence reflects the current reality:

- the code agent is already the strongest part of the system,
- the next bottleneck is no longer code editing,
- the next bottleneck is platform orchestration and evidence flow.

## 9. Planning Rules Going Forward

From this point forward:

- this master plan is the top-level navigation document,
- phase-specific work should be split into dedicated implementation plans,
- old plans should be referenced for context, not treated as competing roadmaps,
- no new mainline feature work should target `server/backend/auto_research/`,
- and any infrastructure-heavy track such as SDK vendoring should stay clearly
  separated from product-capability milestones.

## 10. Definition Of Success

PathScientist should be considered platform-complete for Phase 1 when it can do
all of the following in one continuous project flow:

1. accept a research objective and constraints,
2. ground itself in relevant methods or baselines,
3. edit and run experiments in a persistent workspace,
4. preserve artifacts and evidence across iterations,
5. stop or continue based on explicit success criteria,
6. and generate a report or paper draft tied to evidence.

Until that happens, the code agent should be treated as the foundation, not the
finished product.
