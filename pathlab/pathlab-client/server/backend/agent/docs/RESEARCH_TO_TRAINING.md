# Deep Research 与 Training 衔接方案

## 一、现状

### 1.1 Deep Research 输出

- **`final_report`**：Markdown 报告，含 7 节，其中 **Section 7. Model Configuration JSON** 为结构化 JSON，可直接用于下游：
  - `task_type`: `"WSI-level classification"` | `"patch-level classification"` | `"pixel-level segmentation"`
  - `label_schema`: `type`, `classes`, `granularity`
  - `data_requirements`: `wsi_format`, `magnification`, `patch_size`, `patch_stride`, `min_wsi_per_class`, `annotation_type`
  - `model_architecture`: `feature_extractor`, `feature_dim`, `aggregator`, `segmentation_arch`
  - `training_config`: `learning_rate`, `batch_size`, `optimizer`, `epochs`, `early_stopping`

### 1.2 Training 所需输入（POST /tasks/training）

| 字段 | 来源 | 说明 |
|------|------|------|
| `task_name` | 用户 / 报告摘要 | 必填 |
| `task_type` | 报告 | `classification` \| `segmentation` |
| `data_level` | 报告 | `wsi` \| `patch` |
| **`wsi_ids`** | **用户选择** | 报告**无法提供**，必须先 `list_wsi`，再由用户或 agent 定 |
| `preprocessing` | 报告 + 默认 | `tile_size`, `stride`, `level`, `feature_extractor`, `feature_batch_size` + 分割/过滤默认 |
| `model` | 报告 + 默认 | `epochs`, `learning_rate`, `aggregator` |
| `task_description` | 报告 / 用户 | 可选 |

### 1.3 主图 (graph.py) 与 Research

- 主图：`START -> _route -> [research | llm] -> END`
- `_route`：`/research` 或 `research_status in (awaiting_user, running)` → research，否则 → llm
- Research 完成后：`final_report` 写入 state，`research_status=done`，并清理 `research_brief`、`supervisor_messages` 等

---

## 二、Research JSON → Training 参数映射

Section 7 已增加 **`training`** 对象，与 PathLab `create_training_task` / pipeline 字段一一对应。Adapter 优先使用 **`research_json["training"]`**，无则再从 `model_architecture`、`data_requirements`、`training_config` 做映射。

### 2.1 使用 `training` 块（推荐）

若 `parse_model_config_from_report` 得到的结构中含有 `"training"`，可直接：

- `params = research_json["training"].copy()`
- 删除或忽略 `training` 中不传给 API 的 key（若有）
- 补充 `task_name`、`wsi_ids`（必有，来自用户）、`task_description`（可选）

`training` 中字段与 API 对应关系：

| `training` 字段 | create_training_task / preprocessing / model | 说明 |
|-----------------|---------------------------------------------|------|
| `task_type` | `task_type` | classification \| segmentation |
| `data_level` | `data_level` | wsi \| patch |
| `tile_size` | `preprocessing.tile_size` |  |
| `stride` | `preprocessing.stride` |  |
| `level` | `preprocessing.level` |  |
| `feature_extractor` | `preprocessing.feature_extractor` | 须为 PathLab 支持 id：resnet50, uni, conch, phikon, virchow, plip, patho_clip, vit_l_16, uni2, phikon2, virchow2, conch15, openmidnight, mSTAR, GPFM, H-Optimus-0, H-Optimus-1 |
| `feature_batch_size` | `preprocessing.feature_batch_size` |  |
| `epochs` | `model.epochs` |  |
| `learning_rate` | `model.learning_rate` |  |
| `aggregator` | `model.aggregator` | 仅 abmil, meanmil, maxmil |

### 2.2 无 `training` 时从旧结构映射（兼容）

