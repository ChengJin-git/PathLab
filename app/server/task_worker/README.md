# TaskWorker: execution boundary and consistency

In the PathLab web application the Gateway receives browser requests, the TaskWorker manages the
background GPU queue, and the AI and Preprocessing services provide the internal execution
capabilities.

## Modules and ownership

| Module | Responsibility |
| --- | --- |
| `backend/common/task_dispatch.py` | JSON descriptors, Redis pending/processing/DLQ lists, cancellation signals, dispatch locks, heartbeats |
| `backend/common/task_runtime.py` | Runtime snapshots published by the worker and read by the Gateway |
| `backend/common/task_types.py` | Task types, without runtime side effects |
| `backend/common/queue_lifecycle.py` | Persistent FIFO recovery order, serial recovery and system-interruption semantics shared by training and research |
| `task_worker/main.py` | Consumes descriptors, starts the queue, recovers tasks, subscribes to cancellations, publishes heartbeats |
| `task_worker/task_queue.py` | In-process GPU queue, concurrency limits, memory budget, running-task handles |
| `task_worker/gpu_scheduler.py` | Shared GPU memory leases, admission, fairness and per-process memory attribution |
| `backend/common/gpu_resources.py` | Common resource specification and estimates for chat, research, training and inference |
| `task_worker/handlers.py`, `jobs/` | Adapters from descriptors to execution functions |
| `task_worker/recovery.py` | Builds recovery descriptors from database task records |
| `backend/autoresearch/engine/jobs.py` | Research experiments and public-data download jobs, code snapshots, cancellation and recovery |

The shared protocol never imports the Gateway or the GPU queue runtime. The Gateway's status
endpoints read shared snapshots, not in-process singletons. Some training, inference and analysis
helpers still live in `gateway/` and are lazily loaded by the worker's job adapters; queue operations
inside them only run in the worker process.

## What states and events mean

1. The Gateway checks identity, resource access and parameters, persists the task and sends a JSON
   descriptor.
2. The worker claims it and runs the handler. The handler acknowledges after dispatch;
   **acknowledgement does not mean training finished**.
3. The GPU queue skips duplicate submissions of a pending or running task ID; training preflight and
   patching also check tasks the queue already tracks, so recovery cannot start patching twice.
4. Tasks write their database state, Redis progress and files; the Gateway's SSE streams project
   these states to the browser.
5. Failed dispatches are retried up to a limit and then moved to the DLQ; GPU execution failures are
   recorded by the task pipeline, with the queue as a fallback.
6. When a single worker recovers descriptors from the processing list after a crash, it releases
   leftover dispatch locks, so a recovered task is not mistaken for a duplicate.

Dispatch is at-least-once. There is no global exactly-once guarantee across the database, the Redis
queue and GPU execution. One TaskWorker manages the GPU runtime per deployment; running several
workers is not a distributed GPU scheduler.

Research sessions are managed by the separate ResearchWorker; their GPU experiments enter the shared
lease scheduler through the `research.run` handler. CPU preparation, CPU experiments and downloads do
not hold GPU leases but keep cancellable handles. The earliest request that fits is admitted first
with best-fit device selection; the oldest waiting request yields at most three times or 60 seconds
before a fitting GPU is drained for it. Memory attribution and reservations are counted together;
see [GPU-SCHEDULING.md](GPU-SCHEDULING.md).

## Consistency rules

- **Restart recovery.** Shutdown interrupts executors with `worker_restart`, distinct from a user
  cancellation. Training keeps its progress and checkpoints and stays `resuming` once the AI service
  confirms it stopped. Research jobs are re-queued with the same job ID, code snapshot and output
  directory and do not count as new experiments; cancelled tasks are never revived. The
  ResearchWorker restores native sessions, plans and results; downtime and queueing do not consume
  the research budget. Recovery follows persisted submission time and a stable sequence; research
  sessions are admitted in one global FIFO across users.
- **Access.** Business APIs check ownership and dataset visibility on the server; SSE requires
  authentication. Making a dataset private also covers queued tasks: their cancellation is persisted,
  published to the worker and sent to the AI service; completed tasks are not rewritten. On sign-out
  the browser clears training, analysis and storage task snapshots and ignores late events from old
  connections.
- **Progress.** A Gateway restart does not clear Redis progress still written by the AI service or
  worker. Progress is cleared when a task ends and leftovers expire through TTLs. Lists and SSE read
  current task keys in batches and keep database state when progress or snapshot reads time out.
- **Cancellation.** The Gateway writes a cancellation key and publishes a message; the worker checks
  the flag and cancels its task. Old cancelled queue entries are skipped by object identity, so a
  resubmitted task with the same ID is not mistaken for the old one.
- **Deleting a training task.** Cancellation is published first even for a task shown as completed,
  so post-processing cannot keep writing files. A publishing timeout aborts the deletion; after the
  database commit, AI-service notification and file clean-up run in the background.
- **Deleting a conversation.** The response returns once logical deletion and job cancellation are
  committed. The ResearchWorker stops writers and removes files from a durable manifest; this internal
  clean-up does not appear in the progress panel.
- **Result files.** `AIResultStore` serialises staging, ZIP writes and deletes per task with a thread
  lock and a file lock across Gateway, AI and worker processes; the final ZIP is published by atomic
  replace. `result_catalog.py` updates the task's catalog rows in one SQLite WAL transaction; lists do
  not scan result bundles.
- **Counts.** GPU queue counts and Redis descriptor counts are different layers and must not be added
  up as the number of training tasks.

## Tests

Backend tests in `server/tests/` cover task dispatch, worker handlers, queue cancellation and
de-duplication, the Gateway lifespan, deletion ordering (`test_mutation_responsiveness.py`) and
multi-process result writes. Frontend tests in `test/unit/contexts/backgroundTask/` cover account
switches and late SSE events.
