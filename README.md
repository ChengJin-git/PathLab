# PathHub 

## 产品需求规格说明书 (PRD)

> **项目名称:** PathHub (Pathology Hub)   
> **版本:** v1.0    
> **日期:** 2025-12    
> **状态:** 规划中 (Planning)    
> **核心愿景:** 构建病理领域的 "Hugging Face"，实现“数据不动，模型动”的隐私计算生态。    

---

## 1. 项目背景与愿景 (Vision)

### 1.1 痛点分析
1.  **模型碎片化:** 病理 AI 模型分散在 GitHub 各处，缺乏统一的输入输出标准（倍率、切块大小不一）。
2.  **部署门槛高:** 医生无法使用复杂的 Python 脚本，缺乏“傻瓜式”的本地推理工具。
3.  **数据隐私壁垒:** 医疗数据（WSI）敏感度极高，无法上传至公有云，导致“数据孤岛”现象严重，限制了模型的大规模验证。

### 1.2 解决方案
**PathHub** 采用 **"中心化分发 + 去中心化推理"** 的混合架构：
* **Server (Cloud):** 基于 OpenCSG 二次开发，负责模型托管、版本管理、元数据索引及**受限沙箱评测**。
* **Client (Local):** 基于 Electron + Python 开发，提供智能向导 (Wizard) 和可视化阅片，确保原始切片数据**不出本地**。

---

## 2. 系统架构设计 (System Architecture)

### 2.1 架构拓扑图

```mermaid
graph TD
    %% 定义子图：Client 端
    subgraph ClientBox ["Client: PathHub Workbench (Electron)"]
        direction TB
        User["用户 / 病理医生"]
        
        subgraph FrontendBox ["Frontend (UI)"]
            Viewer["WSI 阅片器 (OpenSeadragon)"]
            Wizard["智能向导 / LLM"]
        end
        
        subgraph BackendBox ["Backend (Python Sidecar)"]
            Inference["本地推理引擎 (ONNX/PyTorch)"]
            LocalStorage[("本地隐私数据")]
        end
    end

    %% 定义子图：Server 端
    subgraph ServerBox ["Server: PathHub Cloud (OpenCSG Based)"]
        direction TB
        API["API Gateway"]
        ModelRepo["模型仓库 (Git-LFS)"]
        DataRepo["数据集仓库 (分级)"]
        Sandbox["沙箱评测系统 (Docker)"]
        Social["社区讨论"]
    end

    %% 交互流连线
    User -->|"1. 打开切片"| Viewer
    Viewer -->|"2. 元数据"| Wizard
    Wizard -->|"3. 查询推荐模型"| API
    API -->|"4. 返回模型列表"| Wizard
    Wizard -->|"5. 下载模型"| Inference
    ModelRepo -.->|"Git LFS"| Inference
    Inference <-->|"6. 读取/推理"| LocalStorage
    Inference -->|"7. 渲染结果"| Viewer

    %% 评测流 (Blind Evaluation)
    User -.->|"提交评测请求"| API
    API -->|"调度"| Sandbox
    Sandbox <-->|"读取 (受限)"| DataRepo
    Sandbox <-->|"拉取模型"| ModelRepo
```

### 2.2 核心技术栈
- Server: OpenCSG / CSGHub (Go/Python), PostgreSQL, MinIO (S3), Docker, Redis.

- Client: Electron (React/Vue), Python (FastAPI), ONNX Runtime, OpenSeadragon.

---

## 3. 功能需求详述 (Functional Requirements)

### 3.1 Server 端 (The Hub)

ID | 模块 | 功能点 | 详细描述 | 优先级
---|------|--------|----------|-------
S-01 | 模型仓库 | Git-LFS 托管 | 支持大文件模型权重存储，支持版本 Tag 管理。 | P0
S-02 | 模型仓库 | 元数据解析 | 强制解析 model_config.json，在 UI 展示适用倍率、染色类型等。 | P0
S-03 | 数据仓库 | 隐私分级 | 实现 Public (公开), Restricted (受限/盲测), Private (私有) 三级权限。 | P0
S-04 | 评测系统 | 沙箱评测 (Level 2) | 在断网 Docker 中运行用户代码测试 Restricted 数据，仅返回 Metrics。 | P1
S-05 | 评测系统 | Leaderboard | 针对特定任务（如乳腺癌淋巴结转移）生成模型性能排行榜。 | P1
S-06 | 社区 | 讨论版 | 支持针对模型/数据集的 Issue 讨论与 Star/Fork 社交功能。 | P2

### 3.2 Client 端 (The Workbench)

ID | 模块 | 功能点 | 详细描述 | 优先级
---|------|--------|----------|-------
C-01 | 基础架构 | 双进程守护 | Electron 主进程管理 Python 子进程生命周期，自动处理环境依赖。 | P0
C-02 | 阅片器 | WSI 可视化 | 支持 SVS, NDPI, TIFF 等格式，支持平滑缩放与多层级浏览。 | P0
C-03 | 向导 | 智能推荐 | 根据打开的切片信息（部位、染色），自动从 Server 检索匹配模型。 | P0
C-04 | 推理引擎 | 本地推理 | 下载模型到本地缓存，对当前视野或全片进行预测，保护数据隐私。 | P0
C-05 | 可视化结果 | 叠加 | 将推理结果（Mask/Heatmap）以图层形式叠加在 WSI 上，支持透明度调节。 | P0
C-06 | 交互 | LLM 助手(可选) | 集成对话框，允许用户通过自然语言指令调用模型。 | P2

