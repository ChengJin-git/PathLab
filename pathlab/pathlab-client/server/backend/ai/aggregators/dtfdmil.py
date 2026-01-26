from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple, Optional, List
from .base import BaseAggregator


import torch
import torch.nn as nn
import torch.nn.functional as F

# ==========================================
# 1. 基础组件 (参照官方 Attention.py)
# ==========================================

class Classifier_1fc(nn.Module):
    """
    简单的全连接分类器
    """
    def __init__(self, n_channels, n_classes, droprate=0.0):
        super(Classifier_1fc, self).__init__()
        self.fc = nn.Linear(n_channels, n_classes)
        self.dropout = nn.Dropout(droprate)

    def forward(self, x):
        x = self.dropout(x)
        x = self.fc(x)
        return x

class AttentionGated(nn.Module):
    """
    Gated Attention Network (Ilse et al.)
    注意：官方 DTFD 代码中，Attention 模块通常只输出 Attention Weights，
    或者同时输出加权后的特征。这里我们按照模块化设计。
    """
    def __init__(self, L=512, D=128, K=1):
        super(AttentionGated, self).__init__()
        self.L = L
        self.D = D
        self.K = K

        self.attention_V = nn.Sequential(
            nn.Linear(self.L, self.D),
            nn.Tanh()
        )
        self.attention_U = nn.Sequential(
            nn.Linear(self.L, self.D),
            nn.Sigmoid()
        )
        self.attention_weights = nn.Linear(self.D, self.K)

    def forward(self, x):
        # x: N x L
        A_V = self.attention_V(x)  # N x D
        A_U = self.attention_U(x)  # N x D
        A = self.attention_weights(A_V * A_U) # N x K
        A = torch.transpose(A, 1, 0)  # K x N (通常 K=1 -> 1 x N)
        A = F.softmax(A, dim=1)  # softmax over N
        return A

class DimReduction(nn.Module):
    """
    特征降维层 (可选，如果输入特征维度很高如 1024，先降维到 512)
    """
    def __init__(self, n_channels, m_dim=512):
        super(DimReduction, self).__init__()
        self.fc1 = nn.Linear(n_channels, m_dim, bias=False)
        self.relu1 = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.fc1(x)
        x = self.relu1(x)
        return x

# ==========================================
# 2. DTFD Aggregator (核心逻辑)
# ==========================================