| Research (Section 7) | Training / Pipeline | 备注 |
|---------------------|---------------------|------|
| `task_type` "WSI-level classification" | `task_type=classification`, `data_level=wsi` |  |
| `task_type` "patch-level classification" | `task_type=classification`, `data_level=patch` |  |
| `task_type` "pixel-level segmentation" | `task_type=segmentation`, `data_level=wsi` |  |
| `data_requirements.patch_size` | `preprocessing.tile_size` | 默认 512 |
| `data_requirements.patch_stride` | `preprocessing.stride` | 默认 512 |
| `data_requirements.level` | `preprocessing.level` | 默认 0 |
| `model_architecture.feature_extractor` | `preprocessing.feature_extractor` | 需名称归一，与 AI 服务一致 |
| `model_architecture.aggregator` | `model.aggregator` | abmil, meanmil, maxmil |
| `training_config.learning_rate` | `model.learning_rate` | 默认 1e-4 |
| `training_config.epochs` | `model.epochs` | 默认 10 |
| `training_config.batch_size` | `preprocessing.feature_batch_size` | 默认 256 |

`task_name`、`task_description` 可由报告 Executive Summary 或用户输入生成，没有时用默认如 `"from_research_<date>"`。

---

## 三、衔接架构选项

### 方案 A：主图增加 training 节点（与 research、llm 并列）

- **路由**：  
  - `/training` 或 “根据报告建训练任务” / “用报告参数建任务” → `training`  
  - 若 `research_status=done` 且 `final_report` 存在且用户意图为“建训练任务”，也 → `training`
- **training 节点**：  
  - 若 state 有 `final_report`：解析 Section 7 的 ```json``` → `report_config`，再 `model_config_to_training_params(report_config)` → `initial_training_params`（**不含** `wsi_ids`）。  
  - 调用 `create_training_graph().invoke/ainvoke`，传入 state：  
    - `messages`：注入一条 `HumanMessage`，例如：「根据研究报告创建训练任务。建议参数已从报告中解析。请先 `list_wsi`，由用户选择 `wsi_ids`，再用建议参数 `propose_create_training_task`。」  
    - `initial_training_params`：上面得到的 dict。  
    - `proposed_training`：`None`。
- **Training 图扩展**：  
  - `TrainingState` 增加 `initial_training_params: dict | None`。  
  - Agent 的 system 或首条 system 中：若存在 `initial_training_params`，则附加说明及 `json.dumps(initial_training_params)`，要求：先 `list_wsi`，用报告参数 + 用户选的 `wsi_ids` 调用 `propose_create_training_task`。  
  - 原有 clarify（propose → 确认/修改）流程不变，`initial_training_params` 仅作 propose 的默认填入。
- **优点**：统一入口，Research 结束后可直接在同一对话中“根据报告建任务”。  
- **缺点**：需改主图路由、training 子图状态与 prompt，以及 __main__ 的 state 传递。

### 方案 B：仅做 Report→Params 适配器，Training 图可选接收“建议参数”

