# PathScientist TODO List

This directory tracks active PathScientist follow-up work. Historical planning docs live locally under `docs/achieve/` and are intentionally git-ignored.

## P0 Security

- [ ] Close PathScientist session IDOR/access-control gaps.
  - Source: `docs/plan/2026-06-18-pathscientist-web-security-remediation-plan.md`, WS-A.
  - Scope: non-admin users must not read, stream, stop, resume, delete, or download another user's session across in-memory, registry-reloaded, and disk-only records.
- [ ] Harden checkpoint command execution against host-side RCE.
  - Source: `docs/plan/2026-06-18-pathscientist-web-security-remediation-plan.md`, WS-B/B1.
  - Scope: validate checkpoint names and avoid shell-interpolated git commands.

## P1 Security / Web Hardening

- [ ] Add shared egress guard for web and dataset fetch paths.
  - Source: `docs/plan/2026-06-18-pathscientist-web-security-remediation-plan.md`, WS-C.
  - Scope: reject localhost, metadata, private networks, non-http schemes, and redirect-to-internal URLs.
- [ ] Verify and harden run-artifact download path containment.
  - Source: `docs/plan/2026-06-18-pathscientist-web-security-remediation-plan.md`, WS-D.
- [ ] Improve SSE/download token handling and persistence robustness.
  - Source: `docs/plan/2026-06-18-pathscientist-web-security-remediation-plan.md`, WS-E/F.

## Code Organization

- [ ] Evaluate LLM-led ownership of PathScientist workflow planning.
  - Source: `docs/todo/LLM_WORKFLOW_OWNERSHIP.md`.
  - Scope: move semantic decisions and high-level workflow planning toward LLM-first structured outputs while keeping deterministic guardrails for auth, paths, labels, feature checks, downloads, sandboxing, and artifact registration.
- [ ] Establish a focused safety baseline before larger refactors.
  - Source: `docs/plan/2026-06-19-pathscientist-code-organization-review.md`, Phase 0.
  - Scope: record and run focused backend/gateway test commands before moving code.
- [ ] Extract runner support modules from `orchestrator/runner.py`.
  - Source: code organization review, Phase 1.
  - Scope: literature setup, model selection, readiness/execution-plan prep, data mounts, acquisition helpers.
- [ ] Extract grounding modules from `orchestrator/grounding.py`.
  - Source: code organization review, Phase 2.
  - Scope: stop-after detection, skill routing, literature query planning, paper/SOTA shaping.
- [ ] Split dataset acquisition internals by concern.
  - Source: code organization review, Phase 3.
  - Scope: local identity, cache layout, manifest writing, provider orchestration.
- [ ] Split readiness internals by concern.
  - Source: code organization review, Phase 4.
  - Scope: types, path probing, feature checks, split helpers.
- [ ] Generalize label-schema resolution.
  - Source: code organization review, Phase 4.5.
  - Scope: replace task-specific label hotfixes with deterministic table scanning plus optional LLM ranking and manifest provenance.
- [ ] Split the large PathScientist gateway route.
  - Source: code organization review, Phase 5.
  - Scope: schemas, session manager, SSE/event normalization, download/archive helpers, access-token validation, PathLab sync, config defaults.

## PathLab Integration

- [ ] Register PathScientist-trained models into the PathLab database automatically after successful training.
  - Source: `docs/todo/PATHLAB_MODEL_REGISTRATION.md`.
  - Scope: durable model artifact path, run/session metadata, internal/external metrics, dataset IDs, feature extractor, model architecture, and owner should be persisted so the model appears in normal PathLab model/task views and can be reused outside the PathScientist session.

## Data / Acquisition

- [ ] Add dedicated GitHub and Figshare providers if they become required.
  - Source: `docs/dataset_acquisition.md` provider matrix.
- [ ] Add GDC manifest download-spec support.
  - Source: `docs/dataset_acquisition.md`, TCGA-BRCA note.
- [ ] Decide whether CLI flags for dataset discovery and auto-ingest are still needed.
  - Source: `docs/dataset_acquisition.md`, deferred Phase 1.5 notes.

## Environment / Deployment Docs

- [ ] Refresh `docs/ENVIRONMENT.md` against the current jhcpu5 state.
  - Scope: venv status, apptainer availability, sandbox image path, active ports, data roots.
- [ ] Refresh `docs/plan/2026-06-17-pathscientist-sandbox-migration-runbook.md` after verifying current sandbox behavior.
  - Scope: remove stale "not active" statements if sandbox is now available.

## Product / UX Follow-Up

- [ ] Reconcile `docs/PROJECT_MEMORY.md` phase status with the current web integration.
  - Scope: Phase 5 is no longer purely "not started" if PathScientist web sessions are already available.
- [ ] Keep frontend PathScientist session/result display covered by focused unit tests when event shapes change.
  - Scope: session list, session detail, execution console, result cards, progress events.
