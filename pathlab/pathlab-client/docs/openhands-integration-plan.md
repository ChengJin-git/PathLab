# 基于 OpenHands SDK 的 Auto Research 改进方案

> 源码位置：`/project/vcompath/storage/ywangrm/OpenHands-SDK/`
> 参考模块 → PathLab 改动文件的精确映射
> 文档校准：2026-04-01，以下内容以当前仓库实现为准，而不是最初设计稿

---

## 总览：6 个可借鉴模块

| # | OpenHands 模块 | 参考文件 | PathLab 改动 | 优先级 |
|---|---------------|---------|-------------|-------|
| 1 | StuckDetector | `sdk/conversation/stuck_detector.py` | `code_agent.py` 纠错循环 | P0 |
| 2 | LLMSummarizingCondenser | `sdk/context/condenser/llm_summarizing_condenser.py` | `code_agent.py`（已落地）/ `nodes.py`（未落地）/ `interactive_agent.py`（消息压缩） | P0 |
| 3 | BaseWorkspace | `sdk/workspace/base.py` | `sandbox_base.py` + `code_agent.py` / `interactive_agent.py` | P1 |
| 4 | SecurityAnalyzer | `sdk/security/analyzer.py` + `risk.py` | `script_safety.py` + `code_agent.py` / `interactive_agent.py` | P1 |
| 5 | ParallelToolExecutor | `sdk/agent/parallel_executor.py` | 并行实验调度 | P2 |
| 6 | Agent.step() ReAct | `sdk/agent/agent.py` | `interactive_agent.py`（实验性） | P3 |

---

## 1. StuckDetector → 纠错循环刹车（P0）

### OpenHands 做了什么

`stuck_detector.py` 检测 5 种卡死模式：
- 同 action + 同 observation 重复 N 次（`action_observation_threshold=4`）
- 同 action + 一直报错 N 次（`action_error_threshold=4`）
- Agent monologue 自言自语（`monologue_threshold=4`）
- 交替循环 A→B→A→B（`alternating_pattern_threshold=6`）
- Context window 错误循环

核心方法：`_event_eq()` 比较两个 event 是否"本质相同"（忽略 ID/时间戳）。

### PathLab 怎么用

改动文件：`code_agent.py`

当前纠错循环只有 `_MAX_FIX_ATTEMPTS=3` 硬限。问题：如果连续 3 次都是
同一个 ImportError，浪费 3 轮 LLM 调用。

新增 `_is_fix_loop_stuck()` 函数：

```python
def _is_fix_loop_stuck(
    fix_history: list[dict],
    threshold: int = 2,
) -> bool:
    """检测纠错循环是否卡死在同一个错误上。
    
    借鉴 OpenHands StuckDetector._is_stuck_repeating_action_error
    """
    if len(fix_history) < threshold:
        return False
    
    # 最近 N 次的 error_type 是否完全相同
    recent_errors = [h.get("error_type") for h in fix_history[-threshold:]]
    if all(e == recent_errors[0] for e in recent_errors):
        # 进一步检查：error 内容的关键行是否相同
        recent_patterns = [h.get("error_key_line", "") for h in fix_history[-threshold:]]
        if all(p == recent_patterns[0] for p in recent_patterns):
            return True
    
    return False

def _extract_error_key_line(error: str) -> str:
    """从 traceback 中提取最关键的一行（最后一个非空行）。
    
    借鉴 OpenHands StuckDetector._event_eq 的比较策略：
    忽略变化的部分（行号可能因代码修改偏移），比较错误本质。
    """
    lines = error.strip().split("\n")
    # 取最后一行（通常是 "ImportError: No module named 'xxx'"）
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith("Traceback") and not line.startswith("File"):
            return line
    return ""
```

在纠错循环中使用：

```python
fix_history = []  # [{error_type, error_key_line, attempt}]

for fix_attempt in range(_MAX_FIX_ATTEMPTS):
    result = await run_sandbox(...)
    if result.success:
        break
    
    error_type = _classify_error(result.error)
    error_key = _extract_error_key_line(result.error)
    fix_history.append({
        "error_type": error_type,
        "error_key_line": error_key,
        "attempt": fix_attempt,
    })
    
    # 卡死检测
    if _is_fix_loop_stuck(fix_history, threshold=2):
        logger.warning(
            f"[code_agent] Fix loop stuck on same error: {error_type} - {error_key}"
        )
        break  # 不再浪费 LLM 调用
    
    # ... 继续修复 ...
```

