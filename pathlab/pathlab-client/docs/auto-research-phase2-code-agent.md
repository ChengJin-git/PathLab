# Auto Research Agent — Phase 2: Code Agent

## Context

Phase 1 只能调 PathLab API 预设参数（extractor × aggregator 组合），无法自定义模型、loss、训练逻辑。Phase 2 引入 Code Agent：agent 基于预置代码模板修改关键部分，在 Docker 沙箱中执行，Karpathy 式棘轮保留改进。

**决策**：
- **执行环境**：Docker 沙箱（GPU 直通，卷挂载数据，安全隔离）
- **代码策略**：模板 + 修改（预置 PathLab 风格训练脚本，agent 只改模型/loss/超参等核心部分）
- **棘轮机制**：改进 → git commit，失败 → git reset

## 架构变化

Phase 1 graph 不变，新增 code_agent 作为 experiment_executor 的替代路径：

```
experiment_planner → human_review
→ code_agent_node（替代 experiment_executor）
    ├─ 1. 选择/修改代码模板
    ├─ 2. 启动 Docker 容器（GPU + 数据卷）
    ├─ 3. 执行训练（固定时长 or 完整训练）
    ├─ 4. 收集结果（metrics + model）
    └─ 5. 棘轮判断：commit or reset
→ results_analyzer → iteration_router
```

## 新增文件

```
server/backend/auto_research/
├── sandbox.py           # DockerSandbox: 容器生命周期管理
├── templates/           # 训练脚本模板
│   ├── classification_template.py
│   ├── survival_template.py
│   └── common/
│       ├── data_loader.py      # WSI 特征加载
│       ├── metrics.py          # AUC/F1/C-Index 计算
│       └── utils.py            # 日志、checkpoint
├── code_agent.py        # CodeAgentNode: LLM 修改模板 + 沙箱执行
└── Dockerfile           # 训练沙箱镜像
```

## 详细设计

### 1. Dockerfile — 训练沙箱镜像

```dockerfile
FROM nvcr.io/nvidia/pytorch:24.05-py3

# PathLab 依赖
RUN pip install --no-cache-dir \
    timm>=1.0.0 einops scikit-learn scipy pandas \
    h5py openslide-python matplotlib seaborn \
    nystrom-attention lifelines

# 工作目录
WORKDIR /workspace
```

构建：`docker build -t pathlab-sandbox .`

### 2. sandbox.py — Docker 沙箱管理

```python
class DockerSandbox:
    """管理训练 Docker 容器的完整生命周期"""

    def __init__(self,
                 image: str = "pathlab-sandbox",
                 gpu_ids: list[str] = None,    # ["0"] or ["0","1"]
                 timeout: int = 600,            # 秒，默认 10 分钟
                 memory_limit: str = "32g",
                 shm_size: str = "8g"):

    async def run_training(self,
                           script_path: str,       # 本地训练脚本路径
                           data_mounts: dict,       # {host_path: container_path}
                           output_dir: str,         # 结果输出目录
                           env_vars: dict = None,
                           ) -> SandboxResult:
        """
        1. 创建容器（GPU 直通 + 数据卷只读挂载 + 输出卷读写）
        2. 复制训练脚本到容器
        3. 执行 python /workspace/train.py
        4. 实时流式读取日志（发射 SSE 事件）
        5. 超时强制停止
        6. 收集 /results/ 下的 metrics.json + model.pth
        7. 清理容器
        """

    async def stream_logs(self, container) -> AsyncGenerator[str, None]:
        """实时流式日志"""

@dataclass
class SandboxResult:
    exit_code: int
    logs: str
    metrics: dict          # 从 /results/metrics.json 解析
    model_path: str | None # 本地路径（如果有 model.pth）
    duration: float        # 执行时长（秒）
    error: str | None
```

容器安全配置：
- `cap_drop=["ALL"]` — 最小权限
- `network_disabled=True` — 禁止网络访问（训练不需要）
- `user="1000:1000"` — 非 root 运行
- `read_only=True` + `tmpfs={"/tmp": "size=4G"}` — 只读 rootfs
- GPU：`device_requests=[DeviceRequest(device_ids=gpu_ids, capabilities=[["gpu"]])]`
- `shm_size="8g"` — PyTorch DataLoader 需要

数据挂载（只读）：
```python
volumes = {
    uploads_dir / "features": {"bind": "/data/features", "mode": "ro"},
    uploads_dir / "wsi_files": {"bind": "/data/wsi", "mode": "ro"},
    uploads_dir / "coordinates": {"bind": "/data/coordinates", "mode": "ro"},
    output_dir: {"bind": "/results", "mode": "rw"},
}
```

### 3. templates/ — 训练脚本模板

基于 PathLab 现有 `ai/tasks/wsi_classification/trainer.py` 简化为独立可执行脚本。

