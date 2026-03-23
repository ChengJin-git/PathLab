# Codebase Refactoring — 高内聚低耦合 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 去除冗余模块、收紧模块边界，达到高内聚低耦合——每个文件只做一件事，跨模块依赖通过清晰接口传递。

**Architecture:** 纯重构，不引入新功能。每个 Task 独立可验证，失败可回滚。执行顺序从低风险到高风险。Python backend 和 TypeScript frontend 各自构成独立 Task 组，可并行执行。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy（backend）；React 18 + TypeScript + Vite（frontend）；Vitest（frontend tests）；pytest + pytest-asyncio（backend tests）。

**不改动范围：**
- `server/backend/deep-research/` — 未完成功能，跳过
- `pathlab/pathlab-server/` — 未完成功能，跳过

---

## 文件变动总览

### 新建文件
| 文件 | 职责 |
|---|---|
| `server/backend/common/chat_context_builder.py` | 聚合多个 Repository 的用户上下文数据（从 gateway/main.py 提取） |
| `server/gateway/routes/analysis_utils.py` | analysis_base + analysis_helpers 合并后的统一工具模块 |
| `server/gateway/routes/access_control.py` | gateway 层所有权/角色校验的统一辅助函数 |

### 删除文件
| 文件 | 原因 |
|---|---|
| `server/gateway/routes/analysis_base.py` | 内容并入 analysis_utils.py |
| `server/gateway/routes/analysis_helpers.py` | 内容并入 analysis_utils.py |

### 修改文件
| 文件 | 变动 |
|---|---|
| `server/gateway/main.py` | 删除 `_build_chat_context_cache_for_user`，改为 import |
| `server/gateway/routes/classification_analysis.py` | 更新 analysis_base/helpers → analysis_utils |
| `server/gateway/routes/segmentation_analysis.py` | 同上 |
| `server/gateway/routes/survival_analysis.py` | 同上 |
| `server/gateway/routes/external_validation_analysis.py` | 同上 |
| `server/gateway/routes/results.py` | analysis_helpers → analysis_utils |
| `server/gateway/routes/chat.py` | check_data_ownership → access_control.assert_owner |
| `server/gateway/routes/training.py` | 同上 |
| `server/gateway/routes/models.py` | 同上 |
| `server/gateway/routes/queue.py` | 同上 |
| `server/gateway/routes/results.py` | 同上 |
| `server/gateway/routes/ai_tasks.py` | 同上 |
| `server/gateway/routes/storage.py` | 同上 |
| `src/renderer/src/lib/utils.ts` | 删除废弃的 `formatBytes` alias |
| `src/renderer/src/api/index.ts` | 删除 `export * from './annotation'`（已迁移）及不必要的全量 re-export |
| `src/renderer/src/constants/training.ts` | 加注释说明静态兜底角色 |
| `src/renderer/src/constants/trainingOptionsBootstrap.ts` | 加注释说明运行时覆盖角色 |
| `src/renderer/src/lib/useRealtimeASR.ts` | barrel → direct import |
| `src/renderer/src/lib/useDataSelection.ts` | barrel → direct import |
| `src/renderer/src/lib/externalValidationUtils.ts` | barrel → direct import |
| `src/renderer/src/components/RegisterRequestModal.tsx` | barrel → direct import |
| `src/renderer/src/components/DisclaimerModal.tsx` | barrel → direct import |
| `src/renderer/src/components/ChangePasswordModal.tsx` | barrel → direct import |
| `src/renderer/src/components/WSIViewer.tsx` | barrel → direct import |
| `src/renderer/src/components/results/AnalysisDetails.tsx` | barrel → direct import |
| `src/renderer/src/components/wsiViewer/*.tsx` | barrel → direct import（多个文件） |
| `src/renderer/src/components/settings/*.tsx` | barrel → direct import（多个文件） |
| `src/renderer/src/components/list/*.tsx` | barrel → direct import |

---

## Task 1: 删除 `formatBytes` 废弃 alias [Frontend — 低风险]

