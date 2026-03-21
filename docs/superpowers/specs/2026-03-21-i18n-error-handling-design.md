# i18n for Hardcoded Error Handling Text

**Date:** 2026-03-21  
**Status:** Draft  
**Scope:** Frontend only (`pathlab/pathlab-client/src/renderer/src/`)

---

## Problem

The existing i18n system is comprehensive (en-US.json has 3 631 lines, zh-CN.json 3 626 lines), but a small set of user-visible strings bypass translation entirely. They are concentrated in four files:

| File | Hardcoded strings |
|---|---|
| `api/client.ts` | Network connection error message (1 string) |
| `contexts/backgroundTask/BackgroundTaskProvider.tsx` | Task item names, task titles, migration error fallback (5 strings) |
| `contexts/backgroundTask/useTaskActions.ts` | Error strings stored in `task.item.error` field (4 strings) |
| `contexts/backgroundTask/useTrainingSSE.ts` | `'Training:'` and `'Validation:'` prefix strings (2 strings) |

**livelogs exception:** `LogViewer.tsx` UI labels are already translated. The actual log content (`log.message`, `log.metadata.error`) comes from the Python backend and intentionally stays in English. No change is needed there.

---

## Decisions

| Question | Decision |
|---|---|
| Background task item names (e.g. "Training: …", "Analyzing: …") | **Translate** — consistent UX for all locales |
| `api/client.ts` (non-React module, cannot use hook) | **Import i18n singleton** (`i18n.t()`) directly |
| Scope | **Targeted fix only** — existing coverage is already very high; no full AST scan needed |
| Livelogs | **Unchanged** — already correctly handled |

---

## Architecture

### i18n key additions

Add to all three locale files (`en-US.json`, `zh-CN.json`, `zh-HK.json`).

#### `backgroundTask.taskTitles` — extend existing node

| Key | en-US value |
|---|---|
| `taskTitles.analyzing` | `"Analyzing: {{name}}"` |
| `taskTitles.training` | `"Training: {{name}}"` |
| `taskTitles.validation` | `"Validation: {{name}}"` |

> Note: `taskTitles.movingData` already exists as `"Moving data to {{path}}"` — used in `BackgroundTaskProvider` but currently bypassed with a template literal. Fix: call `t()`.

#### `backgroundTask.relocatingToPath` — new key

| Key | en-US value |
|---|---|
| `relocatingToPath` | `"Relocating to {{name}}"` |

> Note: `relocatingTo` (= `"Relocating to"`) already exists. Rather than concatenating, we add a proper interpolation key.

#### `backgroundTask.errors` — new sub-node

| Key | en-US value |
|---|---|
| `errors.migrationFailed` | `"Migration failed"` |
| `errors.notAuthenticated` | `"Not authenticated"` |
| `errors.extractionFailed` | `"Extraction failed"` |
| `errors.datasetPollingTimeout` | `"Could not find dataset after 5 minutes of polling"` |

#### Top-level `errors` node — new

| Key | en-US value |
|---|---|
| `errors.networkConnectionFailed` | `"Cannot connect to server. Please check your network connection and ensure the backend is running."` |

---

## File-level changes

### 1. `api/client.ts`

- Add `import i18n from '../i18n'` at the top.
- Replace the hardcoded `friendlyMsg` string (line ~336) with `i18n.t('errors.networkConnectionFailed')`.
- The i18n singleton follows the active locale automatically; no hook needed.

**Before:**
```ts
const friendlyMsg = 'Cannot connect to server. Please check your network connection and ensure the backend is running.'
```

**After:**
```ts
import i18n from '../i18n'
// ...
const friendlyMsg = i18n.t('errors.networkConnectionFailed')
```

---

### 2. `contexts/backgroundTask/useTrainingSSE.ts`

- Add `useTranslation` hook inside `useTrainingSSE`.
- Replace `itemNamePrefix` string assignment with translated versions.
- Replace the `name` field template literal with the pre-built translated string.

**Before:**
```ts
const itemNamePrefix = isExternalValidation ? 'Validation' : 'Training'
// ...
name: `${itemNamePrefix}: ${task.task_name}`,
```

**After:**
```ts
const { t } = useTranslation()
// ...
const itemName = isExternalValidation
  ? t('backgroundTask.taskTitles.validation', { name: task.task_name })
  : t('backgroundTask.taskTitles.training',   { name: task.task_name })
// ...
name: itemName,
```

