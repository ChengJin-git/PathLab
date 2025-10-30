# Model Checkpoints

此目录用于存放训练好的模型权重文件。

## 目录结构建议

```
checkpoints/
├── abmil/
│   ├── lung_cancer_3class.pth
│   └── breast_cancer_2class.pth
├── mean/
│   └── baseline_model.pth
└── custom/
    └── your_model.pth
```

## 使用方法

### 保存 checkpoint

```python
import torch

# 保存模型
torch.save({
    'state_dict': model.state_dict(),
    'num_classes': 3,
    'feature_dim': 2048,
    'epoch': 100,
    'accuracy': 0.95,
}, 'checkpoints/abmil/my_model.pth')
```

### 加载 checkpoint

```python
from lib import create_aggregator

# 创建聚合器并加载权重
aggregator = create_aggregator(
    name="abmil",
    feature_dim=2048,
    num_classes=3,
    device="cuda",
    checkpoint="checkpoints/abmil/my_model.pth"
)
```

## 注意事项

- checkpoint 文件通常较大，不要提交到 git
- 建议使用描述性的文件名，包含任务、类别数等信息
- 保存时建议包含训练相关的元信息（epoch, accuracy等）