**文件:**
- Modify: `pathlab/pathlab-client/src/renderer/src/lib/utils.ts`
- Search all: `src/renderer/src/**/*.{ts,tsx}`

- [ ] **Step 1: 确认 baseline 测试全绿**

```bash
cd pathlab/pathlab-client
npm run test:run
```
Expected: 所有 test 文件通过。

- [ ] **Step 2: 找出所有 formatBytes 使用点**

```bash
grep -rn "formatBytes" src/renderer/src --include="*.tsx" --include="*.ts"
```
记录每个文件及行号。

- [ ] **Step 3: 读 utils.ts，确认 formatBytes 确是 formatFileSize 的 alias，签名相同**

```bash
grep -n "formatBytes\|formatFileSize" src/renderer/src/lib/utils.ts
```

- [ ] **Step 4: 逐文件将 `formatBytes` 替换为 `formatFileSize`**

对 Step 2 找到的每个文件，修改 import 和调用点。

- [ ] **Step 5: 从 utils.ts 删除 formatBytes 导出行**

- [ ] **Step 6: 运行测试**

```bash
npm run test:run
```
Expected: 全部通过。

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(frontend): remove deprecated formatBytes alias, use formatFileSize"
```

---

## Task 2: 提取 `_build_chat_context_cache_for_user` 到独立模块 [Backend — 中风险]

**背景:** `gateway/main.py` L69-245 包含 177 行业务数据聚合逻辑，与启动生命周期代码混杂，违反单一职责。将其提取到 `backend/common/chat_context_builder.py`，使 main.py 只处理启动/关闭生命周期。

**文件:**
- Create: `pathlab/pathlab-client/server/backend/common/chat_context_builder.py`
- Modify: `pathlab/pathlab-client/server/gateway/main.py` (删除函数定义，增加 import)

- [ ] **Step 1: 确认 baseline 后端测试全绿**

```bash
cd pathlab/pathlab-client
python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
```
Expected: 116 tests passed.

- [ ] **Step 2: 读 gateway/main.py L69-245，完整理解函数依赖**

```bash
sed -n '1,10p' server/gateway/main.py    # 查看 imports
sed -n '69,245p' server/gateway/main.py  # 查看完整函数体
```
注意函数内部的 `from .routes.chat_pdf_vectorstore import _embed_texts` 是内联 import，保持原样。

- [ ] **Step 3: 用脚本生成 `server/backend/common/chat_context_builder.py`**

运行以下命令自动提取函数体并写入新文件：

```bash
# 1. 写文件头
cat > server/backend/common/chat_context_builder.py << 'HEADER'
"""
chat_context_builder.py
=======================
Aggregates per-user stats from multiple Repositories into the kwargs dict
consumed by chat_context_cache.set_cached_context_kwargs().

Extracted from gateway/main.py to keep gateway startup logic focused on
lifecycle management only.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database import async_session
from backend.database.models import TrainingTask
from backend.database.repositories import (
    AITaskRepository,
    TrainingTaskRepository,
    TrainedModelRepository,
    WSIRepository,
)

logger = logging.getLogger(__name__)


async def build_chat_context_for_user(user_id: str | None) -> dict[str, Any]:
    """
    Build context kwargs for a single user, or admin global scope when user_id is None.

    Returns the dict passed to set_cached_context_kwargs() / set_cached_context_kwargs_admin().
    """
HEADER

# 2. 提取函数体（L70-245 是函数体行，L69 是 def 行已在头部声明）
#    gateway/main.py 中函数 def 在 L69，函数体从 L70 开始到 L245
sed -n '70,245p' server/gateway/main.py >> server/backend/common/chat_context_builder.py
```

验证提取结果正确（函数体的最后一行应为 return 语句）：

```bash
tail -5 server/backend/common/chat_context_builder.py
```
Expected: 看到 `"inference_tasks_list": inference_tasks_list,` 和 `}` 等 return dict 内容。

- [ ] **Step 4: 修改 `gateway/main.py`**

a. 删除 L69-245 的 `_build_chat_context_cache_for_user` 函数定义。

b. 在文件顶部 import 区域（其他 from backend.common 旁边）增加：

```python
from backend.common.chat_context_builder import build_chat_context_for_user
```

c. 在 `_startup_prewarm_chat_context_cache` 函数内，将调用点：

```python
kwargs = await _build_chat_context_cache_for_user(uid)
```
改为：
```python
kwargs = await build_chat_context_for_user(uid)
```

同样更新 admin scope 调用：
```python
admin_kwargs = await _build_chat_context_cache_for_user(user_id=None)
```
改为：
```python
admin_kwargs = await build_chat_context_for_user(user_id=None)
```

- [ ] **Step 5: import 健康检查**

```bash
python -c "from backend.common.chat_context_builder import build_chat_context_for_user; print('OK')"
python -c "from gateway.main import app; print('OK')"
```
Expected: 两行都打印 OK，无报错。

- [ ] **Step 6: 运行后端测试**

```bash
python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
```
Expected: 116 tests passed.

- [ ] **Step 7: Commit**

```bash
git add server/backend/common/chat_context_builder.py server/gateway/main.py
git commit -m "refactor(backend): extract chat context builder from gateway/main.py to backend/common"
```

---

## Task 3: 合并 analysis_base + analysis_helpers → analysis_utils [Backend — 中风险]

**背景:** `analysis_base.py`（175 行，进度/图表辅助）和 `analysis_helpers.py`（181 行，任务/权限访问辅助）被完全相同的 4 个消费者同时导入（classification/segmentation/survival/external_validation）。两文件边界模糊、总行数小，合并为 `analysis_utils.py` 减少 import 数量，边界更清晰。`analysis_state.py`（独立状态类）和 `analysis_metrics.py`（独立指标计算）不合并，各自职责清晰。

**文件:**
- Create: `server/gateway/routes/analysis_utils.py`
- Delete: `server/gateway/routes/analysis_base.py`
- Delete: `server/gateway/routes/analysis_helpers.py`
- Modify: `classification_analysis.py`, `segmentation_analysis.py`, `survival_analysis.py`, `external_validation_analysis.py`, `results.py`

- [ ] **Step 1: 读取两文件全文，记录所有 public symbol**

```bash
grep -n "^def \|^async def \|^class " \
  server/gateway/routes/analysis_base.py \
  server/gateway/routes/analysis_helpers.py
```

- [ ] **Step 2: 确认消费者 import 清单**

```bash
grep -n "from .analysis_base\|from .analysis_helpers" \
  server/gateway/routes/classification_analysis.py \
  server/gateway/routes/segmentation_analysis.py \
  server/gateway/routes/survival_analysis.py \
  server/gateway/routes/external_validation_analysis.py \
  server/gateway/routes/results.py
```
记录每个文件导入了哪些 symbol。

- [ ] **Step 3: 用命令生成 `server/gateway/routes/analysis_utils.py`**

运行以下命令将两文件拼接为合并文件：

```bash
# 写文件头
cat > server/gateway/routes/analysis_utils.py << 'HEADER'
"""
analysis_utils.py
=================
Shared utilities for analysis route handlers.

