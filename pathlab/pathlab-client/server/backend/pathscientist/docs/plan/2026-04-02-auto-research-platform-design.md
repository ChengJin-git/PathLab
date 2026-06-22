# Auto Research Platform Design

> Date: 2026-04-02
> Status: Draft approved in conversation; ready for implementation planning
> Scope: PathLab `server/backend/auto_research/*`
>
> Update 2026-04-05:
> This document is retained as a product-vision reference.
> The active top-level roadmap is now
> `server/backend/pathscientist/docs/plan/2026-04-05-pathscientist-master-plan.md`.
> Read this file for overall vision and target architecture, but use the master
> plan as the primary navigation entry.

## 1. Vision

Build an OpenHands-style autonomous coding and execution platform for computational pathology research that can:
- understand a research goal,
- gather literature and baselines,
- write or modify experiment code,
- run experiments inside reproducible sandboxes,
- analyze outcomes and decide next steps,
- and generate a paper draft with citations, figures, tables, and evidence links.

This is not just an "auto experiment runner". It is a research workspace, experiment operator, and paper drafting system built around a persistent project and evidence model.

## 2. Product Definition

A concise definition for Phase 1:

> An autonomous research lab for computational pathology that turns a research objective into code changes, experiment runs, evidence summaries, and a paper draft.

The platform should feel like a combination of:
- OpenHands / OpenCode for persistent coding sessions, workspace operations, and sandboxed execution,
- Agent Laboratory for staged research workflow,
- AI Scientist for result-driven experiment loops and paper generation,
- GPT Researcher for citation-backed report writing.

## 3. External Inspirations And What To Borrow

### OpenHands

Borrow:
- persistent workspace and session model,
- agent runtime that can read/write files and execute commands,
- multi-surface entrypoints: API, CLI, and later UI,
- a strong contract between tools, sandbox, and workspace.

Do not copy:
- a fully generic agent product before the research loop works.

Reference: https://github.com/OpenHands/OpenHands

### Agent Laboratory

Borrow:
- the staged workflow: literature review, experimentation, report writing,
- agent role separation instead of one giant prompt,
- explicit human review checkpoints.

Do not copy:
- a purely assistant-style flow that stops short of a productized platform.

Reference: https://github.com/SamuelSchmidgall/AgentLaboratory

### AI Scientist / AI Scientist-v2

Borrow:
- iterative experiment search driven by metrics,
- ratchet behavior: keep improvements, roll back bad changes,
- paper generation as a first-class output,
- later, tree-search style exploration for broader search.

Do not copy:
- Phase 1 over-commitment to free-form search without guardrails.

References:
- https://github.com/SakanaAI/AI-Scientist
- https://github.com/SakanaAI/AI-Scientist-v2

### GPT Researcher

Borrow:
- citation tracking,
- source-backed report generation,
- structured research memory.

Reference: https://github.com/assafelovic/gpt-researcher

### MLAgentBench / AutoRA

Borrow:
- task and evaluation environment design,
- explicit state objects for research workflows,
- reproducibility and traceability as first-class concerns.

References:
- https://github.com/snap-stanford/MLAgentBench
- https://github.com/AutoResearch/autora

## 4. Goals

### Core Goals

- Turn a research objective into a bounded, inspectable research session.
- Maintain a persistent code workspace rather than a one-shot script output.
- Run experiments through one unified sandbox contract across Apptainer, Docker, and local fallback.
- Preserve experiment lineage: plan, code diff, runtime config, logs, metrics, artifacts, claims.
- Generate a paper draft from evidence rather than from prompt-only synthesis.
- Support both autonomous mode and human-in-the-loop review.

### Non-Goals For Phase 1

- A fully generic agent marketplace.
- A multi-tenant enterprise platform with complex roles and billing.
- A domain-agnostic scientific discovery system across all sciences.
- Open-ended free-form multi-agent societies.
- Massive parallel search infrastructure.

## 5. Primary User Journeys

### Journey A: Baseline Reproduction

A researcher provides a paper or method target and a dataset. The platform:
- identifies the expected baseline recipe,
- prepares or patches the training code,
- runs the baseline,
- validates outputs,
- records reproduction gaps,
- and writes a reproducibility-focused report.

### Journey B: Performance Improvement

A researcher provides an existing baseline repository and an optimization goal. The platform:
- inspects the current codebase,
- proposes experiment directions,
- edits code or config,
- runs experiments iteratively,
- keeps improvements,
- and writes a results-oriented paper draft.

### Journey C: Research Draft Generation

A researcher provides a completed or partially completed experiment set. The platform:
- aggregates metrics, logs, tables, and figures,
- links claims to evidence and citations,
- drafts title, abstract, methods, results, discussion, and limitations,
- and exports Markdown plus LaTeX-ready assets.

## 6. Design Principles