### 工作量：~30 行，2 小时

---

## 2. LLMSummarizingCondenser → 实验历史压缩（P0）

### OpenHands 做了什么

`llm_summarizing_condenser.py` 三层策略：
1. 保留前 `keep_first` 个 event（system prompt 等关键上下文）
2. 保留最近一半的 event（最新信息）
3. 中间被丢弃的 event 用 LLM 生成摘要
4. 摘要失败有 `hard_context_reset`（逐步缩减字符长度重试）

关键参数：`max_size=240`（最大 event 数）、`keep_first=2`、
`minimum_progress=0.1`（至少压缩 10%）

### PathLab 怎么用

**场景 A：code_history 压缩**

改动文件：`code_agent.py`

当前用 `code_history[-3:]` 硬截断。5 轮以后前面的实验信息全丢了。

```python
async def _condense_code_history(
    code_history: list[dict],
    research_question: str,
    keep_recent: int = 3,
) -> str:
    """将早期实验历史压缩为摘要。
    
    借鉴 OpenHands LLMSummarizingCondenser：
    keep_first（baseline）+ 摘要中间 + keep 最近 N 条。
    """
    if len(code_history) <= keep_recent + 1:
        # 不需要压缩
        return json.dumps(code_history, indent=2, ensure_ascii=False, default=str)
    
    # 分三段
    baseline = code_history[0]  # 首次实验（baseline，类似 keep_first）
    to_summarize = code_history[1:-keep_recent]  # 中间段
    recent = code_history[-keep_recent:]  # 最近 N 条
    
    if not to_summarize:
        return json.dumps(code_history, indent=2, ensure_ascii=False, default=str)
    
    # LLM 摘要中间段
    from .nodes import _get_llm
    llm = _get_llm(temperature=0.0)
    
    summary_prompt = f"""Summarize these {len(to_summarize)} experiment iterations concisely:

Research question: {research_question}

Experiments:
{json.dumps(to_summarize, indent=2, ensure_ascii=False, default=str)}

Output a brief summary (3-5 sentences) covering:
1. What modifications were tried
2. Which succeeded/failed and why
3. Key error patterns to avoid
4. Best metric achieved in these iterations"""
    
    from langchain_core.messages import HumanMessage
    response = await llm.ainvoke([HumanMessage(content=summary_prompt)])
    
    from .structured_output import strip_thinking
    summary_text = strip_thinking(response.content)
    
    # 组装：baseline + 摘要 + 最近 N 条
    return json.dumps({
        "baseline": baseline,
        "condensed_summary": summary_text,
        "condensed_iterations": f"iterations 1-{len(to_summarize)}",
        "recent": recent,
    }, indent=2, ensure_ascii=False, default=str)
```

在 CODE_AGENT_PROMPT 构造时：

```python
# 替换原来的
# code_history_str = json.dumps(state["code_history"][-3:], ...)
# 为
code_history_str = await _condense_code_history(
    state.get("code_history", []),
    research_question,
    keep_recent=3,
)
```

**场景 B：iteration 间的 literature_findings 压缩**

改动文件：`nodes.py` experiment_planner_node

最初设计里打算同理压缩 `literature_findings`，但**当前仓库尚未实现这一步**。
现在 `experiment_planner_node` 仍然是直接取 `literature_findings[:5]` 塞进 prompt。

也就是说，当前 P0 已落地的是：
- `code_history` 的 LLM 摘要压缩（`code_agent.py`）
- `interactive_agent.py` 内部对长消息历史的会话压缩

尚未落地的是：
- `nodes.py` 中针对 `literature_findings` 的独立 condenser

### 工作量：~50 行，半天

---

## 3. BaseWorkspace → 统一沙箱接口（P1）

### OpenHands 做了什么

```python
class BaseWorkspace(ABC):
    working_dir: str
    
    @abstractmethod
    def execute_command(self, command, cwd, timeout) -> CommandResult
    @abstractmethod  
    def file_upload(self, source, dest) -> FileOperationResult
    @abstractmethod
    def file_download(self, source, dest) -> FileOperationResult
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    
    def __enter__(self): return self
    def __exit__(self, ...): pass  # 子类做清理
```

关键设计：`LocalWorkspace` / `DockerWorkspace` / `RemoteWorkspace` 同一接口，
agent 代码不需要知道自己跑在哪个环境里。