Merged from:
  - analysis_base.py   (progress config helpers, chart generation wrappers)
  - analysis_helpers.py (task/dataset access checks, seed helpers, coercion utils)

analysis_metrics.py and analysis_state.py remain separate — they have distinct,
well-bounded responsibilities.
"""

HEADER

# 追加 analysis_base.py 完整内容（含其 from .analysis_metrics import 行，保持不变）
cat server/gateway/routes/analysis_base.py >> server/gateway/routes/analysis_utils.py

# 分隔注释
echo -e "\n\n# ── from analysis_helpers.py ──────────────────────────────────────────────\n" \
  >> server/gateway/routes/analysis_utils.py

# 追加 analysis_helpers.py 完整内容
cat server/gateway/routes/analysis_helpers.py >> server/gateway/routes/analysis_utils.py
```

验证合并结果：

```bash
# 应包含 analysis_base 和 analysis_helpers 两个文件的所有 def/class
grep -n "^def \|^async def \|^class " server/gateway/routes/analysis_utils.py
```
Expected: 看到 `unpack_progress_config`, `_get_random_seed_from_task`, `_require_task_access` 等两文件的全部符号。

- [ ] **Step 4: 更新 5 个消费者文件的 import（以 Step 1 确认的符号为准）**

根据 Step 1 & 2 的实际输出，对每个文件执行 import 替换。下面列出预期的替换内容（执行前请与实际行号核对）：

**classification_analysis.py：**
删除 `from .analysis_base import (...)` 和 `from .analysis_helpers import _get_random_seed_from_task`，
合并为一行：
```python
from .analysis_utils import (
    # [从 Step 2 中 classification_analysis 行的实际 symbol 列表填入]
    unpack_progress_config,  # 示例，以 grep 实际输出为准
    _get_random_seed_from_task,
)
```

**segmentation_analysis.py、survival_analysis.py、external_validation_analysis.py：**
同上，各自替换为 `from .analysis_utils import (...)` 单行。

**results.py：**
仅将 `from .analysis_helpers import (...)` 改为 `from .analysis_utils import (...)`；
`from .analysis_state import ...` 和 `from .analysis_metrics import ...` 保持不变。

**执行后验证：**
```bash
grep -rn "from .analysis_base\|from .analysis_helpers" server/gateway/routes/
```
Expected: 0 行（全部已替换）。

- [ ] **Step 5: 删除旧文件**

```bash
rm server/gateway/routes/analysis_base.py \
   server/gateway/routes/analysis_helpers.py
```

- [ ] **Step 6: import 健康检查**

```bash
python -c "from gateway.main import app; print('OK')"
```

- [ ] **Step 7: 运行后端测试**

```bash
python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
```
Expected: 116 tests passed.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(backend): merge analysis_base + analysis_helpers into analysis_utils"
```

---

## Task 4: 建立 gateway 层统一权限辅助 `access_control.py` [Backend — 中风险]

**背景:** `check_data_ownership` + `HTTPException(403)` 的组合在 8 个路由文件中各自裸调，每处都重复同样的 2 行模式。提取为 `access_control.py`，使路由函数只表达意图（`assert_owner(...)`），不重复模式。

**文件:**
- Create: `server/gateway/routes/access_control.py`
- Modify: `chat.py`, `training.py`, `models.py`, `queue.py`, `results.py`, `ai_tasks.py`, `storage.py`（各替换内联 403 模式）

- [ ] **Step 1: 精确审计各文件的内联 403 模式**

```bash
grep -n "check_data_ownership\|HTTPException(status_code=403" \
  server/gateway/routes/chat.py \
  server/gateway/routes/training.py \
  server/gateway/routes/models.py \
  server/gateway/routes/queue.py \
  server/gateway/routes/results.py \
  server/gateway/routes/ai_tasks.py \
  server/gateway/routes/storage.py
```
记录每处的确切判断条件（`str(task.user_id)`、`str(model.user_id)` 等）。

- [ ] **Step 2: 创建 `server/gateway/routes/access_control.py`**

```python
"""
access_control.py
=================
Gateway-layer ownership and role assertion helpers.

