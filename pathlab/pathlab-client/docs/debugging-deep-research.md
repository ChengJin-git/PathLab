# Deep Research 调试指南

## 后端日志

- **日志文件位置**: `server/backend/logs/pathlab.log`
- **格式**: `[timestamp] [DeepResearch/Gateway] [LEVEL] module - message`
- **启用 DEBUG 模式**: 设置环境变量 `DEBUG=true`
- **实时查看**: `tail -f server/backend/logs/pathlab.log`
- **安全**: 日志内容经过 `log_sanitizer.py` 清洗，防止日志注入

## 前端日志

### 启用 Debug 模式

两种方式（任选其一）:

1. **URL 参数**: 在地址栏添加 `?dr_debug=1`
2. **DevTools Console**: 执行以下命令后刷新页面
   ```js
   localStorage.setItem('pathlab.deep_research.debug', '1')
   ```

关闭 Debug 模式: URL 添加 `?dr_debug=0` 或 `localStorage.setItem('pathlab.deep_research.debug', '0')`

### 查看日志

- **本地日志文件**: `server/backend/logs/deep-research-frontend.log`
  - 前端日志每 3 秒自动写入本地文件（Electron 模式下）
  - 实时查看: `tail -f server/backend/logs/deep-research-frontend.log`
  - 与后端日志在同一目录，方便对照
- **DevTools Console**: 启用 Debug 模式后，所有 `[DeepResearch]` 前缀的日志会输出到 console
- **日志缓冲区**（最近 2000 条，无论是否开启 Debug 模式都会收集）:
  - `__DR_LOG_BUFFER()` — 查看原始日志数组
  - `__DR_DOWNLOAD_LOGS()` — 下载为 `.txt` 文件
  - `__DR_EXPORT_LOGS()` — 获取日志文本字符串
  - `__DR_CLEAR_LOGS()` — 清空缓冲区

### 状态快照

在 DevTools Console 输入:
```js
__DR_DEBUG_SNAPSHOT()
```
返回当前 store 状态摘要，包括 threadId、conversationId、消息数量、研究绑定关系等。

## 常见调试场景

### 1. 研究卡住不动

- 检查后端日志是否有报错: `tail -f server/backend/logs/pathlab.log`
- 前端检查 `__DR_DEBUG_SNAPSHOT()` 中的 `ongoingResearchId` 和 run status
- 下载前端日志 `__DR_DOWNLOAD_LOGS()` 查看最后的事件流

### 2. 消息渲染异常

- 启用 `?dr_debug=1`，查看 "message-list item skipped" 日志
- 检查 message 的 agent/role/content 字段

### 3. 白屏 / 崩溃

- 检查 DevTools Console 的红色错误
- 下载前端日志 `__DR_DOWNLOAD_LOGS()` 定位崩溃前的操作

### 4. 断线重连问题

- 查看后端日志中 job 状态
- 前端日志搜索 "reconnect" 或 "background"（下载日志后文本搜索）
