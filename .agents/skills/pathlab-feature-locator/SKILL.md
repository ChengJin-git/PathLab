---
name: pathlab-feature-locator
description: >
  Use this skill when working in the PathLab repository and the user wants to add a feature,
  modify an existing workflow, or quickly identify which modules, entry files, API clients,
  backend routes, data models, TaskWorker jobs, AI/Preprocessing services, and tests should
  be loaded before implementation. This skill consumes the existing CODEBASE_MAP-derived
  references; it does not regenerate CODEBASE_MAP.md. Prefer codebase-memory-mcp graph tools
  after using the references to verify concrete symbols and call paths.
---

# PathLab Feature Locator

Use this skill to turn a feature request into a minimal, correct code-loading set for PathLab.
It is a navigation skill, not a codebase-map generator.

## Core Workflow

1. Classify the request into one or more feature domains:
   - results / analysis / run history
   - training / models / logs
   - WSI / datasets / upload / viewer / tile / DZI
   - annotation / collaboration / COCO / audit
   - storage / migration / cleanup
   - permissions / auth / users
   - queue / cancellation / TaskWorker / long jobs
   - AI training / inference implementation
   - Electron / preload / sidecar / deployment
   - tests
2. Load `references/feature-index.md` first. Use it to identify the likely frontend page,
   API client, backend entrypoint, model/worker boundary, and test files.
3. Load only the reference needed next:
   - `references/module-map.md` for module responsibilities and "where to edit" guidance.
   - `references/architecture.md` when service boundaries, process ownership, ports, or entrypoints matter.
   - `references/testing-map.md` when choosing focused regression tests.
4. Verify the concrete implementation with codebase-memory-mcp:
   - `search_graph` to find functions, classes, routes, or variables.
   - `trace_path` to inspect callers/callees or impact.
   - `get_code_snippet` to read exact source once a qualified name is known.
   - `query_graph` for multi-hop or aggregate questions.
5. If MCP graph coverage is insufficient, fall back to `rg` for string literals,
   config values, non-code files, or missing graph entries.

## Loading Rules

- Do not load the full `CODEBASE_MAP.md` by default.
- Do not load every reference file by default.
- For ordinary UI/API features, load: page or component + API client + Gateway route + focused tests.
- For long-running tasks, additionally load: `gateway/task_dispatch.py`,
  `server/task_worker/handlers.py`, the relevant `server/task_worker/jobs/` module, and queue/status tests.
- For data-field changes, additionally load: ORM model, repository, schema/interface, serializer/route,
  frontend TypeScript interface, and API tests.
- For image tile / DZI / thumbnail work, include Preprocessing service files; do not assume Gateway owns image generation.
- For training or inference internals, include AI service routes/tasks; do not implement heavy work in Gateway.

## High-Risk Boundaries

- Gateway owns public API aggregation, authentication, static mounting, and Redis descriptor enqueueing.
  It should not execute long GPU tasks directly.
- TaskWorker owns descriptor claim, execution, heartbeat, cancellation handling, retry, and DLQ behavior.
- Preprocessing owns WSI information, thumbnails, DZI, tiles, patch images, ROI extraction, and image cache behavior.
- AI service owns training, inference, feature extractors, MIL aggregators, classifiers, and task trainers.
- Renderer code should consume backend services through `src/renderer/src/api/` clients.
- Electron main/preload code owns desktop capabilities, service port discovery, sidecar startup, and IPC bridging.

## Output Expected From This Skill

When asked where to implement a PathLab feature, return a concise loading plan:

- feature domain and reason
- frontend files to inspect
- API client files to inspect
- backend route/service files to inspect
- data model, repository, worker, or AI/Preprocessing files to inspect
- focused tests to run or add
- MCP graph queries or symbols worth verifying

Keep the answer scoped to files and symbols needed for the requested feature.
