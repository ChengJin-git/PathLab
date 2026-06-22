# mini-SWE-agent Architecture Analysis

> Date: 2026-04-02
> Source: https://github.com/SWE-agent/mini-swe-agent (v2.2.8)
> Purpose: Evaluate as potential execution engine for PathScientist platform

## 1. Overview

mini-SWE-agent is a ~100-line core agent (~4700 LOC total) from the Princeton/Stanford team behind SWE-bench. It uses bash as its only tool and scores >74% on SWE-bench Verified. It has superseded the original SWE-agent as the team's primary project.

Key design principles:
- Radical simplicity: no custom tools, LLM uses the shell directly.
- Stateless execution: every action runs in an independent subshell via `subprocess.run`.
- Hackable: all components (Agent, Model, Environment) follow duck-typed protocols and are swappable.
- Config-driven: all behavior (prompts, limits, environment) controlled by YAML files merged at startup.

Adopted by: Meta, NVIDIA, Essential AI, IBM, Nebius, Anyscale.

## 2. Three-Layer Architecture

```
+------------------+
|     Agent        |  DefaultAgent / InteractiveAgent
|  (main loop)     |  ~100 lines: query -> parse -> execute -> observe -> repeat
+--------+---------+
         |
+--------+---------+
|     Model        |  LitellmModel / OpenRouterModel / PortkeyModel / ...
|  (LLM + parse)   |  LLM call + action extraction (tool call / text regex)
+--------+---------+
         |
+--------+---------+
|   Environment    |  LocalEnvironment / DockerEnvironment / SingularityEnvironment / ...
|  (execution)     |  execute({"command": str}) -> {"output": str, "returncode": int}
+------------------+
```

All three layers communicate through plain dicts. No shared state between layers except messages list.

## 3. Agent Layer

### 3.1 DefaultAgent (`agents/default.py`, ~150 lines)

Core loop:

```python
def run(self, task: str) -> dict:
    self.messages = [system_prompt, instance_prompt(task)]
    while True:
        self.step()              # query + execute
        if messages[-1]["role"] == "exit":
            break
    return messages[-1]["extra"]

def step(self) -> list[dict]:
    return self.execute_actions(self.query())

def query(self) -> dict:
    # Check step/cost limits -> raise LimitsExceeded
    message = self.model.query(self.messages)
    self.cost += message["extra"]["cost"]
    return message

def execute_actions(self, message: dict) -> list[dict]:
    outputs = [self.env.execute(action) for action in message["extra"]["actions"]]
    return self.model.format_observation_messages(message, outputs, template_vars)
```

Config (`AgentConfig`):
- `system_template`: Jinja2 system prompt
- `instance_template`: Jinja2 task prompt
- `step_limit`: max LLM calls (0 = unlimited)
- `cost_limit`: max USD spend (default $3)
- `output_path`: trajectory save path

Template variables are merged from agent config + model + environment via `get_template_vars()`.

Trajectory serialization: saves full message history + config + stats to `.traj.json`.

### 3.2 InteractiveAgent (`agents/interactive.py`, ~180 lines)

Extends DefaultAgent with three modes:
- `human`: user types bash commands directly
- `confirm`: LLM commands require user confirmation (default)
- `yolo`: LLM commands execute without confirmation

Features:
- Rich console output with step count and cost display
- Slash commands: `/y` (yolo), `/c` (confirm), `/u` (human), `/h` (help), `/m` (multiline)
- Keyboard interrupt handling: user can inject comments or switch modes
- Exit confirmation: when agent wants to finish, user can add new tasks or continue
- Whitelist regex patterns for auto-approved actions

## 4. Model Layer

### 4.1 Model Protocol

All models implement:

```python
class Model(Protocol):
    config: Any
    def query(self, messages: list[dict]) -> dict: ...
    def format_message(self, **kwargs) -> dict: ...
    def format_observation_messages(self, message, outputs, template_vars) -> list[dict]: ...
    def get_template_vars(self, **kwargs) -> dict: ...
    def serialize(self) -> dict: ...
```

The `query()` return must include `message["extra"]["actions"]` (list of `{"command": str}`) and `message["extra"]["cost"]`.

### 4.2 Three Action Parsing Modes

| Mode | Module | Mechanism | Tool Definition |
|------|--------|-----------|-----------------|
| Tool Call | `actions_toolcall.py` | OpenAI tool_calls array | `BASH_TOOL` (nested function object) |
| Responses API | `actions_toolcall_response.py` | Flat function_call items | `BASH_TOOL_RESPONSE_API` (flat) |
| Text-based | `actions_text.py` | Regex on markdown code blocks | No tool definition needed |