- Evidence before narrative.
- One workspace per project, many runs per workspace.
- One sandbox contract, many backends.
- Keep the first version narrow and reliable.
- Every claim in a report should point to either a citation or an experiment artifact.
- A failed experiment is still valuable memory.
- The platform should preserve enough trace to replay or audit a result.

## 7. System Architecture

The platform should be split into five layers.

### Layer 1: Project And Workspace Layer

Responsibilities:
- project definition,
- dataset and resource mounting,
- persistent workspace directories,
- git branch / commit / patch history,
- session and run ownership.

This layer is the stable execution shell around all research activity.

### Layer 2: Research Orchestrator Layer

Responsibilities:
- convert a user objective into staged work,
- delegate tasks to specialized agents,
- manage stop conditions, approval points, and iteration budget,
- coordinate transitions from literature to experimentation to paper drafting.

This is the control plane of the system.

### Layer 3: Execution Layer

Responsibilities:
- write files,
- execute commands,
- run training jobs,
- capture stdout/stderr and artifacts,
- enforce a common runtime contract regardless of sandbox backend.

This layer must hide backend-specific details from agents.

### Layer 4: Research Memory And Evidence Layer

Responsibilities:
- store literature findings,
- record experiment plans and outcomes,
- capture failures and learned heuristics,
- build claim-to-evidence links,
- maintain paper draft state.

This is what lets the system improve within and across sessions.

### Layer 5: Presentation Layer

Responsibilities:
- CLI experience for developers,
- API for integration and orchestration,
- later a web UI for projects, runs, artifacts, and paper drafts,
- export formats such as Markdown, LaTeX, and zip bundles.

## 8. Core Agents

### Research Director

Owns the global plan for a session:
- interprets the user objective,
- sets success criteria,
- chooses the next stage,
- decides whether to continue exploring or stop.

### Literature Agent

Owns external grounding:
- search, filter, and summarize literature,
- identify baselines and evaluation norms,
- extract methods, metrics, datasets, and implementation hints,
- maintain citation records.

### Experiment Planner

Owns the experiment backlog:
- proposes candidate experiments,
- prioritizes by expected value and cost,
- ensures diversity across explored directions,
- enforces stopping criteria and budget usage.

### Code Agent

Owns workspace modifications:
- reads the repository,
- edits code and config,
- writes new files when needed,
- applies patch-style changes when possible,
- prepares runnable experiments.

### Runner

Owns actual execution:
- translates the experiment contract into backend-specific execution,
- mounts data and outputs,
- captures logs and metrics,
- returns structured execution results.

### Result Analyst

Owns interpretation:
- compare runs,
- detect regressions and invalid runs,
- extract findings from metrics and logs,
- decide whether an outcome supports or rejects a hypothesis.

### Paper Writer

Owns narrative generation:
- transform evidence into sections,
- maintain citation fidelity,
- create figure/table manifests,
- draft paper and report outputs.

## 9. Core Domain Model

The current implementation should evolve toward these entities.

### Project

A long-lived research container with:
- objective,
- dataset bindings,
- workspace root,
- domain configuration,
- export settings.

### ResearchSession

One end-to-end attempt to solve a project objective.

Fields should include:
- session id,
- project id,
- objective,
- locale,
- max iterations,
- budget limits,
- current phase,
- status.

### ExperimentSpec

A proposed experiment before execution.

Fields should include:
- hypothesis,
- rationale,
- planned code changes,
- expected metric impact,
- runtime budget,
- required inputs and outputs.

### ExperimentRun

A single execution record.

Fields should include:
- run id,
- experiment spec id,
- workspace revision,
- sandbox backend,
- env and mounts,
- logs,
- metrics,
- status,
- duration,
- artifact pointers.

### Artifact

A durable output such as:
- model checkpoint,
- metrics json,
- figure,
- table,
- patch,
- run log,
- generated script.

### Citation

A literature source with metadata and usage context.

### Claim

A statement used in a report or paper that must link to supporting evidence:
- citations,
- experiment runs,
- tables,
- figures.

### PaperDraft

A versioned document state that stores:
- title,
- abstract,
- section bodies,
- inserted figures/tables,
- unresolved TODOs,
- export status.

## 10. Primary Workflow

The Phase 1 workflow should be fixed and inspectable.

### Step 1: Intake

Inputs:
- research objective,
- dataset bindings,
- target metric,
- iteration budget,
- paper/report mode,
- optional baseline repo or paper.

Outputs:
- project/session record,
- normalized execution config,
- workspace setup.

### Step 2: Grounding

Actions:
- literature retrieval,
- baseline identification,
- metric and protocol extraction,
- risk and feasibility notes.

Outputs:
- literature findings,
- citation set,
- baseline shortlist,
- initial experiment backlog.

### Step 3: Experiment Loop

Per iteration:
- select one experiment,
- modify workspace,
- run through sandbox,
- verify outputs,
- analyze outcome,
- keep or revert changes,
- update memory and backlog.

This is the heart of the system.

### Step 4: Evidence Consolidation

