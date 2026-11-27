# Architecture and code map

This document follows the architecture in the manuscript (Methods, *PathLab architecture and
executable research workflows*, and Fig. 7) and points to the code that implements each part.
Paths are relative to `app/`.

## Processes

`server/main.py` starts five processes on one server:

| Process | Code | Responsibility |
| --- | --- | --- |
| Gateway (port 6100) | `server/gateway/` | Authentication, public REST API, chat workspace, research API, result analysis |
| Preprocessing (6101) | `server/backend/preprocessing/` | Whole-slide reading (OpenSlide and vendor formats), tiles, thumbnails, tissue detection |
| AI (6102) | `server/backend/ai/` | Feature extraction, training and inference for the built-in task types |
| TaskWorker | `server/task_worker/` | Redis-backed queue that runs GPU jobs with memory estimates and device leases |
| ResearchWorker | `server/backend/autoresearch/engine/worker.py` | Supervises research sessions and article writing |

State lives in PostgreSQL (`server/backend/database/models.py`), Redis (queue and progress) and the
storage directory (slides, features, models, results, research workspaces). The browser client in
`src/renderer/` talks to the Gateway, and to Preprocessing for tiles.

## Research controller

The controller is the language model plus the server code that gives it context, tools and limits.
It is not tied to one model vendor: any OpenAI-compatible endpoint configured in Settings can serve
it (the manuscript reports which models were used for each evaluation).

There are two ways investigators work with it, matching the manuscript's Co-pilot and Auto-pilot
modes:

- **Chat** (`server/gateway/routes/chat.py`, `server/gateway/chat/`, prompts in
  `server/gateway/prompts/`). The model answers, retrieves data and literature, and proposes
  structured *cards* — for example a training configuration (`[TASK_CONFIG]`), an analysis or a
  dataset registration. Cards are rendered in the client; nothing runs until the investigator
  reviews the card and submits it. `prompts/execution.py` defines when work stays in chat, uses a
  built-in card or is handed to a research session.
- **Research sessions** (`server/backend/autoresearch/engine/`, client pages
  `src/renderer/src/pages/AutoResearch*.tsx`). An OpenCode agent runs inside the sandbox with the
  PathLab research skill (`engine/research-skill/SKILL.md`) and the tools in `engine/tools.py`
  (exposed over MCP). It plans, writes and runs code, submits experiments to the TaskWorker
  (`engine/jobs.py`), records decisions and evidence, and asks the investigator when a choice is
  needed. Investigators can add instructions, pause, resume and compare experiments.

Both paths share the data catalog, models, checks and outputs below.

## Skill interface

- Built-in skills for the five task families and for analysis, writing and data acquisition:
  `server/backend/autoresearch/engine/builtin_skills.py` and `server/backend/autoresearch/domain/skills/*.yaml`.
- Imported skill packages (directory, ZIP/`.skill` or a GitHub repository) are validated and
  snapshotted per session: `engine/skills.py`, `engine/skill_imports.py`.
- Third-party skill collections are vendored at pinned commits with file hashes in
  `server/backend/autoresearch/skill_library/sources.lock.json`.
- Users enable skills and connectors (web search, article reader, dataset catalogs) per workspace:
  `server/backend/services/capability_library.py`, `server/backend/services/workspaces.py`.
- The PathTrove catalog of public computational-pathology datasets and benchmarks is attached as an
  MCP server (`engine/pathtrove.py`, `deploy/install-pathtrove-data.py`).

## Built-in models and tasks

`server/backend/ai/` contains the model integrations used by Apply and as starting points for Develop:

| Part | Code |
| --- | --- |
| Patch encoders: UNI, UNI2, CONCH, CONCH v1.5, Virchow, Virchow2, H-Optimus-0/1, GPFM, Phikon, Phikon2, PLIP, PathoCLIP, mSTAR, KRONOS, OpenMidnight, SmartCCS, SmartCyto, ResNet-50, ViT-L/16 | `ai/extractors/` (registry in `registry.py`) |
| MIL aggregators: ABMIL, mean/max pooling, DSMIL, DTFD-MIL, CLAM-SB/MB, TransMIL | `ai/aggregators/` |
| Patch classifiers (linear, MLP, attention) | `ai/classifiers/` |
| Segmentation (U-Net family, SegFormer, DPT, UPerNet, and foundation-model decoders) | `ai/segmentors/` |
| Detection (Faster R-CNN, RetinaNet, FCOS) | `ai/detectors/` |
| Trainers for WSI classification, WSI survival, patch classification, detection and segmentation | `ai/tasks/` |
| Canonical task taxonomy and compatibility rules | `ai/task_taxonomy.py` |