The only tool defined:
```json
{
  "type": "function",
  "function": {
    "name": "bash",
    "description": "Execute a bash command",
    "parameters": {
      "type": "object",
      "properties": { "command": { "type": "string", "description": "The bash command to execute" } },
      "required": ["command"]
    }
  }
}
```

Text-based regex: `` ```mswea_bash_command\n(.*?)\n``` `` — expects exactly 1 match per response.

### 4.3 Provider Implementations

| Provider | Tool Call | Responses API | Text-based |
|----------|-----------|---------------|------------|
| litellm (100+ LLMs) | `LitellmModel` | `LitellmResponseModel` | `LitellmTextbasedModel` |
| OpenRouter (direct HTTP) | `OpenRouterModel` | `OpenRouterResponseModel` | `OpenRouterTextbasedModel` |
| Portkey (routing proxy) | `PortkeyModel` | `PortkeyResponseAPIModel` | -- |
| Requesty (router) | `RequestyModel` | -- | -- |
| Test (deterministic) | `DeterministicToolcallModel` | `DeterministicResponseAPIToolcallModel` | `DeterministicModel` |

Key implementation notes:
- **LitellmModel**: Uses `litellm.completion()` with BASH_TOOL. Auto-enables Anthropic cache control for Claude models. Cost via `litellm.cost_calculator`.
- **OpenRouterModel**: Raw `requests.post()` to `https://openrouter.ai/api/v1/chat/completions`. Cost from `response["usage"]["cost"]`. Uses `_DictToObj` wrapper for attribute access compatibility.
- **PortkeyModel**: Uses Portkey SDK. Has workarounds for cache token tracking bugs. Supports `litellm_model_name_override` for cost calculation.
- **Test models**: Return pre-defined outputs in sequence. Support `/sleep N`, `/warning MSG`, and `raise` special commands.

### 4.4 Model Utilities

- **retry.py**: tenacity wrapper — max 10 attempts, exponential backoff 4-60s, configurable abort exceptions (`ContextWindowExceededError`, `AuthenticationError`, etc.)
- **anthropic_utils.py**: Reorders thinking blocks so they are never the last content block in assistant messages (API requirement). Appends empty text block if needed.
- **cache_control.py**: Adds `{"cache_control": {"type": "ephemeral"}}` to the last message only. Handles string/list content and tool messages differently.
- **openai_multimodal.py**: Regex-based extraction of `<MSWEA_MULTIMODAL_CONTENT>` tags, converts to OpenAI `image_url` format.
- **content_string.py**: Extracts displayable text from any message format (tool_calls, tool_result, multimodal lists, Responses API output). Used for Rich console display.

### 4.5 Global Cost Tracking

`GlobalModelStats` (thread-safe with Lock):
- Tracks cumulative cost and call count across all model instances
- Environment variable limits: `MSWEA_GLOBAL_COST_LIMIT` (USD), `MSWEA_GLOBAL_CALL_LIMIT` (count)
- Raises `LimitsExceeded` on breach

### 4.6 Model Factory

`get_model(config)`:
- Resolves model name: config > `MSWEA_MODEL_NAME` env var
- Auto-detects Anthropic models for cache control
- 9 model classes in registry, plus dynamic import support

## 5. Environment Layer

### 5.1 Environment Protocol

```python
class Environment(Protocol):
    config: Any
    def execute(self, action: dict, cwd: str = "") -> dict[str, Any]: ...
    def get_template_vars(self, **kwargs) -> dict: ...
    def serialize(self) -> dict: ...
```

Unified return contract:
```python
{"output": str, "returncode": int, "exception_info": str}
```

Exit signal: all backends check if output starts with `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`, then raise `Submitted`.

### 5.2 Backend Implementations

#### Local (`local.py`, ~80 lines)
- `subprocess.run(command, shell=True, cwd=cwd, timeout=timeout)`
- Each command in independent subshell (no persistent state)
- Forwards host environment + configured env vars
- Config: `cwd`, `env`, `timeout` (default 30s)

#### Docker (`docker.py`, ~155 lines)
- Long-running container via `docker run --name {uuid} {image} sleep {container_timeout}`
- Commands via `docker exec`
- Config: `image`, `cwd`, `env`, `forward_env`, `timeout`, `run_args`, `container_timeout` (default 2h), `pull_timeout`, `interpreter` (default `bash -lc`)
- Background cleanup to avoid blocking
- Configurable executable path via `MSWEA_DOCKER_EXECUTABLE`