These thin wrappers eliminate the repeated
    if not check_data_ownership(owner_id, user):
        raise HTTPException(status_code=403, detail="...")
boilerplate in route handlers. Business logic stays in route files;
only the enforcement pattern is centralized here.
"""

from fastapi import HTTPException
from backend.auth import User
from backend.auth.dependencies import check_data_ownership


def assert_owner(
    resource_owner_id: str,
    user: User,
    detail: str = "You don't have permission to access this resource",
) -> None:
    """Raise HTTP 403 if user is not the resource owner (admins bypass this check)."""
    if not check_data_ownership(resource_owner_id, user):
        raise HTTPException(status_code=403, detail=detail)


def assert_admin(user: User, detail: str = "Admin access required") -> None:
    """Raise HTTP 403 if user is not an admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail=detail)
```

- [ ] **Step 3: 逐文件替换内联 403 模式**

对 Step 1 找到的每处，将：
```python
if not check_data_ownership(str(task.user_id), user):
    raise HTTPException(status_code=403, detail="...")
```
替换为：
```python
from .access_control import assert_owner  # 在文件顶部 import 区统一写
assert_owner(str(task.user_id), user)
```

**注意：** 只替换"资源所有权"检查。如有不同逻辑的 403（如维护模式、管理员专属接口），保持原样或使用 `assert_admin()`。不改变任何业务逻辑，仅替换模式。

- [ ] **Step 4: import 健康检查**

```bash
python -c "from gateway.main import app; print('OK')"
```

- [ ] **Step 5: 运行后端测试**

```bash
python -m pytest server/tests/ -v -k "not pretrained" --tb=short -q
```
Expected: 116 tests passed.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(backend): centralize 403 ownership checks in gateway/routes/access_control.py"
```

