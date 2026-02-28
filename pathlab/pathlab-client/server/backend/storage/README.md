# Storage Management System

PathLab File Storage Management System, providing complete file lifecycle management.

## Overview

The storage management system provides centralized file lifecycle management, including:
- Automatic file cleanup (cascade deletion of all associated files when resources are deleted)
- Storage statistics and monitoring
- File path normalization
- Error handling and logging
- Orphaned file detection
- Storage migration support

## Architecture Design

### Core Components

**StorageManager** - Main storage manager
- Manages the lifecycle of all file resources
- Provides unified file deletion and query interface
- Based on convention-over-configuration file path rules

### File Organization Structure

```
uploads/
├── coordinates/        # Coordinate cache files
│   └── {wsi_id}_coords.h5
├── masks/              # Tissue mask visualization (also serves as thumbnails)
│   └── {wsi_id}_mask.png
├── features/           # Global features cache (reusable across tasks)
│   └── {extractor_name}/
│       └── {params_hash}/      # Preprocessing params hash (ensures same patching config for reuse)
│           └── {wsi_id}.pt     # Cached features
├── ai_results/         # AI analysis results
│   └── {wsi_id}/
│       └── {task_id}_attention.npy
├── training/           # Training task data
│   └── {task_id}/
│       └── features/
│           └── {wsi_id}.pt  # Symlink → global cache
├── models/             # Trained models
│   └── {model_id}/
│       ├── checkpoint.pth
│       ├── config.json
│       └── training_history.json
├── logs/               # Training logs
│   └── {task_id}.log
└── wsi_files/          # WSI original files
    └── {wsi_id}.{ext}
```

## Features

### 1. WSI File Management

Automatic cleanup when deleting WSI:
- WSI original file
- Coordinate cache (`coordinates/{wsi_id}_coords.h5`)
- Tissue mask (`masks/{wsi_id}_mask.png`)
- AI results directory (`ai_results/{wsi_id}/`)
- Feature files in all training tasks (`training/*/features/{wsi_id}.pt`, may be symlinks)
- Global feature cache (`features/{extractor_name}/{params_hash}/{wsi_id}.pt`)

**API Endpoints:**
```python
# Delete WSI (automatically cleans up all files)
DELETE /wsi/{wsi_id}

# Query WSI storage info
GET /storage/wsi/{wsi_id}
```

**Response Example:**
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

### 2. Training Task File Management

Automatic cleanup when deleting training task:
- Training directory (contains all feature files) (`training/{task_id}/`)
- Log file (`logs/{task_id}.log`)
- Associated model directory (`models/{model_id}/`)

**API Endpoints:**
```python
# Delete training task (automatically cleans up all files)
DELETE /tasks/training/{task_id}

# Query training task storage info
GET /storage/training/{task_id}
```

**Response Example:**
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

### 3. Global Storage Statistics

**API Endpoints:**
```python
# Get overall storage statistics
GET /storage/stats
```

**Response Example:**
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

## Usage Examples

### Using in Python Code

```python
from backend.storage.manager import StorageManager

# Initialize storage manager
storage_manager = StorageManager("/path/to/uploads")

# Delete WSI files
result = storage_manager.delete_wsi_files(
    wsi_id="slide_001",
    wsi_path="/path/to/slide_001.svs"
)
print(result["summary"])
# Output: WSI slide_001 storage cleanup: 6 files, 1 directories deleted, 0 failed, 1178.23 MB freed

# Delete training task files
result = storage_manager.delete_training_task_files(
    task_id="task_001",
    model_paths=["/path/to/models/model_001/checkpoint.pth"]
)
print(result["summary"])
# Output: Training task task_001 storage cleanup: 1 files, 2 directories deleted, 0 failed, 105.98 MB freed

# Get storage info
wsi_info = storage_manager.get_wsi_storage_info("slide_001", "/path/to/slide_001.svs")
print(f"Total size: {wsi_info['total_size_mb']:.2f} MB")

# Get global statistics
stats = storage_manager.get_total_storage_stats()
print(f"Total storage: {stats['total_size_gb']:.2f} GB")
```

## Design Principles

### 1. Convention Over Configuration
- No additional database tables needed to track files
- Automatic file discovery and deletion based on standardized path rules
- Simplified system complexity

### 2. Security
- Path validation before deletion (ensures files are within uploads directory)
- Error handling does not interrupt deletion flow
- Detailed logging

### 3. Extensibility
- Easy to add new resource types
- Unified interface design
- Modular implementation

### 4. Fault Tolerance
- Skip non-existent files (no error)
- Log failures but continue processing other files
- Return detailed deletion results and failure information

## Error Handling

Deletion operation returns results containing:
- `deleted_files`: List of successfully deleted files
- `deleted_dirs`: List of successfully deleted directories
- `failed`: Failed files/directories with error messages `[(path, error), ...]`
- `total_size`: Total space freed (bytes)
- `summary`: Human-readable summary

Example:
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

## Implemented Features

1. ✅ **Orphan File Detection** - Scan and identify files not referenced in database (`GET /storage/orphaned`)
2. ✅ **Storage Migration** - Move storage to new location (`POST /storage/migrate`)
3. ✅ **Disk Space Monitoring** - Get disk usage statistics (`GET /storage/disk-space`)
4. ✅ **Storage Configuration** - Get/update storage settings (`GET/PUT /storage/config`)
5. ✅ **Batch Import** - Batch import WSI files (`POST /storage/tasks/batch-import`)
6. ✅ **External File Management** - Manage external data files (`POST /storage/scan/*`)

1. ✅ **Orphan File Detection** - Scan and identify files not referenced in database (`GET /storage/orphaned`)
2. ✅ **Storage Migration** - Move storage to new location (`POST /storage/migrate`)
3. ✅ **Disk Space Monitoring** - Get disk usage statistics (`GET /storage/disk-space`)
4. ✅ **Storage Configuration** - Get/update storage settings (`GET/PUT /storage/config`)

## Future Extensions

Potential features to add:
1. **Storage Quota Management** - Limit storage usage per user or project
2. **Auto Archiving** - Move old data to archive storage
3. **Storage Optimization** - Compression, deduplication, etc.
4. **Backup Management** - Automatic backup of important files

## Maintenance Guidelines

1. **Regularly monitor storage usage**
   ```bash
   # Port is dynamically allocated, use the port number printed at startup
   curl http://localhost:$PORT/storage/stats
   ```

2. **Check failed deletions**
   - Review error messages in logs
   - Manually clean files with permission issues

3. **Verify file integrity**
   - Periodically check consistency between database records and actual files
   - Use storage info API to verify file existence

## Related Documentation

- [API Documentation](../../docs/api_contracts.md)
- [Database Models](../database/models.py)
- [Gateway Service](../../gateway/main.py)

