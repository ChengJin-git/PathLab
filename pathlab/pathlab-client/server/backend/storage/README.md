# Storage Management System

完整的可扩展存储管理系统，用于管理 PathLab 平台中的所有文件资源。

## 概述

存储管理系统提供了集中化的文件生命周期管理，包括：
- 自动文件清理（删除资源时级联删除所有关联文件）
- 存储统计和监控
- 文件路径规范化
- 错误处理和日志记录

## 架构设计

### 核心组件

**StorageManager** - 主存储管理器
- 管理所有文件资源的生命周期
- 提供统一的文件删除和查询接口
- 基于约定的文件路径规则

### 文件组织结构

```
uploads/
├── coordinates/        # 坐标缓存文件
│   └── {wsi_id}_coords.h5
├── masks/              # 组织掩码可视化（同时作为缩略图）
│   └── {wsi_id}_mask.png
├── features/           # 全局 features 缓存 (可跨任务复用)
│   └── {extractor_name}/
│       └── {params_hash}/      # 预处理参数哈希 (确保相同 patching 配置才复用)
│           └── {wsi_id}.pt     # 缓存的 features
├── ai_results/         # AI 分析结果
│   └── {wsi_id}/
│       └── {task_id}_attention.npy
├── training/           # 训练任务数据
│   └── {task_id}/
│       └── features/
│           └── {wsi_id}.pt  # 软链接 → 全局缓存
├── models/             # 训练的模型
│   └── {model_id}/
│       ├── checkpoint.pth
│       ├── config.json
│       └── training_history.json
├── logs/               # 训练日志
│   └── {task_id}.log
└── wsi_files/          # WSI 原始文件
    └── {wsi_id}.{ext}
```

## 功能说明

### 1. WSI 文件管理

删除 WSI 时自动清理：
- WSI 原始文件
- 坐标缓存 (`coordinates/{wsi_id}_coords.h5`)
- 组织掩码 (`masks/{wsi_id}_mask.png`)
- AI 结果目录 (`ai_results/{wsi_id}/`)
- 所有训练任务中的特征文件 (`training/*/features/{wsi_id}.pt`，可能是软链接)
- 全局特征缓存 (`features/{extractor_name}/{params_hash}/{wsi_id}.pt`)

**API 接口：**
```python
# 删除 WSI（自动清理所有文件）
DELETE /wsi/{wsi_id}

# 查询 WSI 存储信息
GET /storage/wsi/{wsi_id}
```

**返回示例：**
```json
{
  "wsi_id": "slide_001",
  "wsi_file": {"path": "...", "size": 1234567890, "exists": true},
  "coordinates": {"path": "...", "size": 12345, "exists": true},
  "mask": {"path": "...", "size": 98765, "exists": true},
  "ai_results": {"path": "...", "size": 456789, "exists": true, "file_count": 3},
  "features": [
    {"path": "...", "size": 234567, "task_id": "task_001"}
  ],
  "total_size": 1235432109,
  "total_size_mb": 1178.23,
  "total_size_gb": 1.15,
  "total_files": 5
}
```

### 2. Training Task 文件管理

删除训练任务时自动清理：
- 训练目录（包含所有特征文件）(`training/{task_id}/`)
- 日志文件 (`logs/{task_id}.log`)
- 关联的模型目录 (`models/{model_id}/`)

**API 接口：**
```python
# 删除训练任务（自动清理所有文件）
DELETE /tasks/training/{task_id}

# 查询训练任务存储信息
GET /storage/training/{task_id}
```

**返回示例：**
```json
{
  "task_id": "task_001",
  "training_dir": {"path": "...", "size": 12345678, "exists": true, "file_count": 50},
  "log_file": {"path": "...", "size": 12345, "exists": true},
  "models": [
    {"path": "...", "size": 98765432, "file_count": 3}
  ],
  "total_size": 111123455,
  "total_size_mb": 105.98,
  "total_size_gb": 0.10,
  "total_files": 54
}
```

### 3. 全局存储统计

**API 接口：**
```python
# 获取整体存储统计
GET /storage/stats
```

