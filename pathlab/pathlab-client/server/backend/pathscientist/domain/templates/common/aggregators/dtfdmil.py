from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple, Optional, List
from .base import BaseAggregator


import torch
import torch.nn as nn
import torch.nn.functional as F

class Classifier_1fc(nn.Module):
    """
    Simple 1-FC Classifier
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
        A = torch.transpose(A, 1, 0)  # K x N (usually K=1 -> 1 x N)
        A = F.softmax(A, dim=1)  # softmax over N
        return A

class DimReduction(nn.Module):
    """
    Feature Dimension Reduction Layer (Optional, if input features are high-dimensional, e.g. 1024, reduce to 512)
    """
    def __init__(self, n_channels, m_dim=512):
        super(DimReduction, self).__init__()
        self.fc1 = nn.Linear(n_channels, m_dim, bias=False)
        self.relu1 = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.fc1(x)
        x = self.relu1(x)
        return x

class DTFDAggregator(BaseAggregator):
    """
    Strict implementation of DTFD following the official logic.
    """
    
    def __init__(self, in_dim: int, num_classes: int, num_pseudo_bags: int = 4, total_instance: int = 4, dropout: float = 0.25):
        """
        Args:
            in_dim: Input feature dimension (e.g. 1024)
            num_classes: Number of classification categories
            num_pseudo_bags: Number of pseudo-bags to divide the slide into during training (used in Tier-1)
            total_instance: "Distillation K", i.e., how many top patches to select from Tier-1 for Tier-2
                            (In the official code, this is usually calculated as instance_per_group * num_Group, simplified here as total K)
            dropout: Dropout rate
        """
        super().__init__(in_dim, num_classes)
        self.num_pseudo_bags = num_pseudo_bags
        self.k_instances = total_instance # This is the Top-K K
        
        # Unified feature dimension reduction (usually WSI features 1024 -> 512)
        # Note: In the official code, this is sometimes done inside AttentionNet, sometimes outside. Here for clarity, it's outside.
        self.dim_reduction = DimReduction(in_dim, m_dim=512)
        
        # --- Tier 1 (Instance/Pseudo-bag Tier) ---
        self.tier1_att = AttentionGated(L=512)
        self.tier1_cls = Classifier_1fc(512, num_classes, dropout)
        
        # --- Tier 2 (Bag/Slide Tier) ---
        # Tier 2 is also a MIL, but it only processes features selected by Tier 1
        self.tier2_att = AttentionGated(L=512)
        self.tier2_cls = Classifier_1fc(512, num_classes, dropout)
        
    def _get_top_k_features(self, features: torch.Tensor, attention_scores: torch.Tensor) -> torch.Tensor:
        """
        Core helper function: Select Top-K features based on Attention scores
        """
        # attention_scores: 1 x N
        # features: N x 512
        N = features.size(0)
        
        # Ensure K does not exceed N
        k = min(self.k_instances, N)
        
        # Select the indices of the top K
        _, indices = torch.topk(attention_scores.squeeze(0), k)
        
        # Select the corresponding features
        selected_features = torch.index_select(features, 0, indices) # K x 512
        return selected_features

    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Inference logic:
        1. Dimension reduction
        2. Tier-1 compute attention -> select top-K key patches
        3. Tier-2 aggregate these top-K -> get final logits
        """
        # 1. Dimension reduction
        feat = self.dim_reduction(H) # N x 512
        
        # 2. Tier 1: compute attention (for selection)
        att_tier1 = self.tier1_att(feat) # 1 x N
        
        # 3. Distillation: select top K features
        # Tier 2 only sees features selected by Tier 1
        selected_feat = self._get_top_k_features(feat, att_tier1) # K x 512
        
        # 4. Tier 2: final classification
        att_tier2 = self.tier2_att(selected_feat) # 1 x K
        
        # Weighted sum to get Bag Representation
        M_tier2 = torch.mm(att_tier2, selected_feat) # 1 x 512
        
        # Classification
        logits = self.tier2_cls(M_tier2) # 1 x C
        
        # Return Tier 1 attention (usually for heatmaps, because it's for the whole slide)
        return logits, att_tier1.squeeze(0)

    def run_one_step(self, features: torch.Tensor, labels: torch.Tensor, criterion: Optional[nn.Module] = None) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Training logic:
        Contains two parallel losses:
        Loss 1: Tier-1 loss on Pseudo-bags (forces the model to learn on local data)
        Loss 2: Tier-2 loss on Selected Top-K (forces the model to focus on key evidence)
        """
        device = features.device
        N = features.size(0)
        
        # 0. Feature transformation
        feat = self.dim_reduction(features) # N x 512
        
        # ===========================
        # Part A: Tier 1 (Pseudo-bags)
        # ===========================
        
        # 1. Randomly shuffle and split Pseudo-bags
        indices = torch.randperm(N, device=device)
        feat_shuffled = feat[indices]
        
        # Split into bags
        current_num_bags = self.num_pseudo_bags
        if N < current_num_bags: current_num_bags = 1
        chunk_size = (N + current_num_bags - 1) // current_num_bags
        pseudo_bags = torch.split(feat_shuffled, chunk_size, dim=0)

        loss_tier1 = 0.0
        # MIL prediction for each pseudo-bag
        for p_bag in pseudo_bags:
            if p_bag.size(0) == 0: continue
            
            # Tier 1 Attention & Aggregation
            att_p = self.tier1_att(p_bag) # 1 x N_p
            M_p = torch.mm(att_p, p_bag)  # 1 x 512
            logits_p = self.tier1_cls(M_p) # 1 x C
            
            # Inherit parent bag's label for pseudo-bag
            loss_tier1 += criterion(logits_p, labels)
            
        loss_tier1 = loss_tier1 / len(pseudo_bags)
        
        # ===========================
        # Part B: Tier 2 (Distillation)
        # ===========================
        
        # 1. Use Tier 1 to compute attention for the **whole slide** (Original Unshuffled)
        # Note: This is to get the selection criteria
        att_global_tier1 = self.tier1_att(feat) # 1 x N
        
        # 2. Select Top-K based on Tier 1's opinion
        selected_feat = self._get_top_k_features(feat, att_global_tier1) # K x 512
        
        # 3. Tier 2 predicts on the selected features
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