### PathLab 怎么用

新增文件：`sandbox_base.py`

```python
from abc import ABC, abstractmethod
from typing import Optional
from .sandbox import SandboxResult


class TrainingSandbox(ABC):
    """统一训练沙箱抽象基类（当前主要覆盖 batch 执行路径）。"""

    @abstractmethod
    async def run_training(
        self,
        script_path: str,
        data_mounts: dict[str, str],
        output_dir: str,
        env_vars: Optional[dict[str, str]] = None,
        rw_paths: Optional[set[str]] = None,
    ) -> SandboxResult:
        ...

    async def execute_command(...):
        ...  # 基类提供 subprocess 默认实现，容器子类可覆盖

    @classmethod
    @abstractmethod
    async def check_available(cls) -> bool:
        ...

    async def cleanup(self):
        ...


class _LocalSandboxAdapter(TrainingSandbox):
    """显式继承 TrainingSandbox 的本地适配器。"""
    ...

# 当前代码里：
# - _LocalSandboxAdapter 显式继承 TrainingSandbox
# - DockerSandbox / ApptainerSandbox 保持兼容方法集合
# - ApptainerSandbox 额外实现 execute_command()，供 interactive_agent 使用
```

工厂函数：

```python
async def get_sandbox(sandbox_config: dict, skill_extra_packages=None) -> TrainingSandbox:
    if await ApptainerSandbox.check_available():
        return ApptainerSandbox(...)
    if await DockerSandbox.check_available():
        return DockerSandbox(...)
    return _LocalSandboxAdapter(...)
```

`code_agent.py` 的 batch 路径已经用统一入口替代了原来的多分支选择：

```python
sandbox = await get_sandbox(sandbox_config, ...)
result = await sandbox.run_training(...)
await sandbox.cleanup()
```

**注意当前实现边界**：
- batch 执行路径已经统一走 `get_sandbox()`
- 纠错循环会复用同一个 sandbox 实例，避免重复启动容器
- `interactive_agent.py` 也走 `get_sandbox()`
- 但 `DockerSandbox` / `ApptainerSandbox` 还没有显式继承 `TrainingSandbox`

所以这部分更准确的说法是：
**统一入口和共享方法契约已经落地，完整继承体系还可以继续收口。**

### 工作量：~100 行新文件 + ~30 行 code_agent 简化，1 天

---

## 4. SecurityAnalyzer → 执行前脚本安全检查（P1）

### OpenHands 做了什么

`security/analyzer.py` + `risk.py`：
- 每个 action 有 SecurityRisk 枚举（LOW/MEDIUM/HIGH/UNKNOWN）
- HIGH 自动要求用户确认
- 支持 LLM-based risk assessment（让 LLM 自己评估风险）

### PathLab 怎么用

新增文件：`script_safety.py`

AI 生成的训练脚本在沙箱里跑，但仍需要防止明显的恶意/危险行为。
比沙箱更早一步拦截。

```python
import ast
import re
from enum import IntEnum


class ScriptRisk(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2


# 当前实现里的高风险模式（直接拒绝）
HIGH_RISK_PATTERNS = [
    (r"subprocess\.(run|call|Popen|check_output)", "subprocess execution"),
    (r"os\.system\(", "os.system call"),
    (r"shutil\.rmtree\(", "recursive directory deletion"),
    (r"open\(.*/etc/", "reading system files"),
    (r"(?<!\w)socket\.", "raw socket access"),
    (r"urllib\.request", "network access via urllib"),
    (r"http\.client", "network access via http.client"),
]

# 当前实现里的中风险模式（警告但允许）
MEDIUM_RISK_PATTERNS = [
    (r"(?<!\w)eval\(", "eval() call"),
    (r"__import__\(", "dynamic import"),
    (r"requests\.(get|post|put|delete)\(", "HTTP request"),
    (r"os\.(remove|unlink)\(", "file deletion"),
    (r"shutil\.(copy|move)\(", "file copy/move"),
    (r"os\.chmod\(", "permission change"),
]


def assess_script_risk(script: str) -> tuple[ScriptRisk, list[str]]:
    """评估 AI 生成脚本的安全风险。
    
    借鉴 OpenHands SecurityAnalyzer 的分层风险评估，
    但用规则替代 LLM（更快、更可靠）。
    
    Returns:
        (risk_level, list_of_reasons)
    """
    reasons = []
    risk = ScriptRisk.LOW
    
    for pattern, desc in HIGH_RISK_PATTERNS:
        matches = re.findall(pattern, script)
        if matches:
            risk = ScriptRisk.HIGH
            reasons.append(f"HIGH: {desc} ({len(matches)}x)")
    
    if risk < ScriptRisk.HIGH:
        for pattern, desc in MEDIUM_RISK_PATTERNS:
            matches = re.findall(pattern, script)
            if matches:
                risk = max(risk, ScriptRisk.MEDIUM)
                reasons.append(f"MEDIUM: {desc} ({len(matches)}x)")
    
    # AST 级别检查
    try:
        tree = ast.parse(script)
        for node in ast.walk(tree):
            # 检查是否有无限循环风险（while True 没有 break）
            if isinstance(node, ast.While):
                if isinstance(node.test, ast.Constant) and node.test.value is True:
                    has_break = any(
                        isinstance(n, ast.Break) for n in ast.walk(node)
                    )
                    if not has_break:
                        risk = max(risk, ScriptRisk.MEDIUM)
                        reasons.append("MEDIUM: while True without break")
    except SyntaxError:
        pass  # 语法错误由 _validate_code 处理
    
    return risk, reasons
```