**返回示例：**
```json
{
  "uploads_dir": "/path/to/uploads",
  "total_size": 12345678900,
  "total_size_mb": 11774.68,
  "total_size_gb": 11.50,
  "breakdown": {
    "coordinates": {"size": 123456, "file_count": 10},
    "masks": {"size": 345678, "file_count": 5},
    "features_cache": {"size": 567890, "file_count": 20},
    "ai_results": {"size": 4567890, "file_count": 30},
    "training": {"size": 123456789, "file_count": 500},
    "models": {"size": 987654321, "file_count": 15},
    "logs": {"size": 12345, "file_count": 8},
    "wsi_files": {"size": 11234567890, "file_count": 10}
  },
  "timestamp": "2024-01-15T10:30:00.000000"
}
```

## 使用示例

### Python 代码中使用

```python
from pathlab.services.backend.storage import StorageManager

# 初始化存储管理器
storage_manager = StorageManager("/path/to/uploads")

# 删除 WSI 文件
result = storage_manager.delete_wsi_files(
    wsi_id="slide_001",
    wsi_path="/path/to/slide_001.svs"
)
print(result["summary"])
# Output: WSI slide_001 storage cleanup: 6 files, 1 directories deleted, 0 failed, 1178.23 MB freed

# 删除训练任务文件
result = storage_manager.delete_training_task_files(
    task_id="task_001",
    model_paths=["/path/to/models/model_001/checkpoint.pth"]
)
print(result["summary"])
# Output: Training task task_001 storage cleanup: 1 files, 2 directories deleted, 0 failed, 105.98 MB freed

# 获取存储信息
wsi_info = storage_manager.get_wsi_storage_info("slide_001", "/path/to/slide_001.svs")
print(f"Total size: {wsi_info['total_size_mb']:.2f} MB")

# 获取全局统计
stats = storage_manager.get_total_storage_stats()
print(f"Total storage: {stats['total_size_gb']:.2f} GB")
```

## 设计特点

### 1. 约定优于配置
- 不需要额外的数据库表来追踪文件
- 基于标准化的文件路径规则自动查找和删除文件
- 简化了系统复杂度

### 2. 安全性
- 删除前进行路径验证（确保文件在 uploads 目录内）
- 错误处理不会中断删除流程
- 详细的日志记录

### 3. 可扩展性
- 易于添加新的资源类型
- 统一的接口设计
- 模块化的实现

### 4. 容错性
- 文件不存在时跳过（不报错）
- 删除失败时记录但继续处理其他文件
- 返回详细的删除结果和失败信息

## 错误处理

删除操作返回的结果包含：
- `deleted_files`: 成功删除的文件列表
- `deleted_dirs`: 成功删除的目录列表
- `failed`: 失败的文件/目录及错误信息 `[(path, error), ...]`
- `total_size`: 释放的总空间（字节）
- `summary`: 人类可读的摘要

示例：
```json
{
  "deleted_files": ["/path/to/file1", "/path/to/file2"],
  "deleted_dirs": ["/path/to/dir1"],
  "failed": [
    ["/path/to/file3", "Permission denied"]
  ],
  "total_size": 123456789,
  "summary": "WSI slide_001 storage cleanup: 2 files, 1 directories deleted, 1 failed, 117.74 MB freed"
}
```

## 未来扩展

可以考虑添加的功能：
1. **孤立文件清理** - 扫描并清理数据库中不存在的文件
2. **存储配额管理** - 限制用户或项目的存储使用
3. **自动归档** - 将旧数据移动到归档存储
4. **存储优化** - 压缩、去重等
5. **备份管理** - 自动备份重要文件

## 维护建议

1. **定期监控存储使用情况**
   ```bash
   # 端口动态分配，使用启动时输出的端口号
   curl http://localhost:$PORT/storage/stats
   ```

2. **检查删除失败的文件**
   - 查看日志中的错误信息
   - 手动清理权限问题的文件

3. **验证文件完整性**
   - 定期检查数据库记录与实际文件的一致性
   - 使用存储信息 API 验证文件存在性

## 相关文档

- [API 文档](../../docs/api_contracts.md)
- [数据库模型](../database/models.py)
- [Gateway 服务](../../gateway/main.py)