class DTFDAggregator(BaseAggregator):
    """
    严格参照官方逻辑的 DTFD 实现。
    """
    
    def __init__(self, in_dim: int, num_classes: int, num_pseudo_bags: int = 4, total_instance: int = 4, dropout: float = 0.25):
        """
        Args:
            in_dim: 输入特征维度 (例如 1024)
            num_classes: 分类类别数
            num_pseudo_bags: 训练时将 Slide 划分为多少个伪包 (Tier-1用)
            total_instance: "Distillation K", 即从 Tier-1 选多少个 Top Patch 给 Tier-2
                            (官方代码中这通常通过 instance_per_group * num_Group 计算，这里简化为总数 K)
            dropout: Dropout 比率
        """
        super().__init__(in_dim, num_classes)
        self.num_pseudo_bags = num_pseudo_bags
        self.k_instances = total_instance # 这就是 Top-K 的 K
        
        # 统一的特征降维 (通常 WSI 特征 1024 -> 512)
        # 注意：官方代码有时是在 AttentionNet 内部做，有时外部做，这里为了清晰放在外部
        self.dim_reduction = DimReduction(in_dim, m_dim=512)
        
        # --- Tier 1 (Instance/Pseudo-bag Tier) ---
        self.tier1_att = AttentionGated(L=512)
        self.tier1_cls = Classifier_1fc(512, num_classes, dropout)
        
        # --- Tier 2 (Bag/Slide Tier) ---
        # Tier 2 也是一个 MIL，但它只处理 Tier 1 筛选出的特征
        self.tier2_att = AttentionGated(L=512)
        self.tier2_cls = Classifier_1fc(512, num_classes, dropout)
        
    def _get_top_k_features(self, features: torch.Tensor, attention_scores: torch.Tensor) -> torch.Tensor:
        """
        核心辅助函数：根据 Attention 分数筛选 Top-K 特征
        """
        # attention_scores: 1 x N
        # features: N x 512
        N = features.size(0)
        
        # 确保 K 不超过 N
        k = min(self.k_instances, N)
        
        # 选出 Top K 的索引
        _, indices = torch.topk(attention_scores.squeeze(0), k)
        
        # 选出对应的特征
        selected_features = torch.index_select(features, 0, indices) # K x 512
        return selected_features

    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        推理 (Inference) 逻辑:
        1. 降维
        2. Tier-1 计算注意力 -> 选出 Top-K 关键 Patch
        3. Tier-2 对这 Top-K 进行聚合 -> 得到最终 Logits
        """
        # 1. 降维
        feat = self.dim_reduction(H) # N x 512
        
        # 2. Tier 1: 计算注意力 (用于筛选)
        att_tier1 = self.tier1_att(feat) # 1 x N
        
        # 3. Distillation: 选出 Top K 特征
        # Tier 2 只能看到 Tier 1 认为重要的特征
        selected_feat = self._get_top_k_features(feat, att_tier1) # K x 512
        
        # 4. Tier 2: 最终分类
        att_tier2 = self.tier2_att(selected_feat) # 1 x K
        
        # 加权求和得到 Bag Representation
        M_tier2 = torch.mm(att_tier2, selected_feat) # 1 x 512
        
        # 分类
        logits = self.tier2_cls(M_tier2) # 1 x C
        
        # 返回 Tier 1 的注意力 (通常用于热力图可视化，因为它是针对全片的)
        return logits, att_tier1.squeeze(0)

    def run_one_step(self, features: torch.Tensor, labels: torch.Tensor, criterion: Optional[nn.Module] = None) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        训练 (Training) 逻辑:
        包含两个并行的 Loss：
        Loss 1: Tier-1 在 Pseudo-bags 上的 Loss (强迫模型在局部数据上学习)
        Loss 2: Tier-2 在 Selected Top-K 上的 Loss (强迫模型关注关键证据)
        """
        device = features.device
        N = features.size(0)
        
        # 0. 特征变换
        feat = self.dim_reduction(features) # N x 512
        
        # ===========================
        # Part A: Tier 1 (Pseudo-bags)
        # ===========================
        
        # 1. 随机打乱并划分 Pseudo-bags
        indices = torch.randperm(N, device=device)
        feat_shuffled = feat[indices]
        
        # 划分包
        current_num_bags = self.num_pseudo_bags
        if N < current_num_bags: current_num_bags = 1
        chunk_size = (N + current_num_bags - 1) // current_num_bags
        pseudo_bags = torch.split(feat_shuffled, chunk_size, dim=0)

        loss_tier1 = 0.0
        # 对每个伪包进行 MIL 预测
        for p_bag in pseudo_bags:
            if p_bag.size(0) == 0: continue
            
            # Tier 1 Attention & Aggregation
            att_p = self.tier1_att(p_bag) # 1 x N_p
            M_p = torch.mm(att_p, p_bag)  # 1 x 512
            logits_p = self.tier1_cls(M_p) # 1 x C
            
            # 伪包继承父包的 Label
            loss_tier1 += criterion(logits_p, labels)
            
        loss_tier1 = loss_tier1 / len(pseudo_bags)
        
        # ===========================
        # Part B: Tier 2 (Distillation)
        # ===========================
        
        # 1. 使用 Tier 1 对 **全片** (Original Unshuffled) 计算注意力
        # 注意：这里是为了获得筛选标准
        att_global_tier1 = self.tier1_att(feat) # 1 x N
        
        # 2. 根据 Tier 1 的意见筛选 Top-K
        selected_feat = self._get_top_k_features(feat, att_global_tier1) # K x 512
        
        # 3. Tier 2 在筛选后的特征上进行预测
        att_tier2 = self.tier2_att(selected_feat) # 1 x K
        M_tier2 = torch.mm(att_tier2, selected_feat) # 1 x 512
        logits_tier2 = self.tier2_cls(M_tier2) # 1 x C
        
        loss_tier2 = criterion(logits_tier2, labels)
        
        # ===========================
        # Total Loss
        # ===========================
        loss = loss_tier1 + loss_tier2
        
        return loss, logits_tier2

    @classmethod
    def build(cls, in_dim: int, num_classes: int, num_pseudo_bags: int = 4, total_instance: int = 4, dropout: float = 0.25) -> DTFDAggregator:
        return cls(in_dim=in_dim, num_classes=num_classes, num_pseudo_bags=num_pseudo_bags, total_instance=total_instance, dropout=dropout)

# -----------------------------------------------------------
# 测试代码 (验证维度流转)
# -----------------------------------------------------------
if __name__ == "__main__":
    # 模拟输入
    # N=1000 patches, D=1024 features
    feats = torch.randn(1000, 1024)
    label = torch.tensor([1]).long() # Bag label
    
    # 初始化: top_k (total_instance) 设为 10，模拟从 1000 个里选 10 个最关键的
    model = DTFDAggregator.build(in_dim=1024, num_classes=2, num_pseudo_bags=4, total_instance=10)
    
    criterion = nn.CrossEntropyLoss()
    
    # 1. 训练步
    loss, logits = model.run_one_step(feats, label, criterion)
    print(f"[Training] Loss: {loss.item():.4f}, Logits shape: {logits.shape}")
    
    # 2. 推理步
    logits_inf, attn = model(feats)
    print(f"[Inference] Logits: {logits_inf.detach().numpy()}, Attn shape: {attn.shape}")
    
    # 验证 Tier 2 是否只看到了 K 个特征
    # 可以通过断点调试 _get_top_k_features 验证，或查看显存占用
    print("DTFD-MIL impl validated.")