Actions:
- compare top runs,
- capture best, failed, and ablation evidence,
- prepare figure and table manifests,
- normalize citations and claims.

### Step 5: Paper Generation

Actions:
- draft title and abstract,
- draft methods from code and run context,
- draft experiments/results from evidence,
- draft discussion, limitations, and future work,
- export Markdown and LaTeX-ready materials.

### Step 6: Human Review

Approval points:
- experiment plan review,
- final report or paper review,
- optional intervention after major failures.

## 11. Workspace And Sandbox Contract

This is the most important technical contract to stabilize.

Every execution backend must honor the same runtime model:
- one workspace root,
- one command execution root,
- explicit read-only data mounts,
- explicit read-write output mounts,
- explicit environment variables,
- structured result capture.

The contract should define:
- `workspace_dir`: where the agent reads and writes code,
- `run_cwd`: where `execute_command()` starts,
- `data_mounts`: host path to in-environment path mapping,
- `output_dir`: canonical output destination,
- `env_vars`: normalized runtime variables,
- `rw_paths`: writable directories inside the environment,
- `artifacts`: named output manifest.

Rules:
- Apptainer, Docker, and local fallback must all expose the same semantic paths.
- Interactive mode and batch mode must share the same workspace contract.
- The agent prompt must not mention paths that the backend does not actually mount.

## 12. Memory, Evidence, And Citation Design

The system should record not just events, but structured research memory.

### Research Memory Buckets

- literature memory: papers, methods, metrics, datasets,
- experiment memory: what was tried and what happened,
- failure memory: repeated errors and invalid directions,
- know-how memory: reusable heuristics and code patterns,
- paper memory: draft sections and unresolved writing TODOs.

### Evidence Links

Each important claim should point to at least one of:
- a citation,
- a run metric,
- a figure,
- a table,
- a log excerpt,
- a code diff.

This makes the paper generator grounded rather than purely generative.

## 13. Paper Generation Pipeline

Paper generation should be evidence-driven, not a single end-of-run prompt.

### Inputs

- best run summaries,
- comparison tables,
- figure and table manifests,
- literature citations,
- methods extracted from code and config,
- known limitations and failure cases.

### Outputs

- `report.md` for fast review,
- `paper.md` as a structured intermediate,
- LaTeX section files or a single draft,
- figure captions and table captions,
- reproducibility appendix notes.

### Required Guarantees

- methods must reflect actual executed code and settings,
- results must reference real artifacts,
- limitations must include missing validations or suspicious outcomes,
- citations must be attributable to stored literature records.

## 14. MVP Scope

Phase 1 should stay intentionally narrow.

### In Scope

- single-domain support: computational pathology,
- baseline reproduction and performance improvement workflows,
- one active project session at a time per invocation,
- batch experiment loop with optional interactive debugging,
- Markdown report plus initial paper draft,
- human approval before major direction changes or final export.

### Out Of Scope

- fully generic science domains,
- broad plugin ecosystems,
- large-scale distributed scheduling,
- collaborative real-time paper editing,
- unrestricted autonomous internet-scale research.

## 15. Delivery Roadmap

### Phase 1: Foundation And Contract Stabilization

- unify workspace and sandbox semantics,
- fix local fallback and interactive execution mismatches,
- extend session data model for project, run, artifact, and locale handling,
- make evidence and artifact capture explicit,
- add paper writer and report outputs.

### Phase 2: Productization

- add project-level APIs and a richer CLI flow,
- support run browsing, artifact listing, and paper draft inspection,
- improve human review checkpoints,
- strengthen citation management.

### Phase 3: Search And Scale

- add controlled parallel experiment search,
- add tree-search planning and broader exploration policies,
- improve long-context memory compression and retrieval,
- support more structured paper exports.

### Phase 4: Toward Autonomous Scientist

- broader domain generalization,
- stronger benchmark-driven self-improvement,
- richer critique / reviewer loops,
- optional multi-agent collaboration with tighter governance.

## 16. Main Risks

- workspace and sandbox semantics drift across backends,
- generated code and executed code diverge,
- paper generation outruns evidence quality,
- local fallback behaves differently from container runs,
- long sessions lose context without good memory compression,
- evaluation quality is too weak to guide search.

## 17. Success Metrics

### Engineering Metrics

- a session can complete end-to-end without manual file surgery,
- the same experiment spec behaves consistently across supported backends,
- every exported report includes linked artifacts,
- replay of a completed run is possible from stored metadata.

### Research Metrics

- baseline reproduction success rate,
- percentage of runs with valid metrics and artifacts,
- percentage of report claims backed by evidence links,
- paper draft completeness and reviewer edit load.

## 18. Recommended Execution Strategy

Use a dual-track strategy:
- stabilize the execution contract first,
- then improve the intelligence of planning and paper generation.

In practice, this means Phase 1 should prioritize correctness of workspace, sandbox, runs, artifacts, and evidence over more ambitious search strategies.
