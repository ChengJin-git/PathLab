# Code Agent Sandbox 方案调研

> Date: 2026-04-03

## 1. 各主流 Code Agent 的 Sandbox 实现

| Agent | 隔离机制 | GPU | 启动时间 | 重量级 | 适用场景 |
|-------|---------|-----|---------|--------|---------|
| **OpenHands (Docker)** | Docker 容器 + 容器内 FastAPI server | ✅ DeviceRequest | 5-15s | 重 | 生产多租户 |
| **OpenHands (Process)** | subprocess 直接跑 | 宿主机 | 1-2s | 轻 | 本地开发 |
| **mini-SWE (Docker)** | docker exec (长驻容器) | ✅ | 2-5s | 中 | 通用 |
| **mini-SWE (Bubblewrap)** | Linux kernel namespace (无需 root) | ❌ | <1s | 极轻 | Linux 本地 |
| **mini-SWE (Singularity)** | apptainer exec | ✅ | 2-5s | 中 | HPC |
| **Claude Code** | macOS Seatbelt / Linux Bubblewrap | ❌ | ~10ms | 极轻 | 开发者工具 |
| **Codex CLI** | 平台原生 (macOS/Linux) | ❌ | ~10ms | 极轻 | 开发者工具 |
| **AI Scientist v2** | Docker + NVIDIA GPU | ✅ 必须 | 5-15s | 重 | ML 实验 |
| **E2B** | Firecracker microVM | ✅ | ~150ms | 中 | 云端多租户 |
| **Daytona** | 完整 VM | ✅ | 200ms | 中 | 云端 SaaS |
| **gVisor** | 用户态内核 | ❌ | ~100ms | 中 | 安全优先 |

## 2. 隔离技术从强到弱

```
Firecracker microVM (E2B, Daytona)     ← 硬件级隔离, 150-200ms 启动
    ↓
gVisor (Google Cloud)                   ← 用户态内核, 10-30% I/O 开销
    ↓
Docker 容器                             ← kernel namespace, 成熟通用
    ↓
Bubblewrap / Seatbelt (Claude Code)    ← 极轻量, 无需 root, CWD 范围
    ↓
subprocess (无隔离)                     ← 最快, 无保护
```

## 3. 对 PathScientist 的分析

**我们的需求：**
- 跑 ML 训练脚本 (PyTorch, 需要 GPU)
- 本地 GPU 机器 (非云端)
- 单用户使用 (非多租户)
- 脚本由 LLM 生成 (有安全风险)
- 需要挂载数据目录 (read-only)
- 需要写结果到 output 目录

**排除的方案：**
- Firecracker / gVisor / Daytona → 云端方案，本地 GPU 机器不适用
- Bubblewrap / Seatbelt → 不支持 GPU passthrough
- 无隔离 subprocess → 当前方案，LLM 生成的代码直接跑在宿主机有风险

## 4. 推荐方案

### 方案 A: Docker exec（推荐）

像 mini-SWE-agent 的 DockerEnvironment 那样：

```python
# 启动长驻容器 (一次性)
docker run -d --name pathscientist \
    --gpus all \
    -v /data:/data:ro \
    -v /workspace:/workspace:rw \
    -v /output:/output:rw \
    pathlab-sandbox:latest \
    sleep infinity

# 每次执行命令
docker exec pathscientist python /workspace/train.py

# 完成后停掉
docker stop pathscientist && docker rm pathscientist
```

**优点：**
- GPU 支持 (`--gpus all` 或 `--gpus '"device=0"'`)
- 文件系统隔离 (只看到挂载的目录)
- 网络可控 (`--network none` 禁网)
- 资源可限 (`--memory 64g --cpus 16`)
- 启动快 (长驻容器, docker exec ~100ms)
- 成熟稳定

**缺点：**
- 需要 Docker 环境
- 需要维护 sandbox 镜像

### 方案 B: Apptainer exec

像 mini-SWE-agent 的 SingularityEnvironment：

```python
apptainer exec --nv --contain --cleanenv \
    --bind /data:/data:ro \
    --bind /workspace:/workspace:rw \
    --writable-tmpfs \
    pathlab-sandbox.sif \
    python /workspace/train.py
```

**优点：**
- HPC 友好 (无需 root)
- GPU 支持 (`--nv`)
- 已有 .sif 镜像 (auto_research_old/ 里就有)

**缺点：**
- 每次执行启动新进程 (比 docker exec 慢)
- 不如 Docker 灵活

### 方案 C: 混合方案（最实际）

在 `Workspace` 层加一个可选的 docker exec 模式，保持现有 subprocess 作为 fallback：

```python
class Workspace:
    def run_script(self, script_path, env_vars, timeout, sandbox="auto"):
        if sandbox == "docker" or (sandbox == "auto" and docker_available()):
            return self._run_in_docker(script_path, env_vars, timeout)
        else:
            return self._run_local(script_path, env_vars, timeout)  # 现有逻辑
```

**优点：**
- 开发时用 local (快, 无需 Docker)
- 生产时用 docker (安全, GPU, 资源限制)
- 一行配置切换
- 不需要改 agent/tools 代码

## 5. 实现计划（方案 C）

### Task 1: Docker sandbox backend

在 `runtime/` 下新增 `docker_sandbox.py`:
- `DockerSandbox` 类: 管理长驻容器生命周期
- `start()`: 启动容器，挂载 workspace/data/output
- `exec(command)`: docker exec 执行命令
- `stop()`: 停止并清理容器
- GPU passthrough 配置
- 资源限制 (memory, cpus)

### Task 2: 更新 Workspace

在 `runtime/workspace.py` 的 `run_script()` 方法加 sandbox 模式选择:
- `sandbox="local"` → 现有 subprocess (默认, 开发用)
- `sandbox="docker"` → docker exec (生产用)
- `sandbox="auto"` → 有 Docker 用 Docker, 否则 local

### Task 3: Sandbox 镜像

复用现有的 `auto_research_old/pathlab-sandbox.sif` 或 `Dockerfile`:
- PyTorch + CUDA
- 常用 ML 包
- common/ 模板库

### Task 4: Config + CLI 集成

在 `PathScientistConfig` 加:
- `sandbox_mode: str = "auto"`
- `docker_image: str = "pathlab-sandbox:latest"`
- `memory_limit: str = "64g"`
- `cpus: int = 16`

在 CLI 加 `--sandbox docker|local|auto`

### 执行顺序

```
Task 1 (DockerSandbox)     → 核心容器管理
Task 2 (Workspace 集成)    → 切换逻辑
Task 3 (镜像)              → 可复用现有镜像
Task 4 (Config/CLI)        → 配置暴露
```

### 验证

1. `--sandbox local`: 现有行为不变
2. `--sandbox docker`: 脚本在容器内执行, metrics 正确收集
3. `--sandbox docker --gpu 0,1`: GPU passthrough 工作
4. 容器内脚本 crash 不影响宿主机