---

## Task 5: 修复前端 api/index.ts barrel export [Frontend — 中风险]

**背景:** `api/index.ts` 是迁移时遗留的"兼容 shim"（注释原文"so that existing imports continue to work"），对外 `export *` 全部 17 个 API 模块。每个消费者组件都与整个 API 表面耦合。目标：将每个消费者改为直接 import 对应的 API 子模块，最终 `index.ts` 只保留确实需要跨模块共用的 `client` 工具。

**文件:**
- Modify: `src/renderer/src/api/index.ts`
- Modify: 所有从 `'../api'` 或 `'../../api'` 或 `'../../../api'` 导入的文件（约 30 个）

- [ ] **Step 1: 确认 baseline 测试全绿**

```bash
npm run test:run
```

- [ ] **Step 2: 生成完整消费者清单**

```bash
grep -rn "from '.*\/api'" src/renderer/src \
  --include="*.tsx" --include="*.ts" \
  | grep -v "\/api\/" \
  | sort
```

- [ ] **Step 3: 运行脚本确认每个消费者文件使用了哪些 barrel symbol**

```bash
# 列出所有 barrel 消费者及其 import 行
grep -rn "from '.*\/api'" src/renderer/src \
  --include="*.tsx" --include="*.ts" \
  | grep -v "\/api\/" \
  | sort
```

对每个文件，读取该文件的完整 import 行，结合下表确定对应子模块：

| Symbol | 目标子模块 |
|---|---|
| `HeatmapData`, `AvailableHeatmap`, `PatchCAMData`, `getPatchImageUrl`, `getPatchFileImageUrl`, `buildSearchParams`, `withAuthTokenQuery` | `./api/heatmap` |
| `DatasetSummary`, `WSIStorageInfo`, `fetchDatasets`, `fetchWSIList`, `ExportLabelsOptions` | `./api/wsi` |
| `getAuthToken`, `requestAccess`, `changePassword` | `./api/auth` |
| `getClientIP`, `ApiError`, `apiFetch`, `buildAuthRequestInit`, `downloadApiFile`, `downloadBlobFile` | `./api/client` |
| `SEGMENTATION_MASK_COLORS` | `./api/annotation` |
| `getGlobalSettings`, `updateGlobalSettings` | `./api/settings` |
| `QueueStatus`, `getQueueStatus`, `updateQueueConfig`, `getQueueConfig` | `./api/queue` |
| `OrphanedRecordsInfo`, `OrphanedRecordsCleanupResult`, `ExternalDatasetInfo`, `ExternalFileInfo` | `./api/storage` |
| `DatasetGrant` | `./api/grants` |
| `UserListItem` | `./api/users` |
| `TrainedModel`, `downloadTrainedModelExport` | `./api/training` |
| `ValidationDataset` | `./api/results` |

- [ ] **Step 4: 逐文件更新 import（按 Step 2 / 3 的实际输出操作）**

**已知消费者完整清单及其替换方式：**

