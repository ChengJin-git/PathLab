# LLM Workflow Ownership TODO

## Goal

Evaluate and gradually move PathScientist workflow decisions from scattered keyword/rule logic toward LLM-led structured decisions, while keeping deterministic guardrails for safety, reproducibility, permissions, and data integrity.

This is not a plan to let the LLM run arbitrary code or bypass PathLab controls. The target is: LLM owns semantic interpretation and workflow planning; deterministic code validates, executes, audits, and persists.

## Current State

- Outer workflow is still mostly deterministic: intake -> grounding -> acquisition/readiness -> execution -> review -> synthesis.
- LLM is used for bounded decisions such as skill selection, task-profile enrichment, dataset discovery enrichment, selector ranking, and summaries.
- Rule and keyword logic still exists in multiple places and can silently influence outcomes:
  - `dataset/task_profile.py`
  - `dataset/llm_task_profile.py`
  - `orchestrator/grounding.py`
  - `orchestrator/execution_plan.py`
  - `dataset/discovery_extractor.py`
  - `dataset/readiness.py`
  - `domain/extractor_selector.py`
  - `domain/mil_selector.py`

## Desired Direction

### 1. LLM-first task profile

- Make LLM structured task profiling the primary path for task shape, prediction target, organ, dataset intent, internal/external split intent, and stop-after intent.
- Keep deterministic rules as fallback only when LLM is unavailable, low confidence, or missing required fields.
- Record provenance for every field: `llm`, `explicit_user`, `heuristic_fallback`, `default`, or `system`.

### 2. LLM-led workflow planning

- Introduce a structured workflow planner that emits a typed plan such as:
  - check registered datasets
  - resolve labels
  - acquire or link missing data
  - extract missing internal features
  - extract missing external features
  - train
  - evaluate internal
  - evaluate external
  - register artifacts
  - summarize results
- The LLM may choose and order high-level steps, but the runner validates the plan against allowed transitions and required prerequisites.

### 3. Agent-accessible workflow tools

- Expose major stages as auditable tools instead of hidden runner-only functions:
  - dataset search / registration check
  - label resolution
  - feature readiness check
  - feature extraction
  - training
  - internal evaluation
  - external evaluation
  - artifact registration
- Each tool must return structured evidence and machine-readable status.

### 4. Guardrails that must stay deterministic

- User/session authorization.
- Filesystem path containment and sandbox mount validation.
- Dataset and artifact registration writes.
- Feature existence checks by exact slide ID / feature path, not only counts.
- Label-table acceptance thresholds.
- Model artifact durability and copy-out rules.
- Download policy, network egress policy, and credential handling.
- Final execution of generated scripts inside sandbox.

### 5. Failure recovery and replanning

- If readiness fails, labels are ambiguous, features are missing, or external data is unavailable, call the planner again with structured failure evidence.
- The LLM can propose a recovery step, but recovery must still pass deterministic validation.
- Persist every replan input/output in the session log.

## Implementation Milestones

### M1. Audit and provenance

- Add/verify provenance fields for task profile, skill selection, dataset selection, label selection, feature extractor selection, and workflow steps.
- Add tests that expose when a keyword/rule overrides an LLM decision.

### M2. LLM-first task profile

- Change `dataset/task_profile.py` from source-of-truth to fallback/hint.
- Make `dataset/llm_task_profile.py` produce the primary structured profile when LLM config is available.
- Keep rule fallback for offline/dev mode.

### M3. Structured workflow planner

- Add a typed `WorkflowPlan` schema with allowed step kinds and required inputs/outputs.
- Add LLM planner prompts that receive objective, task profile, dataset registry summary, readiness summary, and previous failures.
- Validate the LLM plan before execution.

### M4. Toolize workflow stages

- Wrap acquisition, readiness, label resolution, feature extraction, training, evaluation, and artifact registration as structured tools.
- Make runner execute validated tool calls rather than hardcoded linear branches where possible.

### M5. Replanning loop

- On recoverable failures, feed structured evidence back to the planner.
- Limit max replans and persist plan versions.
- Surface plan changes in Web UI logs.

## Non-goals

- Do not remove sandboxing.
- Do not let the LLM bypass authorization or path validation.
- Do not let generated code write directly into PathLab database tables.
- Do not replace exact file/feature/label validation with natural-language judgment.
- Do not make old keyword rules stronger while calling the system LLM-led.

## Open Questions

- Should workflow planning be enabled by default, or behind a feature flag such as `PATHSCIENTIST_LLM_WORKFLOW_PLANNER=1`?
- Should the planner be allowed to request data download automatically, or should download remain a gated deterministic policy decision?
- How much of the current Web progress UI should expose the planner's step list?
- Should standalone CLI keep deterministic mode for reproducibility tests?

## References

- `docs/achieve/2026-06-17-pathscientist-agent-architecture-assessment.md`
- `docs/plan/2026-06-19-pathscientist-code-organization-review.md`
- `docs/todo/TODO.md`