在 code_agent.py 执行前调用：

```python
from .script_safety import assess_script_risk, ScriptRisk

risk_level, risk_reasons = assess_script_risk(modified_script)
if risk_level == ScriptRisk.HIGH:
    logger.error(f"[code_agent] HIGH risk script blocked: {risk_reasons}")
    ratchet.reset_failure()
    # 告诉 LLM 为什么被拒，让它重写
    ...
elif risk_level == ScriptRisk.MEDIUM:
    logger.warning(f"[code_agent] MEDIUM risk script: {risk_reasons}")
    # 允许但记录
```

当前仓库里这套规则还复用在 `interactive_agent.py`：
- batch 路径：`code_agent.py` 执行前检查
- interactive 路径：`write_file(...py)` 时同步检查

所以这里已经不是单点接入，而是共享安全规则集。

### 工作量：~60 行，3 小时

---

## 5. ParallelToolExecutor → 并行实验资源锁（P2）

### OpenHands 做了什么

`parallel_executor.py` 用 `DeclaredResources` 实现细粒度锁：
- 工具声明它要访问的资源（如 `file:/a.py`）
- 不冲突的工具可以并行
- 冲突的工具串行等待

### PathLab 怎么用

当你做并行实验（多个 code_agent 同时跑不同方向）时需要：

```python
from dataclasses import dataclass

@dataclass
class GPUResource:
    gpu_id: str
    in_use: bool = False
    task_id: str = ""

class ExperimentScheduler:
    """并行实验调度器，GPU 资源锁。
    
    借鉴 OpenHands ParallelToolExecutor 的 DeclaredResources 模式。
    """
    
    def __init__(self, gpu_ids: list[str]):
        self.gpus = {gid: GPUResource(gpu_id=gid) for gid in gpu_ids}
        self._lock = asyncio.Lock()
    
    async def acquire_gpu(self, task_id: str) -> str | None:
        async with self._lock:
            for gid, gpu in self.gpus.items():
                if not gpu.in_use:
                    gpu.in_use = True
                    gpu.task_id = task_id
                    return gid
            return None  # 没有空闲 GPU
    
    async def release_gpu(self, gpu_id: str):
        async with self._lock:
            self.gpus[gpu_id].in_use = False
            self.gpus[gpu_id].task_id = ""
```

### 工作量：~40 行，长期用

---

## 6. Agent.step() ReAct 循环 → 交互式沙箱参考（P3）

### OpenHands 做了什么

`agent.py` 的 `step()` 是标准 ReAct 循环：

```
step():
  1. 检查 pending actions（确认模式）
  2. prepare_llm_messages（可能触发 condensation）
  3. LLM completion → response
  4. response 有 tool_calls → 构造 ActionEvent → 安全检查 → 批量执行
  5. response 无 tool_calls 有 content → 输出消息
  6. 无 tool_calls 也无 content → 发纠正提示（"请使用工具"）
  7. Context window 超了 → 触发 condensation
```

关键细节：
- 第 6 步的"纠正提示"防止 agent 空转
- 第 4 步支持并行执行多个 tool_calls
- `_ActionBatch` 封装了整个 batch 的生命周期（准备→执行→emit→finalize）

### PathLab 怎么用

