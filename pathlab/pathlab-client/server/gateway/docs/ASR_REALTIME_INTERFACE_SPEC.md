# PathLab ASR Realtime 接口规范（本地服务兼容 DashScope）

版本：v1.0  
适用范围：PathLab 网关 `server/gateway/routes/asr.py` 对接的上游 ASR Realtime 服务

## 1. 目标

本规范定义“本地 ASR 服务”与 PathLab Gateway 之间的接口，目标是与 DashScope Realtime ASR 事件协议保持一致，使前端与网关无需改造即可切换到本地服务。

PathLab 当前链路：
- 前端 -> Gateway：`/asr/realtime`（固定）
- Gateway -> 上游 ASR：本地服务优先，失败时可回退 DashScope

## 2. 术语

- `Gateway`：PathLab 的 `server/gateway/routes/asr.py`
- `Upstream ASR`：本地部署的 ASR Realtime 服务（你要实现）
- `Client Event`：Gateway 发给 Upstream 的事件
- `Server Event`：Upstream 回给 Gateway 的事件

## 3. 传输与鉴权

### 3.1 WebSocket 连接（必选）

Upstream 必须提供 WebSocket Realtime 端点，支持以下 URL 形式之一：

- `ws://<host>:<port>/<path>?model=<model_name>`
- `wss://<host>:<port>/<path>?model=<model_name>`

Gateway 会附带请求头：
- `OpenAI-Beta: realtime=v1`（必需兼容）
- `Authorization: Bearer <token>`（可选，若用户配置了 `local_asr_api_key`）

### 3.2 模型查询（可选但强烈建议）

当用户在 PathLab 设置页填写 HTTP Base URL（如 `http://127.0.0.1:8001/v1`）时，Gateway 会请求：

- `GET <base_url>/models`

建议返回 OpenAI 兼容结构：

```json
{
  "object": "list",
  "data": [
    { "id": "Qwen/Qwen3-ASR-1.7B", "object": "model", "owned_by": "local" }
  ]
}
```

用途：
- 连通性检测
- 自动探测可用 model

## 4. 事件协议（核心）

消息编码：UTF-8 JSON 文本帧。

### 4.1 通用约定

- 每条消息包含 `type` 字段（必需）
- `event_id` 建议保留并透传（可选）
- 未识别字段应忽略（向前兼容）

---

## 5. Client Event（Gateway -> Upstream）

### 5.1 `session.update`（必需支持）

用于初始化会话参数。

示例：

```json
{
  "event_id": "event_session_update",
  "type": "session.update",
  "session": {
    "input_audio_format": "pcm",
    "sample_rate": 16000,
    "input_audio_transcription": {},
    "turn_detection": {
      "type": "server_vad",
      "threshold": 0.0,
      "silence_duration_ms": 800
    }
  }
}
```

兼容要求：
- 必须接受 `input_audio_format=pcm`
- 必须接受 `sample_rate=16000`
- 必须接受 `turn_detection.type=server_vad`
- `threshold`、`silence_duration_ms` 按服务能力解释

### 5.2 `input_audio_buffer.append`（必需支持）

持续追加音频块。

示例：

```json
{
  "event_id": "event_audio_1730000000000",
  "type": "input_audio_buffer.append",
  "audio": "<base64-encoded-pcm16le-mono-16khz>"
}
```

音频格式要求：
- 编码前原始数据：PCM16 little-endian
- 单声道
- 16kHz
- `audio` 字段为 base64 字符串

### 5.3 `session.finish`（必需支持）

客户端请求结束会话。

```json
{
  "event_id": "event_finish",
  "type": "session.finish"
}
```

---

## 6. Server Event（Upstream -> Gateway）

### 6.1 `session.created`（必需）

连接建立后尽快返回。Gateway 设置页健康检查依赖此事件判断在线。

示例：

```json
{
  "type": "session.created",
  "session": {
    "id": "sess_local_001",
    "model": "Qwen/Qwen3-ASR-1.7B",
    "input_audio_format": "pcm"
  }
}
```

### 6.2 `session.updated`（推荐）

确认 `session.update` 已生效。

```json
{
  "type": "session.updated",
  "session": {
    "id": "sess_local_001"
  }
}
```

### 6.3 `input_audio_buffer.speech_started`（推荐）

服务端 VAD 检测到说话开始。

```json
{
  "type": "input_audio_buffer.speech_started",
  "audio_start_ms": 120
}
```

### 6.4 `input_audio_buffer.speech_stopped`（推荐）

服务端 VAD 检测到说话结束。

```json
{
  "type": "input_audio_buffer.speech_stopped",
  "audio_end_ms": 1860
}
```

### 6.5 `conversation.item.input_audio_transcription.text`（必需）

增量文本（partial）。PathLab 前端读取 `text`（并兼容 `stash` 拼接）。

```json
{
  "type": "conversation.item.input_audio_transcription.text",
  "text": "请帮我",
  "stash": "总结这张切片"
}
```

### 6.6 `conversation.item.input_audio_transcription.completed`（必需）

最终文本（final）。PathLab 前端只把 `transcript` 作为最终输入。

```json
{
  "type": "conversation.item.input_audio_transcription.completed",
  "transcript": "请帮我总结这张切片"
}
```

### 6.7 `session.finished`（推荐）

会话自然结束时返回。

```json
{
  "type": "session.finished"
}
```

### 6.8 `error`（必需）

统一错误事件。

```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "code": "bad_audio_format",
    "message": "Unsupported audio format",
    "param": "audio"
  }
}
```

---

## 7. 时序要求

典型顺序：
1. 建立 WS
2. Upstream 返回 `session.created`
3. Gateway 发送 `session.update`
4. Upstream 可返回 `session.updated`
5. Gateway 连续发送 `input_audio_buffer.append`
6. Upstream 按需发送：
   - `speech_started`
   - `...transcription.text`（多次）
   - `speech_stopped`
   - `...transcription.completed`（至少一次）
7. Gateway 发送 `session.finish`（或客户端断开）
8. Upstream 可返回 `session.finished` 并关闭连接

行为要求：
- `completed` 必须在一次话轮结束后产生；内容可为空但不建议
- 事件必须可被 JSON 解析，且 `type` 不可缺失
- 建议按时间顺序发送，避免乱序覆盖

## 8. 与 DashScope 一致性清单（必须满足）

- [ ] 事件名与本规范完全一致
- [ ] `completed` 事件包含 `transcript`
- [ ] `text` 事件包含 `text`（可选 `stash`）
- [ ] 支持 `OpenAI-Beta: realtime=v1`
- [ ] 接受 `session.update` + `input_audio_buffer.append` + `session.finish`
- [ ] 音频输入支持 PCM16LE/mono/16kHz/base64
- [ ] 首包可返回 `session.created`
- [ ] 异常统一走 `type=error`

## 9. 最小联调方法

1. 在 PathLab 设置页填写：
- `local_asr_enabled = true`
- `local_asr_base_url = ws://<your-host>:<port>/<realtime-path>`（或 http base）
- `local_asr_model = <your-model>`
- `local_asr_api_key = <optional>`

2. 点击设置页 ASR 检测，确认 online。

3. 打开 AIChat 麦克风录音，观察 Gateway 日志：
- `Connected to local ASR ...`
- `Local ASR -> Client: conversation.item.input_audio_transcription.completed ...`

## 10. 非目标

以下内容不在本规范范围内：
- TTS 回放协议
- 多通道/多采样率协商
- Speaker diarization（说话人分离）
- 语言自动检测结果的标准字段定义