---

### 3. `contexts/backgroundTask/BackgroundTaskProvider.tsx`

- Add `useTranslation` hook (currently not present in this file).
- Replace 5 hardcoded strings.

**Replacements:**

| Location | Before | After |
|---|---|---|
| External-validation item name (useMemo) | `` `Analyzing: ${task.title}` `` | `t('backgroundTask.taskTitles.analyzing', { name: task.title })` |
| Synthetic submission item name (useMemo) | `` `Training: ${record.taskName \|\| record.taskId}` `` | `t('backgroundTask.taskTitles.training', { name: record.taskName \|\| record.taskId })` |
| Restored migration task title | `` `Relocating to ${destName}` `` | `t('backgroundTask.relocatingToPath', { name: destName })` |
| Restored migration item name | `` `Moving data to ${status.destination}` `` | `t('backgroundTask.taskTitles.movingData', { path: status.destination })` |
| Restored migration error fallback | `'Migration failed'` | `t('backgroundTask.errors.migrationFailed')` |

---

### 4. `contexts/backgroundTask/useTaskActions.ts`

Already has `const { t } = useTranslation()`. Replace 4 error strings.

| Before | After |
|---|---|
| `'Migration failed'` (line ~334) | `t('backgroundTask.errors.migrationFailed')` |
| `'Could not find dataset after 5 minutes of polling'` (line ~644) | `t('backgroundTask.errors.datasetPollingTimeout')` |
| `'Not authenticated'` (line ~716) | `t('backgroundTask.errors.notAuthenticated')` |
| `'Extraction failed'` (line ~743) | `t('backgroundTask.errors.extractionFailed')` |

---

## Locale translations

### zh-CN (Simplified Chinese)

| Key path | Value |
|---|---|
| `backgroundTask.taskTitles.analyzing` | `"分析中：{{name}}"` |
| `backgroundTask.taskTitles.training` | `"训练中：{{name}}"` |
| `backgroundTask.taskTitles.validation` | `"验证中：{{name}}"` |
| `backgroundTask.relocatingToPath` | `"迁移至 {{name}}"` |
| `backgroundTask.errors.migrationFailed` | `"迁移失败"` |
| `backgroundTask.errors.notAuthenticated` | `"未认证"` |
| `backgroundTask.errors.extractionFailed` | `"提取失败"` |
| `backgroundTask.errors.datasetPollingTimeout` | `"等待 5 分钟后仍未找到数据集"` |
| `errors.networkConnectionFailed` | `"无法连接到服务器，请检查网络连接并确认后端服务正在运行。"` |

### zh-HK (Traditional Chinese)

| Key path | Value |
|---|---|
| `backgroundTask.taskTitles.analyzing` | `"分析中：{{name}}"` |
| `backgroundTask.taskTitles.training` | `"訓練中：{{name}}"` |
| `backgroundTask.taskTitles.validation` | `"驗證中：{{name}}"` |
| `backgroundTask.relocatingToPath` | `"遷移至 {{name}}"` |
| `backgroundTask.errors.migrationFailed` | `"遷移失敗"` |
| `backgroundTask.errors.notAuthenticated` | `"未認證"` |
| `backgroundTask.errors.extractionFailed` | `"提取失敗"` |
| `backgroundTask.errors.datasetPollingTimeout` | `"等待 5 分鐘後仍未找到資料集"` |
| `errors.networkConnectionFailed` | `"無法連接到伺服器，請檢查網絡連接並確認後端服務正在運行。"` |

---

## Out of scope

- **Python backend error messages** — come from FastAPI/Python as `ApiError.message`; always English by design; not localized.
- **`LogViewer.tsx` log content** — `{log.message}` and `{log.metadata.error}` are backend-generated English strings; intentionally excluded per requirements.
- **Other unvisited `.tsx` files** — existing audit confirms near-complete i18n coverage; no full AST scan warranted.

---

## Verification checklist

- [ ] `lsp_diagnostics` clean on all 4 changed `.ts`/`.tsx` files
- [ ] Switch locale to `zh-CN`; Background Task Panel shows Chinese task item names
- [ ] Switch locale to `zh-HK`; Background Task Panel shows Traditional Chinese task item names
- [ ] Simulate network disconnect; error toast shows translated text
- [ ] Open a training task log page; "Live Logs" header is translated but actual log lines remain English
- [ ] All three locale files have identical key structure (no missing keys between locales)