Weights are not part of the repository. Checkpoints are downloaded from their publishers on first
use with the installation's Hugging Face token (`ai/extractors/checkpoint_manager.py`).

## Pre-execution methodological checks

The manuscript describes checks that run before any computation to catch task–data mismatches,
incompatible architectures, leakage between development and evaluation data, and requests to report
results that were never produced. In the code they are layered:

1. **Rules given to the controller.** Workflow contracts in `server/gateway/prompts/workflows.py`
   (which data types, task types, encoders, aggregators and split strategies are compatible; that
   heatmaps or masks need actual result evidence) and the execution boundary in `prompts/execution.py`
   (no fabricated results; a missing tool is different from missing data or labels). The research
   skill (`engine/research-skill/`) carries the corresponding rules for sessions: patient-level
   separation, closest-baseline reproduction, repeated runs and measured evidence before claims.
2. **Server-side validation that does not depend on the model.**
   - `ai/task_taxonomy.py` — task/data/aggregation compatibility for every training and inference
     request.
   - `services/dataset_catalog.py`, `gateway/routes/dataset_catalog.py` — dataset task and label
     validation; COCO payload checks in `gateway/utils.py`.
   - `ai/utils/data_splitter.py` — patient-aware train/validation/test splits.
   - `gateway/routes/external_validation_analysis.py` — model/target compatibility for external
     validation (excludes the training source).
   - `engine/study_contract.py`, `engine/study.py` — a research session's declared design is checked
     against executed comparisons and source files, so an unfinished pilot cannot be reported as a
     completed study.
3. **Access control.** Every request is checked against dataset ownership or public visibility,
   task ownership and the user's role (`server/backend/auth/dependencies.py`,
   `server/permissions/README.md`).

These checks assess methodological compatibility. As the manuscript notes, they do not prove that
generated code is correct or establish clinical validity.

## Apply, Develop and Discover

- **Apply** — built-in training, inference, batch and external validation, and statistical analysis
  through cards (`gateway/routes/training.py`, `results.py`, `classification_analysis.py`,
  `survival_analysis.py`, `segmentation_analysis.py`), plus image retrieval and the slide assistant.
- **Develop** — research sessions write and run code in the sandbox
  (`server/backend/autoresearch/runtime/`, `engine/runtime.py`, `engine/jobs.py`) starting from
  templates in `server/backend/autoresearch/domain/templates/`.
- **Discover** — evidence-based study records and decisions (`engine/study.py`, `engine/harness.py`),
  literature retrieval and citation spans (`server/backend/autoresearch/literature/`), and public
  dataset acquisition and registration (`server/backend/autoresearch/dataset/`).

## Execution environment

- Built-in jobs are queued in Redis and executed by the TaskWorker, which estimates GPU memory and
  leases devices (`server/task_worker/`, `GPU-SCHEDULING.md`).
- Generated code runs in an Apptainer (or Docker) container built from
  `server/backend/autoresearch/runtime/containers/`. Jobs start from a read-only snapshot of the
  session's code and can only reach the datasets mounted for that session.

## Outputs and retained assets

- Result bundles and their catalog (`server/backend/ai/result_store.py`, `result_catalog.py`), shown
  as layers in the whole-slide viewer (`src/renderer/src/components/wsiViewer/`).
- Statistical analysis of saved results (`server/backend/services/result_analysis/`).
- Reports and articles with verified citations (`server/backend/services/REPORTS.md`).
- Models, features and workflows produced in a session are registered for reuse:
  `engine/registration.py` (models and features), `FeatureArtifact` records
  (`server/backend/services/FEATURE-ARTIFACTS.md`), and the capability library for skills.

## Accounts and data access

PathLab supports multiple users with three roles: `admin` (all data and settings, user
management), `pathologist` (all research features on data they own or that is public) and `guest`
(data, viewer and chat; no GPU jobs or research sessions). Datasets are private to their owner or
public to all signed-in users. Models, results and research sessions always belong to the user who
created them. Details: `server/permissions/README.md`.