- **不**改主图路由；主图仍只有 `research` 与 `llm`。
- **新增**：  
  - `backend/agent/adapters/report_to_training.py`：  
    - `parse_model_config_from_report(final_report: str) -> dict | None`：从 Section 7 或全文最后一个 ```json 块解析 JSON。  
    - `model_config_to_training_params(research_json: dict) -> dict`：按上表映射，得到 `CreateTrainingTaskInput` 风格 dict（不含 `wsi_ids`）。
- **Training 图**：  
  - 支持 `create_training_graph(..., initial_training_params: dict | None)` 或在 state 传入 `initial_training_params`；  
  - Agent 在存在 `initial_training_params` 时，将其作为 propose 的默认值，仍要求先 `list_wsi` 再 propose。  
- **调用方式**：  
  - **REPL**：Research 结束后，在 __main__ 打印「若要根据报告创建训练任务，可运行：  
    `uv run python -m backend.agent.training.run_chat --from-report`」，  
    该模式从 stdin 或 `--report-file` 读取 `final_report`，解析 → `initial_training_params`，再启动 `run_chat` 并注入到 training 的 state。  
  - **或**：在前端/另一个服务中，用 `parse_model_config_from_report` + `model_config_to_training_params` 得到 params，再调用 `create_training_graph` 或直接 `create_training_task`（若已有 `wsi_ids`）。
- **优点**：改动小，Research 与 Training 解耦；便于单独测试 adapter 和 training。  
- **缺点**：需要用户多一步（如切到 `run_chat --from-report` 或另一个 UI）。

### 方案 C：Research 完成后自动弹出“创建训练任务”的引导，逻辑仍在主图外

- 主图与 Research 逻辑不变。  
- Research 完成后，在 __main__ 或前端：  
  - 若存在 `final_report`，打印/展示「根据报告创建训练任务：`/training from-report`」或一个按钮。  
  - 用户输入 `/training from-report` 时，**不**走主图的 `research`/`llm`，而是：  
    - 从**上一轮** state 中取 `final_report`（或专门缓存的 `last_final_report`）；  
    - 解析 → `initial_training_params`；  
    - 直接 `create_training_graph().invoke`，state 带 `messages=[HumanMessage("根据报告建训练任务，请先 list_wsi。")]` 与 `initial_training_params`。  
- 相当于：主图只负责“何时跳转”的入口，真正执行的是独立的一次 training 子图调用；`/training from-report` 可在 `_route` 中识别并指向一个 `training_from_report` 节点，该节点做解析+调用 training 图。
- **优点**：Research 与 Training 仍较清晰；用户意图明确（“根据报告”）。  
- **缺点**：需要主图能拿到“上一轮”的 `final_report`（通常已有），并在路由里区分 `/training` 与 `/training from-report`。

---

## 四、推荐实施顺序

### 阶段 1：Adapter（方案 B 的公共部分，所有方案都会用到）

1. **新建** `backend/agent/adapters/`（或放在 `backend/agent/utils/`）：  
   - `parse_model_config_from_report(final_report: str) -> dict | None`  
     - 定位 `## 7. Model Configuration JSON` 或 `## 7.` 后的第一个 ```json ... ```；  
     - 若无，再尝试文中最后一个 ```json ... ```；  
     - `json.loads` 失败则返回 `None`。  
   - `model_config_to_training_params(research: dict) -> dict`  
     - 输入：Section 7 的 JSON（或兼容子集）；  
     - 输出：与 `CreateTrainingTaskInput` 对齐的 flat dict，**不含** `wsi_ids`，含：  
       - `task_name`, `task_type`, `data_level`, `task_description`（可为 None）  
       - `tile_size`, `stride`, `level`, `feature_extractor`, `feature_batch_size`  
       - `epochs`, `learning_rate`, `aggregator`  
     - 对 `feature_extractor`、`aggregator` 做简单归一（小写、常见别名→AI 服务名）。

### 阶段 2：Training 图支持“建议参数”

1. **`TrainingState`** 增加 `initial_training_params: dict | None`。  
2. **`create_training_graph`**：  
   - 若通过 state 或参数传入 `initial_training_params`，在构造 agent 的 system 时追加：  
     - 说明这些来自 research 报告；  
     - 要求先 `list_wsi`，再用 `initial_training_params` 与用户提供的 `wsi_ids` 调用 `propose_create_training_task`；  
     - 未在 `initial_training_params` 中的字段用 tool 默认值。  
3. **`run_chat`**：  
   - 支持 `--from-report` 或 `--report-file`：  
     - 读入 `final_report` 文本；  
     - `parse_model_config_from_report` → `model_config_to_training_params` → `initial_training_params`；  
     -  invoke 时 state 带 `initial_training_params` 与一条说明性 `HumanMessage`。  

这样即使不接主图，也能用「保存的 report + run_chat --from-report」完成 Research→Training 的闭环。

### 阶段 3：与主图接在一起（方案 A 或 C）

