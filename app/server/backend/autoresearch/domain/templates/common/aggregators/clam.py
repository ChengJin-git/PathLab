"""CLAM Aggregator Module (Compatible with BaseAggregator)"""
from __future__ import annotations

from typing import Tuple, Optional, Dict, List

import torch
import torch.nn as nn
import torch.nn.functional as F
from .base import BaseAggregator


class Attn_Net_Gated(nn.Module):
    """
    Gated Attention Network (Ilse et al., 2018)
    Formula: a = W(tanh(V*h) * sigmoid(U*h))
    """
    def __init__(self, L: int = 1024, D: int = 256, dropout: bool = False, n_classes: int = 1):
        super().__init__()
        self.attention_a = nn.Sequential(nn.Linear(L, D), nn.Tanh())
        self.attention_b = nn.Sequential(nn.Linear(L, D), nn.Sigmoid())
        
        if dropout:
            self.dropout = nn.Dropout(0.25)
        else:
            self.dropout = nn.Identity()
            
        self.attention_c = nn.Linear(D, n_classes)

    def forward(self, x: torch.Tensor):
        a = self.attention_a(x)
        b = self.attention_b(x)
        A = a.mul(b)
        A = self.dropout(A)
        scores = self.attention_c(A)
        return scores, x

# ==========================================
# CLAM-SB (Single Branch) Implementation
# ==========================================

class CLAM_SB(BaseAggregator):
    """
    CLAM Single Branch (SB) implementation.
    Suitable for Binary Classification.
    """
    def __init__(self, in_dim: int, num_classes: int, 
                 dropout: float = 0.0, 
                 k_sample: int = 8, 
                 subtyping: bool = False,
                 bag_weight: float = 0.7):
        super().__init__(in_dim, num_classes)
        
        # Hyperparameters
        self.k_sample = k_sample
        self.subtyping = subtyping
        self.bag_weight = bag_weight # Weight for Bag Loss vs Instance Loss (default 0.7/0.3)
        self.instance_loss_fn = nn.CrossEntropyLoss()
        
        # Network Architecture
        # 1. Feature Projection (1024 -> 512)
        size = [in_dim, 512, 256]
        fc_layers = [nn.Linear(size[0], size[1]), nn.ReLU()]
        if dropout > 0.0:
            fc_layers.append(nn.Dropout(dropout))
            
        # 2. Gated Attention
        # SB: n_classes=1 (shared attention)
        attention_net = Attn_Net_Gated(L=size[1], D=size[2], dropout=dropout > 0.0, n_classes=1)
        fc_layers.append(attention_net)
        self.attention_net = nn.Sequential(*fc_layers)
        
        # 3. Bag Classifier
        self.classifiers = nn.Linear(size[1], num_classes)
        
        # 4. Instance Classifiers (for clustering loss)
        instance_classifiers = [nn.Linear(size[1], 2) for _ in range(num_classes)]
        self.instance_classifiers = nn.ModuleList(instance_classifiers)

    @staticmethod
    def create_positive_targets(length, device):
        return torch.full((length, ), 1, device=device).long()
    
    @staticmethod
    def create_negative_targets(length, device):
        return torch.full((length, ), 0, device=device).long()

    def inst_eval(self, A, h, classifier):
        device = h.device
        if len(A.shape) == 1: A = A.view(1, -1)
            
        # Top-K High & Low
        top_p_ids = torch.topk(A, self.k_sample)[1][-1]
        top_p = torch.index_select(h, dim=0, index=top_p_ids)
        top_n_ids = torch.topk(-A, self.k_sample, dim=1)[1][-1]
        top_n = torch.index_select(h, dim=0, index=top_n_ids)
        
        p_targets = self.create_positive_targets(self.k_sample, device)
        n_targets = self.create_negative_targets(self.k_sample, device)

        all_targets = torch.cat([p_targets, n_targets], dim=0)
        all_instances = torch.cat([top_p, top_n], dim=0)
        
        logits = classifier(all_instances)
        instance_loss = self.instance_loss_fn(logits, all_targets)
        return instance_loss

    def inst_eval_out(self, A, h, classifier):
        device = h.device
        if len(A.shape) == 1: A = A.view(1, -1)
        
        top_p_ids = torch.topk(A, self.k_sample)[1][-1]
        top_p = torch.index_select(h, dim=0, index=top_p_ids)
        p_targets = self.create_negative_targets(self.k_sample, device)
        
        logits = classifier(top_p)
        instance_loss = self.instance_loss_fn(logits, p_targets)
        return instance_loss

    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Standard forward pass compliant with BaseAggregator.
        Returns bag-level logits and attention weights.
        """
        # A: N x 1, h: N x 512
        A, h = self.attention_net(H) 
        A = torch.transpose(A, 1, 0) # 1 x N
        A_raw = A # Save raw scores for instance eval
        A = F.softmax(A, dim=1) 

        M = torch.mm(A, h) # 1 x 512
        logits = self.classifiers(M) # 1 x num_classes
        
        # We store intermediate results needed for loss calculation in self._cache
        # This is a common pattern when `forward` signature is restricted
        self._cache = {"A_raw": A_raw, "h": h}
        
        return logits, A.squeeze(0)

    def run_one_step(self, features: torch.Tensor, labels: torch.Tensor, criterion: Optional[nn.Module] = None) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Overridden step to include Instance-Level Clustering Loss.
        """
        # 1. Bag Level Forward
        logits, _ = self.forward(features)
        
        # 2. Bag Loss
        bag_loss = criterion(logits, labels)
        
        # 3. Instance Loss (CLAM Specific)
        # Retrieve cached features from forward pass
        if not hasattr(self, '_cache'):
            raise RuntimeError("Forward must be called before run_one_step logic")
            
        A_raw = self._cache["A_raw"]
        h = self._cache["h"]
        
        total_inst_loss = 0.0
        inst_labels = F.one_hot(labels, num_classes=self.num_classes).squeeze()
        
        for i in range(len(self.instance_classifiers)):
            classifier = self.instance_classifiers[i]
            if inst_labels[i].item() == 1:
                # In-class: High Attn -> Positive, Low Attn -> Negative
                inst_loss = self.inst_eval(A_raw, h, classifier)
            else:
                if self.subtyping:
                    # Out-class: High Attn -> Negative
                    inst_loss = self.inst_eval_out(A_raw, h, classifier)
                else:
                    continue
            total_inst_loss += inst_loss
            
        if self.subtyping:
            total_inst_loss /= len(self.instance_classifiers)
            
        # 4. Total Loss
        total_loss = self.bag_weight * bag_loss + (1 - self.bag_weight) * total_inst_loss
        
        return total_loss, logits

    @classmethod
    def build(cls, in_dim: int, num_classes: int, dropout: float = 0.25, k_sample: int = 8, subtyping: bool = False, bag_weight: float = 0.7) -> CLAM_SB:
        return cls(in_dim, num_classes, dropout, k_sample, subtyping, bag_weight)