这部分在当前仓库里已经有**实验性落地**：
- `code_agent.py` 在 `sandbox_config["interactive"]` 为 true 时，会切到 `_run_interactive()`
- `interactive_agent.py` 提供 `run_command` / `write_file` / `read_file` / `list_files` / `think` / `finish`
- 已实现空响应纠正、stuck detection、history condensation、脚本安全检查

```python
class InteractiveCodeAgent:
    """借鉴 OpenHands Agent.step() 的 ReAct 循环，
    在容器内逐步执行命令。"""
    
    async def step(self, state, sandbox):
        messages = self._prepare_messages(state)
        
        # 可能需要 condensation
        if self._should_condense(messages):
            condensed = await self._condense(messages)
            messages = condensed
        
        response = await self.llm.ainvoke(messages)
        
        if response.tool_calls:
            for tool_call in response.tool_calls:
                if tool_call.name == "run_command":
                    result = await sandbox.execute_command(tool_call.args["command"])
                    state.add_observation(result)
                elif tool_call.name == "write_file":
                    self._write_workspace_file(
                        tool_call.args["path"],
                        tool_call.args["content"],
                    )
                    state.add_observation("Workspace file updated")
                elif tool_call.name == "finish":
                    return "done"
        elif not response.content.strip():
            # 空响应 → 纠正提示（借鉴 OpenHands 第 6 步）
            state.add_message("Your response was empty. Use a tool to proceed.")
        
        return "continue"
```

但它目前仍然属于**实验性**，原因是：
- API / CLI 还没有把 `sandbox_config["interactive"]` 暴露成正式开关
- Docker 路径还没有补齐 `execute_command()`，当前 interactive 更偏向 Apptainer / 基类默认实现
- 文档和主计划里仍把它视为 P3 收尾项是合理的

### 工作量：~100 行，这是架构级改动；仓库已有实验性版本，剩下主要是入口收口与接口补齐

---

## 实施路线

```
P0 ✅ 已完成
├── [1] StuckDetector 纠错刹车           ✅ done
│   └── code_agent.py: _is_fix_loop_stuck + _extract_error_key_line
└── [2] Condenser 历史压缩               ✅ done
    ├── code_agent.py: _condense_code_history
    └── nodes.py: literature_findings condenser 仍未落地

P1 ✅ 已完成（按当前代码语义）
├── [3] BaseWorkspace 风格统一入口       ✅ done
│   ├── 新增 sandbox_base.py (TrainingSandbox ABC + get_sandbox 工厂)
│   ├── code_agent.py / interactive_agent.py 统一走 get_sandbox()
│   ├── 纠错循环复用同一 sandbox 实例
│   └── Docker / Apptainer 仍为兼容接口，未显式继承 TrainingSandbox
└── [4] SecurityAnalyzer 脚本安全        ✅ done
    ├── 新增 script_safety.py (ScriptRisk + assess_script_risk)
    ├── code_agent.py 执行前调用，HIGH 拒绝，MEDIUM 警告
    └── interactive_agent.py 的 write_file(.py) 也复用同一检查

P2/P3（待做 / 部分实验性已存在）
├── [5] ParallelExecutor GPU 锁          ████████    需并行实验时做
└── [6] Agent.step() ReAct              ████████████████      interactive_agent.py 已有实验性版本
```

---

## 与已有 plan 的关系

| 已有文档 | 本文补充 |
|---------|---------|
| `code-agent-modify-plan.md` 改进 1（纠错循环） | 本文 #1 加刹车检测 |
| `code-agent-modify-plan.md` 改进 3（错误模式记忆） | 本文 #1 的 error_key_line |
| `code-agent-modify-plan.md` 改进 2（静态预检） | 本文 #4 的 script_safety |
| `sandbox-improve-plan.md` 改进 3（容器复用） | 本文 #3 的 workspace 抽象 |
| `sandbox-improve-plan.md` 改进 4（交互式沙箱） | 本文 #6 的 ReAct 循环 |
| `auto-research-v2-plan.md` Phase 3.1（Tree Search） | 本文 #5 的并行调度 |

**建议执行顺序**：

1. sandbox streaming（sandbox-improve-plan P0）
2. 纠错循环 + 刹车（code-agent P0 + 本文 #1）
3. 历史压缩（本文 #2）
4. 统一沙箱接口（本文 #3）
5. 脚本安全检查（本文 #4）
6. 其余按需
