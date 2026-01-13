import torch.nn as nn


class LinearProbe(nn.Module):
    def __init__(self, feature_dim=512, num_classes=2, dropout_p=0.0):
        super().__init__()
        self.dropout = nn.Dropout(dropout_p) if dropout_p > 0 else nn.Identity()
        self.linear = nn.Linear(feature_dim, num_classes)
    
    def forward(self, x):
        x = self.dropout(x)
        return self.linear(x)