# ==========================================
# CLAM-MB (Multi Branch) Implementation
# ==========================================

class CLAM_MB(CLAM_SB):
    """
    CLAM Multi Branch (MB) implementation.
    Suitable for Multi-class Classification.
    """
    def __init__(self, in_dim: int, num_classes: int, 
                 dropout: float = 0.25, 
                 k_sample: int = 8, 
                 subtyping: bool = False,
                 bag_weight: float = 0.7):
        # Initialize BaseAggregator directly to skip SB specific init
        BaseAggregator.__init__(self, in_dim, num_classes)
        
        self.k_sample = k_sample
        self.subtyping = subtyping
        self.bag_weight = bag_weight
        self.instance_loss_fn = nn.CrossEntropyLoss()
        
        size = [in_dim, 512, 256]
        fc_layers = [nn.Linear(size[0], size[1]), nn.ReLU()]
        if dropout > 0.0:
            fc_layers.append(nn.Dropout(dropout))
            
        # MB Difference 1: n_classes output for Attention
        attention_net = Attn_Net_Gated(L=size[1], D=size[2], dropout=dropout > 0.0, n_classes=num_classes)
        fc_layers.append(attention_net)
        self.attention_net = nn.Sequential(*fc_layers)
        
        # MB Difference 2: Independent Bag Classifiers for each class
        bag_classifiers = [nn.Linear(size[1], 1) for _ in range(num_classes)]
        self.classifiers = nn.ModuleList(bag_classifiers)
        
        instance_classifiers = [nn.Linear(size[1], 2) for _ in range(num_classes)]
        self.instance_classifiers = nn.ModuleList(instance_classifiers)

    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        # A: N x num_classes, h: N x 512
        A, h = self.attention_net(H)
        A = torch.transpose(A, 1, 0) # num_classes x N
        A_raw = A
        A = F.softmax(A, dim=1) # Softmax per class

        M = torch.mm(A, h) # num_classes x 512
        
        # Compute logits per class
        logits = torch.empty(1, self.num_classes).float().to(H.device)
        for c in range(self.num_classes):
            logits[0, c] = self.classifiers[c](M[c])
            
        self._cache = {"A_raw": A_raw, "h": h}
        
        return logits, A # Return all attention maps

    def run_one_step(self, features: torch.Tensor, labels: torch.Tensor, criterion: Optional[nn.Module] = None) -> Tuple[torch.Tensor, torch.Tensor]:
        # 1. Bag Level Forward
        logits, _ = self.forward(features)
        bag_loss = criterion(logits, labels)
        
        # 2. Instance Loss
        A_raw = self._cache["A_raw"] # num_classes x N
        h = self._cache["h"]
        
        total_inst_loss = 0.0
        inst_labels = F.one_hot(labels, num_classes=self.num_classes).squeeze()
        
        for i in range(len(self.instance_classifiers)):
            classifier = self.instance_classifiers[i]
            inst_label = inst_labels[i].item()
            
            # Use class-specific attention map A_raw[i]
            if inst_label == 1:
                inst_loss = self.inst_eval(A_raw[i], h, classifier)
            else:
                if self.subtyping:
                    inst_loss = self.inst_eval_out(A_raw[i], h, classifier)
                else:
                    continue
            total_inst_loss += inst_loss
            
        if self.subtyping:
            total_inst_loss /= len(self.instance_classifiers)
            
        total_loss = self.bag_weight * bag_loss + (1 - self.bag_weight) * total_inst_loss
        
        return total_loss, logits

    @classmethod
    def build(cls, in_dim: int, num_classes: int, dropout: float = 0.25, k_sample: int = 8, subtyping: bool = False, bag_weight: float = 0.7) -> CLAM_MB:
        return cls(in_dim, num_classes, dropout, k_sample, subtyping, bag_weight)