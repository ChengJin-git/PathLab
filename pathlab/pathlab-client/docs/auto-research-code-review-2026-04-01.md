# Auto Research Code Review

> Date: 2026-04-01
> Method: static review only; no runtime validation in this pass
> Scope: `server/backend/auto_research/*` and related training templates / API entrypoints

## Findings

### 1. High — local fallback path crashes after normal execution

- Files:
  - `server/backend/auto_research/code_agent.py:1449`
  - `server/backend/auto_research/code_agent.py:1454`
  - `server/backend/auto_research/sandbox_base.py:149`
- In `_run_local_training()`, the subprocess handle `proc` is created inside the inner `_run()` closure at `server/backend/auto_research/code_agent.py:1393`, but the outer function later reads `proc.returncode` at `server/backend/auto_research/code_agent.py:1449` and `server/backend/auto_research/code_agent.py:1454`.
- When `get_sandbox()` falls back to `_LocalSandboxAdapter`, a normal subprocess run can therefore end in `NameError: name 'proc' is not defined` instead of returning a `SandboxResult`.
- This means the advertised local fallback is not actually usable as a safe degraded path.
- Suggested fix: return the exit code from `_run()` and use `exit_code` consistently in the outer scope instead of referencing `proc`.

### 2. High — local fallback does not honor the current script/template runtime contract

- Files:
  - `server/backend/auto_research/sandbox_base.py:160`
  - `server/backend/auto_research/code_agent.py:1356`
  - `server/backend/auto_research/templates/feature_extraction_template.py:286`
  - `server/backend/auto_research/templates/classification_template.py:244`
- `_LocalSandboxAdapter.run_training()` accepts `data_mounts`, `env_vars`, and `rw_paths`, but drops all of them when it delegates to `_run_local_training()`.
- `_run_local_training()` only prepares a minimal environment (`PYTHONUNBUFFERED`, `CUDA_VISIBLE_DEVICES`, `PYTHONPATH`) and never maps the runtime contract that the templates rely on, such as `OUTPUT_DIR`, `WSI_DIR`, `FEATURES_DIR`, or container-style paths like `/results` and `/data/*`.
- The current templates explicitly read those variables and defaults, so the same generated script can behave differently across Apptainer/Docker vs. local fallback.
- Impact: local fallback can silently write outputs to the wrong place, fail to find inputs, or appear to succeed while producing unusable artifacts.
- Suggested fix: pass the full mount/env contract through the local adapter and make local execution emulate the same path conventions as the container backends.

### 3. High — interactive mode workspace semantics do not match the execution backend

- Files:
  - `server/backend/auto_research/code_agent.py:1192`
  - `server/backend/auto_research/interactive_agent.py:385`
  - `server/backend/auto_research/interactive_agent.py:418`
  - `server/backend/auto_research/prompts.py:452`
  - `server/backend/auto_research/apptainer_sandbox.py:143`
  - `server/backend/auto_research/sandbox.py:40`
  - `server/backend/auto_research/sandbox_base.py:76`
- The interactive prompt tells the agent to execute commands such as `python /workspace/train.py`, and `write_file` stores relative paths under the host `workspace_dir`.
- But `ApptainerSandbox.execute_command()` builds a container command without binding that host workspace to `/workspace`, `DockerSandbox` does not implement `execute_command()` at all, and the base fallback execution path runs `subprocess.run()` without setting `cwd` to the interactive workspace.
- As a result, the write path and the run path are not describing the same filesystem in any backend with current code.
- Impact: an interactive session can successfully write files and still fail immediately when attempting to execute them, or behave differently depending on backend selection.
- Suggested fix: define one workspace contract for interactive mode, bind it consistently in every backend, and make `execute_command()` honor that workspace as its execution root.

### 4. Medium — `locale` request field is exposed but ignored

- Files:
  - `server/backend/auto_research/server.py:47`
  - `server/backend/auto_research/server.py:87`
  - `server/backend/auto_research/server.py:275`
  - `server/backend/auto_research/types.py:103`
- `StartRequest` exposes `locale`, and `_run_graph_session()` tries to read `config.locale`.
- However, `AutoResearchConfig` does not define a `locale` field, and `/start` never copies `req.locale` into the config object.
- The runtime therefore always falls back to `"en-US"` even when callers provide a different locale.
- This is an API/implementation mismatch: the public request model promises behavior that the backend ignores.
- Suggested fix: add `locale` to `AutoResearchConfig`, set it in `/start`, and add one propagation test so this field cannot regress silently.

## Open Questions / Assumptions

- This review is based on static source inspection; I did not run end-to-end training, container, or interactive sandbox flows in this pass.
- I assume local subprocess fallback is intended to be production-usable because `get_sandbox()` selects it unconditionally when Apptainer and Docker are unavailable.
- I assume interactive mode is still experimental, but the current implementation already exposes enough surface area that its backend contract should be made internally consistent before wider use.

## Suggested Smoke Tests

1. Force the code agent onto the local backend and verify one end-to-end training run returns a `SandboxResult` instead of raising `NameError`.
2. Add a local-backend contract test that confirms `OUTPUT_DIR`, `WSI_DIR`, and `FEATURES_DIR` resolve exactly as the training templates expect.
3. Add an interactive Apptainer test that performs `write_file("train.py")` followed by `run_command("python /workspace/train.py")`.
4. Add an API test for `/start` proving a non-default `locale` propagates into `AutoResearchConfig` and the graph initial state.