#### Singularity/Apptainer (`singularity.py`, ~140 lines)
- Builds sandbox from image: `singularity build --sandbox {tmp_dir} {image}`
- Retries sandbox build up to 3 times
- Executes: `singularity exec --contain --cleanenv --fakeroot --writable {sandbox} bash -c {command}`
- Supports `--pwd`, `--env` for working directory and environment variables
- Config: `image`, `cwd`, `env`, `forward_env`, `timeout`, `executable` (from `MSWEA_SINGULARITY_EXECUTABLE`), `exec_args`, `global_args`
- Cleanup: `shutil.rmtree` on sandbox directory

#### Bubblewrap (`bubblewrap.py`, ~150 lines)
- Linux unprivileged sandboxing (no root needed)
- Read-only binds: /usr, /bin, /lib, /lib64, /etc
- tmpfs for /tmp, /proc, /dev
- Creates temp working directory per environment
- Config: `cwd`, `env`, `timeout`, `wrapper_args`

#### ConTree (`contree.py`, ~150 lines)
- Remote containerization via ConTree SDK
- Pulls OCI images, auto-creates cwd
- Config: `contree_config`, `image`, `image_tag`, `cwd`, `env`, `forward_env`, `interpreter`, `timeout`

#### SweRex Docker (`swerex_docker.py`, ~80 lines)
- Async Docker execution via SWE-ReX library
- `asyncio.run()` wrapper around `swerex.deployment.docker.DockerDeployment`
- Commands as `RexCommand` objects

#### SweRex Modal (`swerex_modal.py`, ~125 lines)
- Serverless cloud execution via Modal platform
- Supports custom CPU/memory via `modal_sandbox_kwargs`
- Config: `startup_timeout` (60s), `runtime_timeout` (3600s), `deployment_timeout` (3600s)
- Optional pipx installation for swe-rex

### 5.3 Environment Factory

`get_environment(config, default_type="")`:
- Registry maps strings to classes: `"docker"`, `"singularity"`, `"local"`, `"bubblewrap"`, `"contree"`, `"swerex_docker"`, `"swerex_modal"`
- Supports full import path for custom environments

## 6. Configuration System

### 6.1 Config Loading

```python
get_config_from_spec(spec: str | Path) -> dict
```

Search order for config files:
1. Exact path
2. `MSWEA_CONFIG_DIR` environment variable
3. Built-in config directory
4. `extra/` subdirectory
5. `benchmarks/` subdirectory

Supports key-value overrides: `model.model_kwargs.temperature=0.5` -> nested dict.

Multiple configs merged recursively with `recursive_merge()` (later overrides earlier, `UNSET` sentinel skipped).

### 6.2 Preset Configurations

| Config | Purpose | Environment | Mode |
|--------|---------|-------------|------|
| `default.yaml` | General text-based agent | Local | Text regex |
| `mini.yaml` | Interactive local agent | Local | Tool call, confirm |
| `mini_textbased.yaml` | Interactive text-based | Local | Text regex |
| `swebench.yaml` | SWE-bench evaluation | Docker | Tool call, 250 steps, $3 |
| `swebench_backticks.yaml` | SWE-bench text-based | Docker | Text regex |
| `swebench_xml.yaml` | SWE-bench XML tags | Docker | Text regex |
| `swebench_modal.yaml` | SWE-bench cloud | Modal | Merged with swebench.yaml |

### 6.3 Prompt Templates

All prompts use Jinja2 with `StrictUndefined`. Template variables come from three sources merged:
- Agent: config fields, `n_model_calls`, `model_cost`
- Model: config fields
- Environment: config fields, platform info (`system`, `release`, `version`, `machine`)

Standard instance template structure:
1. Task statement
2. Recommended 6-step workflow (analyze -> reproduce -> fix -> verify -> edge cases -> submit)
3. Command execution rules (subshell model, non-persistent state)
4. Useful command examples (cat heredoc, sed, nl)
5. System information block

Observation templates handle output truncation: content >10k chars is split into head (5k) + tail (5k) with elision warning.

## 7. Run Layer (CLI and Benchmarks)

### 7.1 CLI Entry Points

- `mini` / `mini-swe-agent`: Interactive local agent (`run/mini.py`)
  - Options: `-m model`, `-t task`, `-y yolo`, `-l cost_limit`, `-c config`, `-o output`
  - Default config: `mini.yaml`
  - Prompts for task if not provided

- `mini-extra` / `mini-e`: Utility commands (`run/utilities/mini_extra.py`)
  - `config setup/set/unset/edit`: Global config management (API keys, model selection)
  - `inspect` / `i`: TUI trajectory browser (Textual, vi keybindings)
  - `swebench`: Batch SWE-bench evaluation
  - `swebench-single`: Single instance evaluation

### 7.2 SWE-bench Batch Runner (`run/benchmarks/swebench.py`, ~290 lines)

