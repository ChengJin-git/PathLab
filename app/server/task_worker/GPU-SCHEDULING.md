# GPU scheduling

> PathLab v1.0.8 · Updated 2026-11-01

`gpu_resources.py` owns resource normalization and peak-memory planning. Both
`TaskQueueManager.submit` (whole GPU jobs) and pipeline stages call that estimator.
AutoResearch GPU submissions require a `resources` object; CPU jobs bypass GPU
admission. No descriptor-specific fallback silently assumes a research job needs 2 GB.

`GpuScheduler` is the sole admission owner in TaskWorker. CPU preparation runs
without a lease. Actual GPU stages acquire/release leases and compete with research
jobs and inference for `max_concurrent` slots and available memory. The independent
research-agent concurrency setting still governs LLM sessions, not GPU slots.

- Estimates distinguish frozen encoders, trainable backbones, segmentation and
  MIL aggregators over frozen embeddings. Image resolution and batch size matter;
  MIL uses persisted feature-file sizes grouped by case when available. Estimates
  include context/optimizer/activation overhead and a planning margin. Custom code
  supplies a declared/measured peak. These are estimates, not measured guarantees.
- Telemetry uses system-wide NVML free memory, with CUDA driver `mem_get_info`
  fallback. Allocator-local usage is never substituted for system free memory.
- Apple Silicon native training uses `mps` at index 0. A real tensor probe must pass;
  admission uses 70% of Metal's recommended working set, bounded by available system
  RAM, with all cross-process reservations withheld conservatively. CUDA-only AMP
  and pinned-memory options are disabled. Docker sandbox jobs cannot use MPS; GPU jobs
  in Docker require a CUDA-capable image.
- Reserve only the unallocated remainder of peak commitments: actual attributed
  process memory is already deducted by NVML. Shared AI process leases are grouped
  by PID, with a pre-allocation baseline; research binds the sandbox process group.
  Missing attribution stays conservative. No fixed-time reservation expiry.
- Oldest fitting requests start first. Placement preserves larger-capacity devices;
  among equally sized GPUs it selects the most available VRAM after reservations.
  Fresh capacity and per-job wait state are included in the agent's research context.
  After three bypasses or 60 seconds, the oldest blocked request
  drains one capable GPU; other devices can still serve smaller work.
- Busy GPUs wait; impossible single-device requirements fail with actionable
  size feedback. Failed telemetry never grants GPU 0. Hardware failures are
  excluded, while a model OOM or invalid kernel does not declare hardware broken.
- Cancelled waits leave no lease; running sandboxes are terminated before release.
  Remote training cancellation waits for the request to finish so disconnecting
  HTTP cannot prematurely free a lease while a CUDA thread is still running.
- CUDA logical indices are resolved through the worker's visible-device mapping
  before narrowing the research sandbox to its single assigned GPU.

Queue snapshots contain ordered stage requests, estimated MiB, reason and position.
Research APIs project only the requesting session's scheduling state. The UI shows
a localized wait notice; the tool response tells the agent not to submit duplicates.
Time spent idle with only GPU-queued jobs suspends the research wall-clock budget.
