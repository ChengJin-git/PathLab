# PathLab Client 单元测试

> 适用版本：`PathLab v1.0.5`

本目录包含 PathLab 前端的单元测试套件，覆盖 API 客户端、工具函数、Context、页面和组件等主要业务模块。`2026-06-23` 加入的 AutoResearch（实现 codename：AutoResearch）前端也通过本测试树覆盖。

当前测试清单以 `test/**/*.test.{ts,tsx}` 为准；README 只记录稳定的目录分层和代表性测试对象，不把所有测试文件数量写死。

## 测试技术栈

| 工具 | 版本 | 用途 |
|------|------|------|
| [Vitest](https://vitest.dev/) | ^2.1.9 | 测试运行器与断言库 |
| [@testing-library/react](https://testing-library.com/docs/react-testing-library/intro/) | ^16 | React Context / Hook 测试 |
| [@testing-library/jest-dom](https://testing-library.com/docs/ecosystem-jest-dom) | — | DOM 扩展断言 |
| jsdom | ^24.1.3 | 浏览器环境模拟 |

## 运行测试

```bash
# 交互式监听模式
npm test

# 单次全量运行（CI）
npm run test:run

# 生成覆盖率报告
npm run test:coverage
```

覆盖率报告输出到 `coverage/` 目录（lcov + 终端文字摘要）。

## 目录结构

```text
test/
├── setup.ts              # 全局测试初始化
├── helpers/              # 测试工具函数
│   └── apiHelpers.ts     # ok() / errResp() / noContent() / blobResp() / createSSEStream()
└── unit/
    ├── api/              # API 客户端层测试
    │   ├── client.test.ts
    │   ├── crypto.test.ts
    │   ├── auth.test.ts
    │   ├── wsi.test.ts
    │   ├── training.test.ts
    │   ├── results.test.ts
    │   ├── stats.test.ts
    │   ├── chat.test.ts
    │   ├── heatmap.test.ts
    │   ├── users.test.ts
    │   ├── analysis.test.ts
    │   ├── annotation.test.ts
    │   ├── batchInference.test.ts
    │   ├── export.test.ts
    │   ├── feedback.test.ts
    │   ├── grants.test.ts
    │   ├── autoresearch.test.ts
    │   ├── queue.test.ts
    │   ├── settings.test.ts
    │   ├── storage.test.ts
    │   └── trainingOptions.test.ts
    ├── lib/              # 纯工具函数 / Hook 测试
    │   └── *.test.ts(x)
    ├── contexts/         # React Context 测试
    │   └── AuthContext.test.tsx
    ├── constants/        # 常量测试
    ├── pages/            # 页面级测试
    └── components/       # 组件测试
        └── **/*.test.tsx
```

AutoResearch 前端测试分布在 `unit/api/autoresearch.test.ts`、`unit/pages/AutoResearch*.test.tsx`、`unit/components/autoresearch/**/*.test.tsx` 与 `unit/lib/autoresearch*.test.ts(x)`。后端 pytest 套件位于 `server/tests/`，覆盖 Gateway 路由、权限边界、任务队列、存储、分析、AI 结果、AutoResearch 路由/进程注册与 GPU/模型 smoke；AutoResearch package 自身测试位于 `server/backend/autoresearch/tests/`，详见 `server/README.md`。

---

## helpers/apiHelpers.ts — 测试工具函数

**对应源文件**：无（纯测试基础设施）

提供 5 个工厂函数，用于快速构造 `Response` mock 对象，消除各测试文件中的重复样板代码：

- `ok(data, status?)` — 成功响应（默认 200，Content-Type: application/json）
- `errResp(data, status)` — 错误响应（ok=false）
- `noContent()` — 204 No Content
- `blobResp(content, type?)` — 二进制 / 文件下载响应
- `createSSEStream(lines)` — 构造 SSE 流用于流式 AI 对话测试

API 测试文件通过 `import { ok, errResp } from '../../helpers/apiHelpers'` 等方式复用这些工具，避免在各测试中重复手写 Response mock。

---

## setup.ts — 全局测试初始化

**对应源文件**：无（纯测试基础设施）

在所有测试文件执行前运行，负责：

- 将全局 `fetch` 替换为 `vi.fn()` mock，所有网络请求均通过 `mockFetch.mockResolvedValueOnce(...)` 手动控制
- 每个测试前调用 `mockFetch.mockReset()` 清除上次调用记录
- 每个测试前清空 `localStorage`，保证 token 不跨测试污染

---

## unit/lib/cache.test.ts

**对应源文件**：`src/renderer/src/lib/cache.ts`
PathLab 的 API 层大量使用三种缓存原语减少重复请求，本文件对这三种原语进行全面测试。

### 测试对象与覆盖点

**`createCache`**（单值缓存，带 TTL）

- 首次调用触发 fetcher，后续调用在 TTL 内直接返回缓存值，不再发起请求
- TTL 到期后重新发起请求（使用 `vi.useFakeTimers` 模拟时间推进）
- 并发请求去重：多个同时发起的 `cache.get()` 只调用一次 fetcher，共享同一个 Promise（"in-flight deduplication"）
- `forceRefresh=true` 绕过缓存强制重新获取
- `cache.invalidate()` 手动清除缓存后下次重新获取
- `hasValidData()` 在获取前返回 `false`，获取后返回 `true`，invalidate 后重置为 `false`
- fetcher 抛错后缓存不写入，允许下次重试

**`createKeyedCache`**（按 key 分组的多值缓存）

- 不同 key 的缓存完全独立
- 同 key 在 TTL 内命中缓存
- `cache.invalidate(key)` 只清除指定 key，不影响其他 key
- `cache.invalidateAll()` 清除全部 key
- 同 key 并发请求同样去重

**`createPersistentCache`**（基于 localStorage 的持久化缓存）

- 数据写入 localStorage，含 TTL 时间戳
- 下次创建同名缓存实例时直接从 localStorage 恢复，不重新 fetch
- TTL 过期后 localStorage 中的数据作废，重新 fetch
- `cache.set(data)` 手动写入缓存
- `cache.invalidate()` 清除 localStorage 中的缓存键

### 测试方式

纯函数，无需 mock。并发去重测试：先创建 unresolved Promise，同时发起两次 `cache.get()`，然后 resolve Promise，验证 fetcher 只被调用一次。

---

## unit/lib/avatarUrl.test.ts

**对应源文件**：`src/renderer/src/lib/avatarUrl.ts`
覆盖头像 URL 解析辅助函数：

- 空值返回 `null`
- 已经是绝对 URL 的头像地址保持不变
- 以 `/avatars/...` 开头的根路径会按 `API_BASE` 自动补齐为完整后端地址

---

## unit/lib/utils.test.ts

**对应源文件**：`src/renderer/src/lib/utils.ts`
### 测试对象与覆盖点

**`cn()`**（Tailwind 类名合并）

- 多个类名拼接
- Tailwind 冲突类合并（`p-2 p-4` → `p-4`，依赖 tailwind-merge）
- 条件类（`false && 'hidden'` 自动忽略）
- `undefined`、`null` 安全过滤

**`formatBytes()`**（字节数格式化）

- `0`、`null`、`undefined` 均返回 `"0 B"`
- B / KB / MB / GB / TB 各档位转换（基准 1024）
- 保留两位小数

**`formatFileSize()`**

- 与 `formatBytes` 行为一致，作为别名测试

### 测试方式

无依赖，直接 import 调用，无需任何 mock。

---

## unit/lib/chatMessageParser.test.ts

**对应源文件**：`src/renderer/src/lib/chatMessageParser.ts`
AI 对话消息中嵌入了多种 `[TAG]...[/TAG]` 格式的结构化控制块，这些块只供前端解析，发送给 AI 时需要清理或脱敏。

### 测试对象与覆盖点

**`sanitizeConfigBlocksForAI()`**（发送前清理消息内容）

- 完整移除 `[CITATION_CONTEXTS]`、`[OPTIONS]`、`[MODEL_LIST]`、`[PATCH_INFERENCE]` 块
- `[TASK_CONFIG]` 块：保留块本身，但删除 JSON 中的 `submitted_task_id` 字段（避免泄露内部 ID）
- `[ANALYSIS_CONFIG]` 块：删除 `submitted_analysis_id` 和 `external_validation_task_id`
- 多块共存时全部正确处理
- 无匹配块时原样返回

**`isPdfContextMessage()`**（检测 PDF 上下文注入消息）

- 消息含 `[CITATION_CONTEXTS]` 块时返回 `true`
- 普通消息返回 `false`
- 空字符串返回 `false`

### 测试方式

纯函数，无 mock，直接用字符串输入验证输出。

---

## unit/api/crypto.test.ts

**对应源文件**：`src/renderer/src/api/crypto.ts`
PathLab 使用客户端 SHA-256 对密码加盐后再发送，避免明文传输。

### 测试对象与覆盖点

**`APP_SALT`**

- 是非空字符串
- 与后端约定值 `'PathLab2024SecureSalt'` 完全一致

**`sha256()` — Web Crypto API 路径**（正常运行时）

- 返回 64 字符小写十六进制字符串
- `'hello'` 的标准 SHA-256 值正确
- 不同输入产生不同哈希
- 相同输入结果稳定一致
- 空字符串返回标准空串哈希
- Unicode 输入（中文）可正常处理

**`sha256()` — 纯 JS Fallback（`crypto === undefined` 时）**

- 用 `Object.defineProperty` 将 `globalThis.crypto` 置为 `undefined` 模拟非安全上下文（HTTP 非 localhost）
- 返回 64 字符十六进制字符串，格式正确
- 每次 `afterEach` 恢复原始 `crypto`

**`sha256()` — `subtle.digest` 抛错时的 Fallback**

- 用 `vi.stubGlobal('crypto', { subtle: { digest: vi.fn().mockRejectedValue(...) } })` 模拟 SubtleCrypto 不可用
- 确认降级到纯 JS 实现，输出仍为 64 字符十六进制字符串

---

## unit/api/client.test.ts

**对应源文件**：`src/renderer/src/api/client.ts`
整个 API 层的基础设施，本文件测试覆盖最广。

### 测试对象与覆盖点

**`ApiError` 类**

- 构造时正确记录 `message`、`status`、`code`、`details`，`name` 固定为 `'ApiError'`
- `is(code)` 精确匹配错误码
- `isNotFound()`：404 状态或 `NOT_FOUND` 码均返回 `true`
- `isAuthError()`：401 / 403 返回 `true`
- `isValidationError()`：400 / 422 返回 `true`
- `isServerError()`：500+ 返回 `true`，404 返回 `false`
- `isNetworkError()`：仅 `NETWORK_ERROR` 码返回 `true`
- 默认 code 为 `'API_ERROR'`

**`parseErrorResponse()`**（解析各类错误响应体）

- JSON 响应：取 `detail` / `message` / `error` 字段，都没有则用 `statusText`
- 纯文本响应：直接用文本内容
- HTML 响应（如 Nginx 502 错误页）：用 `statusText`，不暴露 HTML 原文

**`getErrorCodeFromStatus()`**

- 404 → `NOT_FOUND`，401/403 → `AUTH_ERROR`，400/422 → `VALIDATION_ERROR`，409 → `CONFLICT`，500+ → `SERVER_ERROR`，其余 → `UNKNOWN`

**Token 管理**（`getAuthToken` / `setAuthToken` / `clearAuthToken`）

- 写入 / 读取 / 清除 localStorage，清除后返回 `null`

**`buildSearchParams` / `appendSearchParams`**

- 单值、数组值、`null`/`undefined` 过滤
- 数组参数生成多个同名查询参数

**`buildAuthHeaders`**

- 无 token 时不注入 Authorization
- 有 token 时注入 `Bearer <token>`
- `skipAuth=true` 时跳过注入
- 传入自定义 header 时正确合并

**`buildAuthRequestInit`**

- 合并传入的 `RequestInit` 并注入认证 header

**`withAuthTokenQuery`**

- 将 token 追加为 URL 查询参数（用于不支持 header 的场景）

**`apiFetch`**

- 成功响应（2xx）：返回解析后的 JSON 数据
- 204 No Content：返回 `undefined`
- 4xx 响应：抛出 `ApiError`，status 正确
- 5xx 响应：抛出 `ApiError`
- `TypeError`（网络不通）：抛出 `ApiError(NETWORK_ERROR, 0)`
- 401 且有 token：派发 `SESSION_EXPIRED_EVENT` 自定义事件
- 401 且无 token：不派发事件（正常未登录状态）
- `context` 参数：错误消息前缀追加上下文描述

**`apiFetchBlob`**

- 成功：返回 Blob 对象
- 失败：抛出带 status 的 `ApiError`

**`downloadBlobFile`**

- 创建隐藏 `<a>` 元素并模拟点击触发下载，之后从 DOM 移除

### 测试方式

通过 `vi.mocked(fetch).mockResolvedValueOnce(...)` 精确控制每次请求的响应。`SESSION_EXPIRED_EVENT` 测试通过 `window.addEventListener` 捕获事件验证。

---

## unit/api/auth.test.ts

**对应源文件**：`src/renderer/src/api/auth.ts`
### 测试对象与覆盖点

**`loginWithCredentials()`**

- 发送的 `hashed_password` 是 64 字符哈希（SHA-256(password + salt + timestamp)），绝不是明文
- `timestamp` 字段存在且为正数
- 成功后将 `access_token` 存入 localStorage
- 成功后调用 `invalidateRecentActivityCache()`（防止旧用户数据缓存残留）
- 可选 `turnstile_token` 存在时包含在请求体中
- 失败时抛出 `ApiError`（status 正确）

**`logout()`**

- 调用 `POST /auth/jwt/logout`
- 成功后清除 localStorage 中的 token
- 网络失败时 token 依然清除（`finally` 块保证）
- 调用 `invalidateRecentActivityCache()`

**`getCurrentUser()`**

- 无 token 时直接返回 `{ is_logged_in: false }`，不发网络请求
- 有 token 时请求 `/auth/me`，返回用户信息

**`updateCurrentUser()`**

- 发送 `PATCH` 请求，只包含传入的字段
- 返回更新后的用户对象

**`registerUser()`**

- 发送 `POST` 到已禁用的 `/auth/register`；测试保留该客户端函数的请求封装行为，管理员创建用户不再使用它

**`uploadAvatar()` / `deleteAvatar()`**

- 上传：通过 `FormData` 发送图片文件
- 删除：发送 `DELETE` 请求

---

## unit/api/wsi.test.ts

**对应源文件**：`src/renderer/src/api/wsi.ts`
WSI（全玻片图像）是系统核心数据对象，本文件测试完整的数据管理 CRUD。

### 测试对象与覆盖点

**`checkDuplicateFilenames()`**

- 空列表直接返回 `{ duplicates: [], new: [] }`，不发请求
- 非空列表发送 `POST` 到 `/wsi/check-duplicates`

**`fetchWSIList()`**

- 默认 `page=1&page_size=20`（分页获取）
- 按 `dataset_id` 过滤
- 带 TTL 的缓存，`invalidateWSIListCache()` 清除后重新请求

**`fetchAllWSIList()` / `fetchAllDatasets()`**

- 使用有界分页逐页获取完整列表，不发送 `page_size=0`

**`fetchWSIIds()`**

- 返回 WSI ID 字符串列表

**`fetchDatasets()` / `fetchDatasetSummary()`**

- 数据集列表与统计摘要的获取与缓存

**`renameDataset()` / `updateDatasetType()` / `updateDatasetDataLevel()`**

- 各类 PATCH 操作，验证请求体字段

**`fetchWSIDetail()`**

- 带缓存的详情获取，`forceRefresh` 绕过缓存

**`uploadWSIByPath()`**

- 通过本地路径上传 WSI，验证请求体包含路径和元数据字段

**`deleteWSI()`**

- `DELETE /wsi/{id}`
- 删除后使 WSI 列表缓存、热图缓存失效

**`updateWSIMetadata()`**

- PATCH 更新任意字段组合（label、case_id、survival 字段等）
- 成功后清除相关缓存

**`uploadWSIByCSV()`**

- 通过 FormData 上传 CSV 批量导入

**`downloadCSVTemplate()`**

- `task_type=classification`（默认）和 `task_type=survival` 两种模板下载
- 触发浏览器文件下载（Blob → `<a>` 点击）

---

## unit/api/training.test.ts

**对应源文件**：`src/renderer/src/api/training.ts`
### 测试对象与覆盖点

**`getTrainingTasks()`**

- 获取训练任务列表，带 TTL 缓存
- `invalidateTrainingTasksCache()` 清除后重新请求

**`getTrainingTask()`**

- 按 ID 获取单个任务详情

**`createTrainingTask()`**

- POST 请求，body 包含完整 `TrainingTaskConfig`（feature_extractor、aggregator、task_type 等）
- 创建后使列表缓存失效

**`deleteTrainingTask()`**

- DELETE 请求，删除后使缓存失效

**`updateTrainedModel()`**

- PATCH 更新模型元数据

**`getTrainedModels()` / `getTrainedModel()`**

- 模型列表与详情获取

**`deleteTrainedModel()`**

- DELETE 模型，清除关联缓存

**`fetchExtractors()`**

- 获取可用特征提取器列表（UNI、CONCH、SmartCyto 等）

---

## unit/api/results.test.ts

**对应源文件**：`src/renderer/src/api/results.ts`
### 测试对象与覆盖点

**`fetchResults()`**

- 获取所有推理结果，带 TTL 缓存
- 按 `dataset_id` 过滤

**`fetchAllResults()`**

- 不分页获取全量结果列表

**`deleteWSIResults()`**

- 删除指定 WSI 的所有结果
- 删除后同时使结果缓存和热图缓存失效（调用 `invalidateHeatmapAvailabilityCache`）

**`invalidateResultsCache()`**

- 手动清除结果缓存，触发重新请求

---

## unit/api/stats.test.ts

**对应源文件**：`src/renderer/src/api/stats.ts`
### 测试对象与覆盖点

**`fetchStats()`**

- 获取系统存储统计，带缓存
- `hasValidStatsCache()` 反映缓存状态
- `invalidateStatsCache()` 清除后重新请求

**`fetchRecentActivity()`**

- 获取近期活动记录，带缓存
- `hasValidRecentActivityCache()` / `invalidateRecentActivityCache()` 同上

**`fetchUserUsageStats()`**

- 获取按用户维度的存储使用统计

---

## unit/api/chat.test.ts

**对应源文件**：`src/renderer/src/api/chat.ts`
### 测试对象与覆盖点

**会话 CRUD**

- `createConversation()`：POST 创建会话，body 含标题
- `getConversations()`：GET 列表
- `getConversation()`：GET 单个会话（含历史消息）
- `deleteConversation()`：DELETE

**消息操作**

- `addMessage()`：POST 向会话追加消息（角色 + 内容）
- `updateMessage()`：PATCH 更新消息内容
- `deleteMessagesFrom()`：DELETE 从指定消息开始删除后续所有消息

**AI 对话流**

- `chatWithAI()`：发送 SSE 流式请求，验证 URL、请求体字段（model、messages、wsi_context 等）

**Patch 推理**

- `startChatPatchInference()`：启动 patch 级别推理任务
- `getChatPatchInferenceTask()`：轮询任务状态

---

## unit/api/heatmap.test.ts

**对应源文件**：`src/renderer/src/api/heatmap.ts`
### 测试对象与覆盖点

**`fetchAvailableHeatmaps()`**

- 获取指定 WSI 可用的热图列表，按 WSI ID 分 key 缓存
- 同 WSI 第二次调用命中缓存，不发请求
- 不同 WSI 各自独立缓存

**`invalidateHeatmapAvailabilityCache()`**

- 传入特定 WSI ID：只清除该 WSI 的缓存，不影响其他 WSI
- 不传参数：清除全部 WSI 的缓存

**`fetchHeatmapData()`**

- 获取热图张量数据（attention 权重矩阵）

**URL 构建函数**（纯函数，无网络请求）

- `getPatchImageUrl(wsiId, patchId)`
- `getThumbnailUrl(wsiId)`
- `getHeatmapThumbnailUrl(wsiId, taskId)`
- `getPatchCAMImageUrl(wsiId, taskId, patchId)`
- `getSegMaskImageUrl(wsiId, taskId)`
- `getRecommendationThumbnailUrl(wsiId, taskId, patchId)`

**`SEGMENTATION_MASK_COLORS`**

- 颜色数组非空，每个元素为合法 CSS 颜色字符串

---

## unit/api/users.test.ts

**对应源文件**：`src/renderer/src/api/users.ts`
管理员专用接口。

### 测试对象与覆盖点

**用户 CRUD**

- `listUsers()`：GET 用户列表
- `listUsersPaged()`：分页 / 搜索用户列表
- `getUserById()`：GET 单个用户
- `createUser()`：POST 创建用户（含 role、password 等字段）
- `updateUser()`：PATCH 更新用户信息
- `deleteUser()`：DELETE

**批量状态管理**

- `batchActivateUsers(userIds)` / `batchDeactivateUsers(userIds)`：批量激活 / 停用用户账号
- `batchDeleteUsers(userIds)`：批量删除用户

**协议与维护**

- `acceptAgreement(ip?)`：当前用户接受协议
- `revokeUserAgreement(userId)`：管理员撤销指定用户的协议接受状态
- `getMaintenanceMode()` / `setMaintenanceMode(enabled)`：读取 / 更新维护模式
- `getMaintenanceNotice()` / `setMaintenanceNotice(message)`：读取 / 更新维护公告
- `acknowledgeNotice()`：标记用户已读维护公告

**辅助**

- `getClientIP()`：获取客户端 IP（用于协议签署记录）

---

## unit/contexts/AuthContext.test.tsx

**对应源文件**：`src/renderer/src/contexts/AuthContext.tsx`
唯一的 React Context 测试，使用 `renderHook` + `act` + `waitFor` 测试认证状态机的完整生命周期。

### Mock 策略

| Mock 目标 | 原因 |
|-----------|------|
| `@renderer/api` | 隔离所有网络请求，精确控制各 API 的返回值 |
| `@renderer/contexts/ToastContext` | 捕获 `toast.warning()` 调用，验证 session 过期通知 |
| `react-i18next` | 避免 i18n 初始化依赖，`t(key)` 直接返回 key |

### 测试对象与覆盖点

**初始加载状态**

- 挂载瞬间 `isLoading=true`、`user=null`
- `getCurrentUser` 返回 `{ is_logged_in: true }` 时，`user` 被设置、`isLoggedIn=true`
- `getCurrentUser` 抛错时，`error` 被设置、`user` 保持 `null`

**`login()`**

- 成功：调用 `loginWithCredentials` → `refreshUser`，返回 `true`，`user` 更新
- 传递 `turnstileToken` 到底层 API
- `login_bad_credentials` 错误 → `error` = `'Invalid username or password'`
- `maintenance_mode` 错误 → `error` 含 `'maintenance'`
- `login_user_not_active` 错误 → `error` 含 `'deactivated'`
- `clearError()` 将 `error` 重置为 `null`

**`logout()`**

- 成功：派发 `BEFORE_LOGOUT_EVENT`（供其他模块清理状态），`user` 清为 `null`
- API 失败：`user` 依然清除，`clearAuthToken()` 被调用

**角色判断**

- `isAdmin=true` 仅当 `role === 'admin'`
- `isPathologist=true` 仅当 `role === 'pathologist'`
- `canUseGpu=true` 当 admin 或 pathologist；guest 为 `false`
- `canUseGpuForDataset(id)`：base GPU 权限满足时直接 `true`；guest 仅当该 dataset 在 `elevatedDatasetIds` 中

**`needsAgreement`**

- 未登录：`false`
- admin 角色：`false`（管理员免签）
- pathologist / guest 且 `agreement_accepted_at=null`：`true`
- 已有 `agreement_accepted_at`：`false`

**`acceptAgreement()`**

- 先调用 `getClientIP()` 获取 IP，再调用 `apiAcceptAgreement(ip)`
- IP 为 `null` 时传 `undefined`
- 成功后更新 `user`；失败后设置 `error` 并返回 `false`

**维护公告**

- 用户登录后自动调用 `getMaintenanceNotice()`
- 公告 `active=true` 时设置 `maintenanceNoticeMessage` 和 `needsMaintenanceAcknowledgment`
- 用户登出后两者均重置为 `null` / `false`

**`acknowledgeMaintenanceNotice()`**

- 调用 `acknowledgeNotice()` API，更新 `user`，`needsMaintenanceAcknowledgment` 置 `false`
- 用户更新触发 `checkMaintenanceNotice` 重新执行，此时 mock 返回 `active=false` 保证状态正确

**`SESSION_EXPIRED_EVENT`**

- 有用户会话时收到事件：调用 `toast.warning()`，`user` 清为 `null`
- 无用户（未登录）时收到事件：不触发 toast（避免误报）

**`refreshDatasetGrants()`**

- 成功：更新 `elevatedDatasetIds`
- 失败：重置为空数组

**Provider 边界检查**

- `useAuth()` 在 `AuthProvider` 外调用时抛出 `'useAuth must be used within an AuthProvider'`

---

## unit/api/analysis.test.ts

**对应源文件**：`src/renderer/src/api/analysis.ts`

覆盖外部验证与分析相关接口：

- `fetchDatasetsForValidation()`：获取可用于外部验证的数据集列表（含标签分布、可用提取器信息）
- `startExternalValidation()`：提交外部验证任务（含模型 ID、数据集 ID 等参数）
- `runTaskAnalysis()`：为指定任务触发完整分析流程
- `getTaskQuickAnalysis()`：获取任务快速分析摘要（含 `has_analysis`、`task_type`、指标数等）
- `getAnalysisStatus()`：轮询分析任务状态，覆盖 running / completed / failed 三态

---

## unit/api/annotation.test.ts

**对应源文件**：`src/renderer/src/api/annotation.ts`

覆盖分割标注的完整 CRUD、标签读取、协作标注全流程与审计：

- `saveAnnotation()` / `listAnnotations()` / `getAnnotation()` / `deleteAnnotation()`：标注草稿增删查
- `getDatasetLabels()` / `getWSILabels()`：数据集与 WSI 级别标签读取（原 ground-truth 接口已重命名）
- `getLabelThumbnailUrl()`：构建标签缩略图 URL（纯函数，无网络请求）
- `getDatasetAnnotationSummary()`：数据集标注摘要（label 分布、annotated_wsi 计数）
- `deleteDatasetAnnotationsByLabels()`：按 label 批量删除
- `deleteDatasetLabels()`：删除整个数据集的标签
- `extractRegions()`：触发 ROI 提取任务
- `getExtractProgressSSEUrl()`：获取 ROI 提取进度的 SSE 流地址（纯函数）
- **协作标注**：`getSharedAnnotation()` / `saveSharedAnnotation()` / `deleteSharedAnnotation()` / `finalizeSharedAnnotation()` / `bulkDeleteSharedRegionsByCreator()` / `getSharedAnnotationSSEUrl()`
- **协作者管理**：`listCollaborators()` / `addCollaborator()` / `removeCollaborator()`（含 URL 编码验证）
- **审计日志**：`listAnnotationAudit()`（含查询参数过滤）/ `exportAnnotationAuditUrl()`（纯函数）
- **WebSocket 协作**：`getPresenceWSUrl()`（未认证返回 null，已认证返回 ws:// 地址）

---

## unit/api/export.test.ts

**对应源文件**：`src/renderer/src/api/export.ts`

覆盖异步导出任务管理：

- `startAsyncExport()`：发起异步导出任务（支持 feedbacks 等类型，指定 `file_format`）
- `getExportTaskStatus()`：轮询导出任务状态（pending → running → completed）
- `downloadExportFile()`：下载已完成的导出文件（Blob 响应，触发浏览器下载）

---

## unit/api/feedback.test.ts

**对应源文件**：`src/renderer/src/api/feedback.ts`

覆盖 AI 对话消息反馈的完整功能：

- `submitMessageFeedback()` / `deleteMessageFeedback()`：用户提交 / 撤回对单条消息的反馈
- `getConversationFeedbacks()`：获取会话内的所有反馈记录
- `getAdminFeedbacks()`：管理员分页获取全量反馈（含筛选参数）
- `getFeedbackStats()`：获取反馈统计摘要（thumbs_up / thumbs_down 计数等）
- `exportFeedbacks()`：导出反馈数据（Blob 下载）
- `resetAllFeedbacks()`：管理员清空全部反馈记录

---

## unit/api/grants.test.ts

**对应源文件**：`src/renderer/src/api/grants.ts`

覆盖数据集临时提权管理：

- `getMyDatasetGrants()`：获取当前用户已获得临时提权的数据集 ID 列表
- `grantDatasetGrant()` / `revokeDatasetGrant()`：单条授权 / 撤销
- `getUserDatasetGrants()`：获取指定用户的所有权限记录
- `listDatasetGrants()`：管理员分页列出全量权限记录（含过期状态）
- `batchGrantDatasetGrants()` / `batchRevokeDatasetGrants()`：批量授权 / 批量撤销

---

## unit/api/queue.test.ts

**对应源文件**：`src/renderer/src/api/queue.ts`

覆盖 GPU 任务队列管理接口：

- `getQueueStatus()`：获取当前队列状态（running_count、pending_count、GPU 信息等）
- `getQueueConfig()` / `updateQueueConfig()`：读取 / 修改 `max_concurrent` 等队列配置
- `cancelQueueTask()`：取消指定排队任务，并验证 `invalidateTrainingTasksCache()` 被调用

---

## unit/api/settings.test.ts

**对应源文件**：`src/renderer/src/api/settings.ts`

覆盖系统设置接口：

- `getPublicSettings()`：获取公开设置（`turnstile_enabled`、`turnstile_site_key` 等，无需认证）
- `getGlobalSettings()`：管理员获取全部全局设置（API keys、vLLM、ASR 等配置项）
- `updateGlobalSettings()`：管理员 PATCH 更新全局设置，验证请求体字段

---

## unit/api/storage.test.ts

**对应源文件**：`src/renderer/src/api/storage.ts`

覆盖 `/storage` 全部接口，是测试用例数最多的单文件：

- **配置与空间**：`getStorageConfig()` / `updateStorageConfig()` / `getDiskSpace()` / `checkUploadSpace()`
- **统计**：`getStorageStats()` / `getWSIStorageInfo()` / `getTrainingTaskStorageInfo()`
- **孤立项**：`detectOrphanedFiles()` / `cleanupOrphanedFiles()` / `detectOrphanedRecords()` / `cleanupOrphanedRecords()`
- **迁移**：`startMigration()` / `getMigrationStatus()`
- **外部扫描**：`scanDirectory()` / `getExternalDatasets()` / `invalidateExternalDatasetsCache()` / `getExternalDatasetsCachedSync()`
- **后台任务**：`startBatchImportTask()` / `startDeleteExternalTask()` / `startBatchUpdateMetadataTask()` / `getStorageTaskStatus()` / `cancelStorageTask()`
- **派生数据**：`resetDerivedData()`

---

## unit/api/trainingOptions.test.ts

**对应源文件**：`src/renderer/src/api/trainingOptions.ts`

覆盖训练配置选项接口：

- `fetchTrainingOptions()`：从 `GET /training/options` 获取全部可选项（feature_extractors、aggregators、segmentation_architectures、segmentation_backbones、segmentation_losses、optimizers）
- 验证请求 URL 前缀正确指向 Gateway（`API_BASE`）
- 验证错误时抛出 `ApiError`

---

## unit/api/batchInference.test.ts

**对应源文件**：`src/renderer/src/api/batchInference.ts`

覆盖无标签数据集批量推理的完整接口：

- `fetchDatasetsForInference()`：获取可提交批量推理的无标签数据集列表
- `startBatchInference()`：提交批量推理任务（指定模型任务 ID 与目标数据集 ID）
- `listBatchInferenceTasks()`：列出当前用户的批量推理任务列表
- `getBatchInferenceResults(taskId)`：获取指定推理任务的逐 WSI 预测结果
- `getBatchInferenceSummary(taskId)`：获取推理汇总摘要（类别分布、处理 slide 数等）
- `exportBatchInferenceCsv(taskId)`：导出推理结果为 CSV 文件（Blob 响应，触发浏览器下载）

---

## unit/lib/datasetPagination.test.ts

**对应源文件**：`src/renderer/src/lib/datasetPagination.ts`
覆盖 `clampDatasetPage()` 的三条分支：请求出错时保持当前页不变、正在加载且无数据时保持不变、数据稳定时将页码夹紧到总页数上限。

---

## unit/lib/segmentationUploadUtils.test.ts

**对应源文件**：`src/renderer/src/lib/segmentationUploadUtils.ts`
覆盖分割标注上传的文件匹配工具函数：

- `getSegmentationStem(name)` — 剥离 `.json` 与其他扩展名后小写化，覆盖多种命名组合
- `mergeSegmentationJsonFiles(existing, files)` — 合并 JSON 文件映射，检测重复 stem；验证不修改原始 Map
- `summarizeSegmentationMatches(items, jsonMap)` — 计算已匹配、缺失 JSON、孤立 JSON、重复图像的 stem 集合；验证排序行为

---

## unit/lib/externalValidationUtils.test.ts

**对应源文件**：`src/renderer/src/lib/externalValidationUtils.ts`
覆盖外部验证的模型-数据集兼容性校验逻辑：

- `isSurvivalTask()` / `isSegmentationTask()` — 任务类型判断，含边界值（undefined、空串）
- `getDatasetCompatibilityError()` — 核心兼容性逻辑，覆盖：data_type 不匹配、task_type 不匹配、分类标签集不等、WSI 数据泄漏检测、survival 免标签检查、分割任务特有规则（文件级数据集、架构 / backbone 元数据校验、source/target 数据集不能相同）；WSI 特征缺失由 external validation 运行时按模型提取器自动生成，不再用缓存提取器维度做兼容性拦截
- `filterCompatibleDatasets()` / `isDatasetCompatible()` — 基于 `getDatasetCompatibilityError` 的过滤包装

---

## unit/lib/useAsyncAction.test.tsx

**对应源文件**：`src/renderer/src/lib/useAsyncAction.ts`
覆盖 `useAsyncAction` Hook 的核心语义：

- 初始状态 `isPending = false`
- 异步函数运行期间 `isPending = true`，完成后归 `false`
- `run()` 返回异步函数的解析值
- 函数抛错后 `isPending` 仍归 `false`，并调用 `onError` 回调
- 未提供 `onError` 时降级到 `console.error`
- 两个并发 `run()` 调用各自独立完成，引用计数在最后一个完成前保持 `isPending = true`

### 测试方式

使用 `renderHook` + `act` 驱动 React Hook，通过手动 resolve/reject Promise 精确控制异步时序。

---

## unit/lib/trainingSubmissionTracker.test.ts

**对应源文件**：`src/renderer/src/lib/trainingSubmissionTracker.ts`
覆盖基于 localStorage 的训练提交状态机：

- **状态转换**：`markTrainingSubmissionPending()` → `Created` → `Failed` → `Cancelled`，验证各转换保留 `createdAt`、携带可选 `taskName` / `error`
- **读取**：`getTrainingSubmissionRecord()` 对未知 task 返回 null，对超出 7 天保留期的记录返回 null
- **列表**：`listTrainingSubmissionRecords()` 支持按 state 过滤、按 `updatedAt` 降序排列
- **超时检测**：`isTrainingSubmissionPendingTimedOut()` 基于默认（30 分钟）与自定义超时阈值
- **清除**：`clearTrainingSubmissionRecord()` 只删除指定 task，不影响其他记录；对不存在的 task 不抛错
- 所有测试使用 `vi.useFakeTimers()` 精确控制时间推进

---

---

## unit/lib/listPageFileView.test.ts

**对应源文件**：`src/renderer/src/lib/utils/listPageFileView.ts`

覆盖 WSI 列表页文件视图区域的显示状态计算逻辑：

- `getListPageFileViewState()`：
  - 初始文件加载中：只展示加载态，不显示搜索操作栏与空态提示
  - 无文件且无搜索词：显示数据集空态
  - 搜索词有效但无匹配：显示"无匹配文件"提示
  - 有文件且无活跃搜索：正常显示文件表格
  - 有活跃搜索词（无论是否有结果）：显示搜索操作栏

---

## 测试设计原则

### 网络隔离

所有 API 测试均不发送真实 HTTP 请求。`test/setup.ts` 将全局 `fetch` 替换为 vi mock，每个测试用 `mockFetch.mockResolvedValueOnce(...)` 注入精确的响应。

### 缓存隔离

每个 API 测试文件的 `beforeEach` 调用对应模块的 `invalidateXxxCache()` 函数，确保上一个测试的缓存不影响下一个。

### 全局 stub 还原

涉及 `vi.stubGlobal('URL', ...)` 等全局替换的测试，使用 `vi.stubGlobal('URL', origURL)` 逐一还原，**不使用** `vi.unstubAllGlobals()` 或 `vi.restoreAllMocks()`，避免意外恢复 `fetch` mock。

### React Context 测试

`AuthContext.test.tsx` 使用 `renderHook(() => useAuth(), { wrapper: AuthProvider })` 挂载完整 Context，通过 `act()` 包裹所有触发状态变更的操作，通过 `waitFor()` 等待异步副作用完成。