- Loads instances from HuggingFace datasets
- `ThreadPoolExecutor` with configurable worker count
- Per-instance: creates Docker environment with instance-specific image
- `ProgressTrackingAgent` wraps `DefaultAgent`, updates Rich progress bar
- Thread-safe predictions file (JSON) with lock
- Instance filtering: `--filter` (regex), `--slice` (range), `--shuffle`, `--redo-existing`

Docker image naming: `get_swebench_docker_image_name()` replaces `__` with `_1776_` for Docker compatibility.

### 7.3 SWE-bench Single Runner (`run/benchmarks/swebench_single.py`, ~100 lines)

- Loads one instance by ID or index
- Uses InteractiveAgent by default (confirm mode)
- Supports cost limit override and immediate exit

### 7.4 Trajectory Inspector (`run/utilities/inspector.py`, ~290 lines)

- Textual TUI for browsing .traj.json files
- Vi-style navigation: `h/l` (prev/next step), `H/L` (prev/next trajectory), `j/k` (scroll)
- Groups messages into "steps" (assistant + observation pairs)
- `e` opens step in jless, `E` opens full trajectory

### 7.5 Progress Tracking (`run/benchmarks/utils/batch_progress.py`, ~180 lines)

- Rich-based progress UI for batch runs
- Tracks instances by exit status (Submitted, LimitsExceeded, error, etc.)
- ETA estimation based on completion speed
- Saves YAML report on completion

## 8. Exception Hierarchy

```
InterruptAgentFlow(messages)     # Base: interrupts agent loop with messages to append
  ├── Submitted                  # Task completed ("COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT")
  ├── LimitsExceeded             # step_limit or cost_limit exceeded
  └── UserInterruption           # User interrupted (Ctrl-C or slash command)
FormatError                      # LLM output format invalid (triggers retry with error template)
```

## 9. Fit Assessment for PathScientist

### What We Can Reuse Directly

| Component | Reuse Strategy |
|-----------|----------------|
| Model layer (litellm + retry + cost) | `pip install mini-swe-agent` and import `LitellmModel` or `get_model()` |
| Singularity environment | Import `SingularityEnvironment`, extend config for GPU/data mounts |
| Local environment | Import `LocalEnvironment` for dev/test |
| Docker environment | Import for container-based experiments |
| Config system | YAML config + Jinja2 prompt templates |
| Cost tracking | Global cost limits per session |
| Trajectory serialization | Extend for experiment evidence |
| Interactive agent | Use for human-in-the-loop review stages |

### What We Must Build on Top

| Need | Why mini-SWE-agent Can't Do It | PathScientist Approach |
|------|-------------------------------|----------------------|
| Multi-stage orchestration | Single while-loop, no phase concept | Build orchestrator that runs multiple agent instances per stage |
| Custom tools beyond bash | Only bash tool, by design | Add tools via LLM function calling or prompt-injected helpers |
| Persistent workspace state | Stateless subshells | Use workspace dir contract + git tracking |
| Artifact tracking | No concept of artifacts | Build evidence layer on top of trajectory data |
| Literature retrieval | No web/API access tools | Add as pre-stage or custom environment capability |
| Paper generation | No report output | Build as post-stage using evidence from trajectories |
| Experiment memory | No cross-run memory | Build memory layer that feeds into prompt templates |
| Domain skills/templates | No domain concept | Inject via system prompt and workspace setup |

### Integration Options

**Option A: pip dependency** (lightest)
- `pip install mini-swe-agent`
- Import Model + Environment classes
- Write PathScientist orchestrator on top
- Pro: minimal code, get updates for free
- Con: coupled to their API, may need to pin versions

**Option B: vendored fork** (most control)
- Copy relevant modules into PathScientist package
- Adapt and extend as needed
- Pro: full control, no external dependency
- Con: maintenance burden, no upstream updates

**Option C: protocol-compatible reimplementation** (cleanest)
- Follow their Agent/Model/Environment protocols
- Implement from scratch with PathScientist-specific features
- Pro: clean architecture, no baggage
- Con: more initial work, may duplicate effort

### Recommended Approach

Option A (pip dependency) for Model and Environment layers, custom orchestrator on top:

```
PathScientist Orchestrator
  ├── IntakeStage        → uses mini-swe-agent Model for LLM calls
  ├── GroundingStage     → literature agent (custom)
  ├── ExperimentStage    → uses mini-swe-agent Environment for execution
  │   └── CodeAgent      → uses mini-swe-agent Agent loop (extended)
  ├── AnalysisStage      → uses mini-swe-agent Model for LLM calls
  └── PaperStage         → uses mini-swe-agent Model for LLM calls
```

This avoids forking OpenHands (heavyweight, ~100k LOC) while getting a battle-tested execution layer.