#### classification_template.py（~200 行）

```python
"""
PathLab Classification Training Template
=========================================
AI Agent 可修改的区域用 ### MODIFIABLE ### 标记。
不可修改的区域用 ### FIXED ### 标记（数据加载、评估指标、结果保存）。
"""

# === FIXED: 数据加载 ===
from common.data_loader import load_features, create_splits
from common.metrics import compute_classification_metrics
from common.utils import save_results, setup_logging

# === MODIFIABLE: 模型定义 ===
### MODIFIABLE START: model ###
import torch
import torch.nn as nn

class MILAggregator(nn.Module):
    """Agent 可以修改这个类的结构"""
    def __init__(self, in_dim=1024, num_classes=2, hidden_dim=256):
        super().__init__()
        self.attention = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1)
        )
        self.classifier = nn.Sequential(
            nn.Linear(in_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.25),
            nn.Linear(hidden_dim, num_classes)
        )

    def forward(self, H):
        # H: (N_patches, D)
        A = torch.softmax(self.attention(H), dim=0)  # (N, 1)
        M = (A * H).sum(dim=0, keepdim=True)           # (1, D)
        logits = self.classifier(M)                      # (1, C)
        return logits, A.squeeze(-1)
### MODIFIABLE END: model ###

### MODIFIABLE START: loss ###
def get_criterion(num_classes, class_weights=None):
    if class_weights is not None:
        return nn.CrossEntropyLoss(weight=torch.tensor(class_weights).float())
    return nn.CrossEntropyLoss()
### MODIFIABLE END: loss ###

### MODIFIABLE START: hyperparams ###
LEARNING_RATE = 0.0001
EPOCHS = 50
OPTIMIZER = "adamw"      # adam, sgd, adamw
BATCH_SIZE = 1            # MIL: 1 bag per batch
EARLY_STOPPING_PATIENCE = 10
SCHEDULER = "cosine"      # cosine, step, none
### MODIFIABLE END: hyperparams ###

# === FIXED: 训练循环 ===
def train():
    # 1. 加载数据
    features, labels, splits = load_features(
        features_dir="/data/features",
        split_file="/data/splits.json"
    )

    # 2. 创建模型
    in_dim = features[list(features.keys())[0]].shape[-1]
    num_classes = len(set(labels.values()))
    model = MILAggregator(in_dim=in_dim, num_classes=num_classes).cuda()

    # 3. 创建优化器
    criterion = get_criterion(num_classes)
    if OPTIMIZER == "adamw":
        optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE)
    elif OPTIMIZER == "sgd":
        optimizer = torch.optim.SGD(model.parameters(), lr=LEARNING_RATE, momentum=0.9)
    else:
        optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)

    if SCHEDULER == "cosine":
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    else:
        scheduler = None

    # 4. 训练循环
    best_val_metric = 0.0
    patience_counter = 0

    for epoch in range(1, EPOCHS + 1):
        model.train()
        train_loss = 0.0
        for wsi_id in splits["train"]:
            H = features[wsi_id].cuda()
            label = torch.tensor([labels[wsi_id]]).cuda()
            optimizer.zero_grad()
            logits, _ = model(H)
            loss = criterion(logits, label)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        if scheduler:
            scheduler.step()

        # 5. 验证
        val_metrics = compute_classification_metrics(
            model, features, labels, splits["val"]
        )
        print(f"Epoch {epoch}/{EPOCHS} | loss={train_loss/len(splits['train']):.4f} | "
              f"val_auc={val_metrics['auc']:.4f} | val_acc={val_metrics['accuracy']:.4f}")

        # 6. Early stopping
        if val_metrics["auc"] > best_val_metric:
            best_val_metric = val_metrics["auc"]
            patience_counter = 0
            torch.save(model.state_dict(), "/results/best_model.pth")
        else:
            patience_counter += 1
            if patience_counter >= EARLY_STOPPING_PATIENCE:
                print(f"Early stopping at epoch {epoch}")
                break

    # 7. 测试集评估
    model.load_state_dict(torch.load("/results/best_model.pth"))
    test_metrics = compute_classification_metrics(
        model, features, labels, splits["test"]
    )

    # 8. 保存结果
    save_results("/results/metrics.json", {
        "best_val_auc": best_val_metric,
        "test": test_metrics,
        "epochs_trained": epoch,
        "hyperparams": {
            "lr": LEARNING_RATE, "epochs": EPOCHS,
            "optimizer": OPTIMIZER, "scheduler": SCHEDULER,
        }
    })

if __name__ == "__main__":
    train()
```

#### common/data_loader.py（FIXED，不可修改）

从 `/data/features/` 加载 .pt 文件，从 `/data/splits.json` 读取划分。这部分复用 PathLab 的 `WSIFeatureDataset` 逻辑简化版。