```
lib/useRealtimeASR.ts
  from '../api' → from '../api/auth'
  symbol: getAuthToken

lib/useDataSelection.ts
  from '../api' → from '../api/wsi'
  symbols: fetchDatasets, fetchWSIList, DatasetSummary

lib/externalValidationUtils.ts
  from '../api' → from '../api/training' + '../api/results'
  symbols: TrainedModel (training), ValidationDataset (results)

components/RegisterRequestModal.tsx
  from '../api' → from '../api/auth' + '../api/client'
  symbols: requestAccess (auth), ApiError (client)

components/DisclaimerModal.tsx
  from '../api' → from '../api/client'
  symbol: getClientIP

components/ChangePasswordModal.tsx
  from '../api' → from '../api/auth' + '../api/client'
  symbols: changePassword (auth), ApiError (client)

components/WSIViewer.tsx
  from '../api' → from '../api/heatmap' + '../api/client'
  symbols: HeatmapData, buildSearchParams, getPatchFileImageUrl (heatmap),
           buildAuthRequestInit, withAuthTokenQuery (client)

components/results/AnalysisDetails.tsx
  from '../../api' → from '../../api/client' + '../../api/training'
  symbols: downloadApiFile, downloadTrainedModelExport, withAuthTokenQuery (client)

components/wsiViewer/PatchOverlayStack.tsx
  from '../../api' → from '../../api/heatmap'
  symbol: getPatchFileImageUrl

components/wsiViewer/AttentionClassSelector.tsx
  from '../../api' → from '../../api/heatmap'
  symbol: HeatmapData

components/wsiViewer/TaskSelectorCard.tsx
  from '../../api' → from '../../api/heatmap'
  symbols: AvailableHeatmap, HeatmapData, PatchCAMData

components/wsiViewer/utils.ts
  from '../../api' → from '../../api/heatmap' + '../../api/client'
  symbols: HeatmapPoint, getPatchImageUrl (heatmap),
           buildAuthRequestInit, downloadBlobFile (client)

components/wsiViewer/AttentionPatchesPanel.tsx
  from '../../api' → from '../../api/heatmap'
  symbols: HeatmapData, PatchCAMData, getPatchImageUrl

components/wsiViewer/DeleteResultsModal.tsx
  from '../../api' → from '../../api/heatmap'
  symbol: AvailableHeatmap

components/wsiViewer/ViewerOverlayControls.tsx
  from '../../api' → from '../../api/annotation'
  symbol: SEGMENTATION_MASK_COLORS

components/list/ExportLabelsModal.tsx
  from '../../api' → from '../../api/wsi'
  symbols: DatasetSummary, ExportLabelsOptions

components/list/DeleteModals.tsx
  from '../../api' → from '../../api/wsi'
  symbol: WSIStorageInfo

components/settings/StorageTab.tsx
  from '../../api' → from '../../api/storage'
  symbols: (run grep on file to confirm full list)

components/settings/GeneralTab.tsx
  from '../../api' → from '../../api/settings' + '../../api/client'
  symbols: getGlobalSettings, updateGlobalSettings (settings),
           buildAuthRequestInit (client)

components/settings/FeedbackTab.tsx
  from '../../api' → from '../../api/feedback'
  symbols: (run grep on file to confirm full list)

components/settings/TasksTab.tsx
  from '../../api' → from '../../api/queue'
  symbols: QueueStatus, getQueueStatus, updateQueueConfig, getQueueConfig

components/settings/DatasetPermissionModal.tsx
  from '../../api' → from '../../api/grants' + '../../api/users'
  symbols: DatasetGrant (grants), UserListItem (users) + others (grep to confirm)

components/settings/UsersTab.tsx
  from '../../api' → from '../../api/users'
  symbols: (grep to confirm full list)

components/settings/PermissionModal.tsx
  from '../../api' → from '../../api/users' + '../../api/grants'
  symbols: UserListItem (users), DatasetGrant (grants)

components/settings/storage/ExternalDatasetsTable.tsx
  from '../../../api' → from '../../../api/storage'
  symbol: ExternalDatasetInfo

components/settings/storage/OrphanedRecordsCard.tsx
  from '../../../api' → from '../../../api/storage'
  symbols: OrphanedRecordsInfo, OrphanedRecordsCleanupResult

components/settings/storage/DatasetSelection.tsx
  from '../../../api' → from '../../../api/wsi'
  symbol: DatasetSummary

components/settings/storage/UnavailableFilesList.tsx
  from '../../../api' → from '../../../api/storage'
  symbol: ExternalFileInfo
```

