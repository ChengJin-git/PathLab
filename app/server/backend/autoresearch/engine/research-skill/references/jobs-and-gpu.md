# Jobs, GPU scheduling and dependencies

## Job scripts

- `submit_experiment` runs model training or method comparisons and consumes an experiment
  attempt. `submit_computation` runs data preparation, metrics, analysis and report generation and
  does not. Both take an argument array, e.g. `["python", "train.py", "--config", "cfg.json"]`.
- Jobs start in a frozen read-only snapshot of the workspace. Read earlier outputs through
  `Path(os.environ["PATHLAB_WORKSPACE"])`; write everything to `Path(os.environ["OUTPUT_DIR"])`.
  Save finite numeric metrics to `$OUTPUT_DIR/metrics.json` and progress to
  `$OUTPUT_DIR/progress.json`. The agent, not the job, updates `findings.md`.
- `PATHLAB_DEVICE` is `cuda:0` or `cpu`. Initialise the CUDA device with a tensor before resetting
  allocator peak statistics.
- Jobs interrupted by a restart are requeued with the same ID, snapshot and OUTPUT_DIR. Save
  checkpoints atomically and resume from them, or detect completed output.

## GPU resources

For `device=gpu` provide `resources`: `operation` (feature_extraction, patch_classification,
segmentation, mil_training, inference or custom), `model`, `batch_size`, actual `image_size`. MIL
jobs add `bag_size` and `feature_dim`; set `trainable=true` when the backbone receives gradients.
Custom architectures add `peak_vram_mb` from a calculation or measured pilot. The scheduler picks
the GPU; never enumerate host GPUs or launch DDP inside a single-GPU lease. Split jobs whose
resource needs differ. A queued GPU job is not a failure; do not resubmit it.

## Speed

Profile a slow run once: separate loading, optimisation, inference and serialisation. Cache fixed
encodings outside epoch loops and batch small tensor work. Fix the bottleneck, then run the full
data; do not shrink the comparison to fit an unprofiled script.

## Dependencies and tools

- Missing Python module: `install_dependencies` with packages and import checks (e.g.
  `tabulate==0.9.0`, imports `[tabulate]`); it builds a session `.venv` used by later jobs.
- The image includes scientific Python/R, PDF/Word/PPT tools, Node 22, LibreOffice, XeLaTeX,
  Playwright/Chromium and OCR; see `/opt/pathlab/skills-python-freeze.txt`. Use `pathlab-mermaid`
  for Mermaid diagrams. Plot with matplotlib and Liberation Sans.
- Reference implementations live in `/opt/pathlab/templates` (WSI/patch classification, survival,
  segmentation, feature extraction, external evaluation) and task guidance in
  `/opt/pathlab/guidance`. They are starting points; adapt or replace them freely.
- Never print or copy credentials from the environment.