---

## 4. 数据隐私与安全策略 (Data Privacy Strategy)

PathHub 的核心差异化在于对 Restricted (Level 2) 数据的处理。

### 4.1 隐私分级矩阵

等级 | 名称 | 适用场景 | 数据可见性 | 模型执行位置
-----|------|----------|------------|--------------
Level 1 | Public | 教学、公共竞赛 | 全员可下载 | 用户本地 / 云端
Level 2 | Restricted | 科研合作、多中心验证 | 不可下载 (Code-to-Data) | Server 端沙箱 (无网容器)
Level 3 | Private | 医院临床数据 | 仅 Owner 可见 | Client 端本地 (数据不上云)

### 4.2 沙箱安全机制 (针对 Level 2)

- **网络阻断:** 评测容器禁用所有 Outbound 网络连接。  
- **日志清洗:** 拦截 stdout/stderr，限制输出长度，防止通过日志打印像素数据。  
- **临时存储:** 容器销毁后，除 metrics.json 外的所有临时文件立即清除。

---

## 5. 接口与标准化 (Standards)

### 5.1 模型配置文件标准 (model_config.json)

为了实现 Client 端的“傻瓜式”调用，所有模型必须包含此文件。

```json
{
  "version": "1.0",
  "meta": {
    "name": "PathHub-Unified-Model",
    "framework": "pytorch"
  },

  // 输入标准：不管是哪种任务，Client 第一步都是切图
  "input": {
    "mpp": 0.5,
    "patch_size": [512, 512],
    "normalization": "macenko"
  },

  // 任务定义：开发者只需从以下三种模板里选一种
  "tasks": [
    
    // --- 类型 1: Patch Classification (图块分类) ---
    // 场景：判断这一小块是肿瘤还是正常
    // Client 行为：循环推理 -> 取最大概率类别 -> 在该 Patch 位置画一个半透明方块
    {
      "name": "Tumor Detection (Tile Level)",
      "type": "classification", 
      "tensor_index": 0,         // 输出是向量 [0.1, 0.9]
      "classes": [
        { "label": 0, "name": "Normal", "color": null },      // 正常不染色
        { "label": 1, "name": "Tumor",  "color": "#FF0000" }  // 肿瘤染成红色方块
      ]
    },

    // --- 类型 2: Patch Segmentation (像素分割) ---
    // 场景：精确勾勒肿瘤边界
    // Client 行为：循环推理 -> 获取 Mask -> 在 Patch 上进行像素级叠加
    {
      "name": "Nuclei Segmentation",
      "type": "segmentation",
      "tensor_index": 0,         // 输出是 Mask 图片 [512, 512]
      "classes": [
        { "label": 0, "name": "Background", "color": null },
        { "label": 1, "name": "Nuclei",     "color": "#0000FF" } // 细胞核染蓝
      ]
    },

    // --- 类型 3: WSI Classification (全片 MIL) ---
    // 场景：直接给这张片子下诊断，并给出热力图
    // Client 行为：提取全片特征 -> 喂入 Bag -> 显示诊断 -> 映射 Attention 权重
    {
      "name": "Slide Diagnosis",
      "type": "wsi",
      
      // 主输出：诊断结果
      "tensor_index": 0,         // 输出是全片概率
      "classes": [
        { "label": 0, "name": "Benign" },
        { "label": 1, "name": "Malignant" }
      ],

      // 辅助输出：热力图 (Attention Map)
      "attention": {
        "enabled": true,
        "tensor_index": 1,       // 输出是 Attention 权重向量
        "colormap": "jet",       // 渲染风格
        "opacity": 0.5
      }
    }
  ]
}
```

### 5.2 Client-Sidecar 通信协议

Electron (Frontend) 调用 Python (Backend) 的本地接口示例。

**Endpoint:** `POST http://localhost:PORT/inference`  

**Payload:**

```json
{
  "model_path": "cache/models/user_a/model_b",
  "wsi_file": "/Users/docs/slide_001.svs",
  "region": { "x": 1000, "y": 2000, "w": 1024, "h": 1024 }
}
```

---

## 6. 开发路线图 (Roadmap)

### Phase 1: 原型 (Prototype) - 1个月

**目标:** 跑通全流程，验证技术可行性。  

**任务:**

- 部署基础版 OpenCSG。
- Electron 实现打开本地 SVS 文件。
- Electron 调用 Python 脚本运行一个硬编码的 ResNet 模型。

### Phase 2: MVP (Minimum Viable Product) - 3个月

**目标:** 实现核心功能，发布内测版。  

**任务:**

- 定义并冻结 model_config.json。
- 实现 Client 端模型自动下载与版本管理。
- 实现 Wizard 基础推荐逻辑。
- Server 端支持 Public 数据集。

### Phase 3: 增强与生态 (Beta) - 6个月

**目标:** 完善隐私计算与社区功能。  

**任务:**

- 上线 Level 2 沙箱评测系统。
- 上线 Leaderboard。
- 集成 LLM 对话接口。