每处替换后立即保存，不要批量操作。注意：
- `type`-only 的 symbol 加 `import type` 前缀
- 同一文件若需多个子模块则写多行 import
- 路径深度（`../`、`../../`、`../../../`）按原文件相对位置保持正确

- [ ] **Step 5: 精简 `api/index.ts`**

更新后，index.ts 仅保留 `client` 的 re-export（因为 `ApiError`、`apiFetch` 等被非常多地方使用，保留兼容性）：

```typescript
// api/index.ts
//
// 遗留兼容层：仅保留 client 工具函数的 re-export。
// 其余模块请直接从各自子模块导入，例如：
//   import { listWSIs } from './api/wsi'
//   import type { HeatmapData } from './api/heatmap'
//
export * from './client'
export * from './crypto'
```

- [ ] **Step 6: 运行测试**

```bash
npm run test:run
```
Expected: 全部通过。

- [ ] **Step 7: TypeScript 编译检查**

```bash
npm run build 2>&1 | grep -E "error TS|Error" | head -20
```
Expected: 0 TypeScript 错误。

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(frontend): replace api barrel with direct module imports, keep client shim"
```

---

## Task 6: 明确 constants/training.ts 与 trainingOptionsBootstrap.ts 的关系 [Frontend — 低风险]

**背景:** `training.ts` 定义静态编译期常量，`trainingOptionsBootstrap.ts` 在运行时动态 fetch 并覆盖。两文件命名和职责不够明确，读者容易混淆"哪个是 source of truth"。

**文件:**
- Modify: `src/renderer/src/constants/training.ts`
- Modify: `src/renderer/src/constants/trainingOptionsBootstrap.ts`

- [ ] **Step 1: 读取两文件，确认覆盖机制**

```bash
cat src/renderer/src/constants/training.ts | head -30
cat src/renderer/src/constants/trainingOptionsBootstrap.ts | head -30
```

- [ ] **Step 2: 在 `training.ts` 顶部加注释**

```typescript
/**
 * 静态编译期兜底值 — 仅用于 trainingOptionsBootstrap 尚未完成加载时的初始渲染。
 * 运行时真实值来自 GET /training/options，由 trainingOptionsBootstrap.ts 覆盖。
 * 不要将此文件视为权威数据源。
 */
```

- [ ] **Step 3: 在 `trainingOptionsBootstrap.ts` 顶部加注释**

```typescript
/**
 * 运行时训练选项初始化 — 应用启动后异步 fetch GET /training/options，
 * 并覆盖 constants/training.ts 中的静态兜底值。
 * 这是运行时训练选项的唯一权威来源。
 */
```

- [ ] **Step 4: 运行测试确认无副作用**

```bash
npm run test:run
```

- [ ] **Step 5: Commit**

```bash
git add src/renderer/src/constants/
git commit -m "docs(frontend): clarify training constants static fallback vs runtime bootstrap roles"
```

---

## 最终验证

所有 Task 完成后执行完整验证：

- [ ] **后端全量测试**

```bash
cd pathlab/pathlab-client
python -m pytest server/tests/ -v -k "not pretrained" --tb=short
```
Expected: **116 tests passed, 0 failed.**

- [ ] **前端全量测试**

```bash
npm run test:run
```
Expected: **30 test files, 0 failed.**

- [ ] **前端 TypeScript 编译**

```bash
npm run build 2>&1 | tail -5
```
Expected: `✓ built in ...` 无 error。

- [ ] **后端 import 健康检查**

```bash
python -c "
from gateway.main import app
from backend.common.chat_context_builder import build_chat_context_for_user
from gateway.routes.access_control import assert_owner, assert_admin
from gateway.routes.analysis_utils import unpack_progress_config
print('All imports OK')
"
```
Expected: `All imports OK`

- [ ] **最终 commit 总结**

```bash
git log --oneline -7
```
Expected: 可看到 Task 1~6 各自的 commit，每步独立可回滚。