#### common/metrics.py（FIXED）

`compute_classification_metrics(model, features, labels, wsi_ids)` → `{auc, accuracy, f1, precision, recall}`
`compute_survival_metrics(model, features, times, statuses, wsi_ids)` → `{c_index}`

### 4. code_agent.py — Code Agent 节点

```python
class CodeAgentNode:
    """
    LLM 修改训练模板 → Docker 沙箱执行 → 棘轮判断。
    替代 Phase 1 的 experiment_executor + experiment_monitor。
    """

    async def __call__(self, state: AutoResearchState) -> Command:
        """
        1. 选择模板（classification / survival）
        2. 准备上下文（文献、know-how、上轮结果）
        3. LLM 修改模板的 MODIFIABLE 区域
        4. 保存修改后的脚本到临时目录
        5. 启动 DockerSandbox.run_training()
        6. 收集 metrics.json
        7. 棘轮判断：
           - metric > best → git commit, 更新 best
           - metric <= best → git reset, 丢弃
        8. 返回 completed_results
        """
```

LLM Prompt 关键部分：

```
你是一个计算病理学代码专家。修改以下训练脚本的 MODIFIABLE 区域。

当前研究问题：{research_question}
文献推荐的方法：{literature_findings}
上轮结果：{comparison_table}
Know-How 推荐：{knowhow}

修改规则：
1. 只修改 ### MODIFIABLE START ### 和 ### MODIFIABLE END ### 之间的代码
2. 不要修改 FIXED 区域（数据加载、评估指标、结果保存）
3. 你可以：改模型结构、改 loss 函数、改超参数、加正则化
4. 保持代码可运行（正确的 import、正确的变量名）

输出完整的修改后脚本（包括未修改的 FIXED 部分）。
```

### 5. 棘轮机制

```python
class RatchetManager:
    """Karpathy 式棘轮：改进保留，失败丢弃"""

    def __init__(self, workspace_dir: str):
        self.workspace = Path(workspace_dir)
        # git init workspace
        self._git("init")

    def commit_improvement(self, script_path: str, metrics: dict, message: str):
        """改进了 → git add + commit"""
        shutil.copy(script_path, self.workspace / "train.py")
        self._git("add", "train.py")
        self._git("commit", "-m", f"{message} | metrics={json.dumps(metrics)}")

    def reset_failure(self):
        """没改进 → git reset 回到上一个 commit"""
        self._git("checkout", "--", "train.py")

    def get_history(self) -> list[dict]:
        """获取改进历史"""
        # git log --oneline → parse

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.workspace)] + list(args), ...)
```

### 6. Graph 集成

修改 `builder.py`：experiment_planner 输出的 experiment_plan 增加 `mode` 字段：

- `mode: "api"` → 走 Phase 1 的 experiment_executor（调 PathLab API）
- `mode: "code"` → 走 Phase 2 的 code_agent_node（Docker 沙箱）

```python
# human_review 之后的路由
def route_after_review(state):
    if state["plan_approved"]:
        mode = state["experiment_plan"][0].get("mode", "api")
        if mode == "code":
            return "code_agent"
        return "experiment_executor"
    return "experiment_planner"
```

### 7. State 扩展

新增字段到 `AutoResearchState`：

```python
# Code Agent
code_mode: bool = False           # True = 用 code agent，False = 用 PathLab API
code_workspace: str = ""          # git 工作区路径
code_history: list[dict] = []     # [{iteration, script_diff, metrics, committed}]
sandbox_config: dict = {}         # {gpu_ids, timeout, memory_limit}
```

### 8. Docker 依赖

`requirements.txt` 添加：
```
docker>=7.0.0
```

## Implementation Order

| Sprint | 内容 | 预估 |
|--------|------|------|
| 1 | Dockerfile + sandbox.py（容器管理） | 2-3 天 |
| 2 | templates/（classification + survival + common/） | 2-3 天 |
| 3 | code_agent.py + RatchetManager + LLM prompt | 3-4 天 |
| 4 | 集成到 graph（builder 路由 + state 扩展 + API） | 2-3 天 |
| 5 | 端到端测试（LLM 改模板 → Docker 跑 → 收结果 → 棘轮） | 2-3 天 |

## Verification

1. `docker build -t pathlab-sandbox .` — 镜像构建成功
2. 手动跑模板：`docker run --gpus all -v data:/data:ro pathlab-sandbox python train.py` — 训练成功
3. LLM 修改模板后仍可运行（语法正确、import 正确）
4. 棘轮：改进 → `git log` 有新 commit；失败 → 代码回退到上一版本
5. 完整流程：research_question → 文献 → 设计 → LLM 改代码 → Docker 跑 → 指标对比 → 迭代
6. 超时：容器运行超过 timeout 被强制 kill
7. GPU 隔离：指定 GPU ID 正确传递