- **方案 A**：  
  - 主图 `_route` 增加对 `/training` 以及（当 `research_status=done` 且 `final_report` 存在时）“根据报告建任务”类意图 → `training`。  
  - 新增节点 `training`：  
    - 从 state 取 `final_report`，解析得到 `initial_training_params`；  
    - 构造 `messages`（含“根据报告创建训练任务，请先 list_wsi”等）；  
    - 调用已支持 `initial_training_params` 的 `create_training_graph`，将子图返回的 `messages` 等合并回主图 state。  
  - `AgentState` 需能携带 `final_report` 或 `initial_training_params` 供 `training` 使用；若 research 刚跑完，`final_report` 已在 state 中。  

- **方案 C**：  
  - 主图 `_route` 识别 `/training from-report`（且 preferably `final_report` 存在）→ 新节点 `training_from_report`。  
  - `training_from_report`：与方案 A 的 `training` 类似，但从 state 取 `final_report`，解析后只调用一次 training 子图，不区分“一般 /training”与“根据报告 /training”的兩种节点实现时可复用同一子图，仅 `initial_training_params` 是否为空不同。  

- **__main__**：  
  - 若走 training 子图，其返回的 `messages` 可能有多条（list_wsi、propose、clarify、create 等）；  
  - 主循环需像对待 research 一样，按 `messages` 或 `proposed_training` 等决定展示与下一轮输入，具体可与现有 `run_chat` 逻辑对齐。

---

## 五、名称归一（feature_extractor / aggregator）

- **若使用 Section 7 的 `training` 块**：prompt 已约束 `feature_extractor`、`aggregator` 为 PathLab 支持的 id，一般无需再归一。
- **若从 `model_architecture` / `training_config` 等 fallback 映射**：建议在 `model_config_to_training_params` 中做名称归一，例如 UNI/Uni→uni、ABMIL→abmil、MeanMIL→meanmil、MaxMIL→maxmil，未知时回退 resnet50、abmil。具体以 `backend/ai` 的 `extractors/registry`、`aggregators/registry` 为准。

---

## 六、文件级改动一览

| 文件 | 改动 |
|------|------|
| **新建** `backend/agent/adapters/__init__.py` | 空或导出 `parse_model_config_from_report`, `model_config_to_training_params` |
| **新建** `backend/agent/adapters/report_to_training.py` | `parse_model_config_from_report`（优先取 `training` 所在 ```json 块）；`model_config_to_training_params` 优先用 `research_json["training"]`，无则从 `model_architecture`/`data_requirements`/`training_config` 映射 + 名称归一 |
| `backend/agent/training/src/training/graph.py` | `TrainingState` 增加 `initial_training_params`；agent 在存在时附加说明与默认；`create_training_graph` 支持从 state 读入 |
| `backend/agent/training/run_chat.py` | `--from-report` / `--report-file`，读 report → 解析 → 传入 `initial_training_params` |
| `backend/agent/graph.py` | 若采用方案 A：`_route` 增加 `training` 分支；新节点 `_training_node`，内部解析 `final_report` 并调用 training 子图；`AgentState` 若需可加 `initial_training_params`（也可由 `_training_node` 内部解析，不持久化到主 state） |
| `backend/agent/__main__.py` | 若 training 子图返回多轮 `messages`：按 `proposed_training`、`messages` 等做展示与循环，类似 research；Research 完成后可打印“根据报告建任务：/training from-report”等提示 |

---

## 七、数据流小结

```
[User] /research  MSIH 分类的 WSI 深度研究
    → research 子图
    → final_report（含 Section 7 JSON）

[User] 根据报告建训练任务  或  /training from-report
    → parse_model_config_from_report(final_report) → research_json
    → model_config_to_training_params(research_json) → initial_training_params（无 wsi_ids）

    → training 子图
        state: messages=[说明 + “请先 list_wsi”], initial_training_params=...
    → agent: list_wsi → 用户提供 wsi_ids（或 agent 基于当前 list 选）
    → agent: propose_create_training_task( **merge(initial_training_params, {wsi_ids}) )
    → 用户确认/修改 → create_training_task
    → 返回 task_id，pipeline 运行
```

`wsi_ids` 始终在 training 阶段、在 `list_wsi` 之后由用户或 agent 决定，报告只提供除 `wsi_ids` 以外的建议参数。
