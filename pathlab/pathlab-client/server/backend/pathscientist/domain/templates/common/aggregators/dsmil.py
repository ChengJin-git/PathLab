"""DSMIL Aggregator Module
https://github.com/binli123/dsmil-wsi

"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple, Optional
from .base import BaseAggregator

import torch
import torch.nn as nn

import torch
import torch.nn as nn
import torch.nn.functional as F


class FCLayer(nn.Module):
    def __init__(self, in_size, out_size=1):
        super(FCLayer, self).__init__()
        self.fc = nn.Sequential(nn.Linear(in_size, out_size))
    def forward(self, feats):
        x = self.fc(feats)
        return feats, x

class BClassifier(nn.Module):
    def __init__(self, input_size, output_class, dropout_v=0.0, nonlinear=True, passing_v=False): # K, L, N
        super(BClassifier, self).__init__()
        if nonlinear:
            self.q = nn.Sequential(nn.Linear(input_size, 128), nn.ReLU(), nn.Linear(128, 128), nn.Tanh())
        else:
            self.q = nn.Linear(input_size, 128)
        if passing_v:
            self.v = nn.Sequential(
                nn.Dropout(dropout_v),
                nn.Linear(input_size, input_size),
                nn.ReLU()
            )
        else:
            self.v = nn.Identity()
        
        ### 1D convolutional layer that can handle multiple class (including binary)
        self.fcc = nn.Conv1d(output_class, output_class, kernel_size=input_size)
        
    def forward(self, feats, c): # N x K, N x C
        device = feats.device
        V = self.v(feats) # N x V, unsorted
        Q = self.q(feats).view(feats.shape[0], -1) # N x Q, unsorted
        
        # handle multiple classes without for loop
        _, m_indices = torch.sort(c, 0, descending=True) # sort class scores along the instance dimension, m_indices in shape N x C
        m_feats = torch.index_select(feats, dim=0, index=m_indices[0, :]) # select critical instances, m_feats in shape C x K 
        q_max = self.q(m_feats) # compute queries of critical instances, q_max in shape C x Q
        A = torch.mm(Q, q_max.transpose(0, 1)) # compute inner product of Q to each entry of q_max, A in shape N x C, each column contains unnormalized attention scores
        A = F.softmax( A / torch.sqrt(torch.tensor(Q.shape[1], dtype=torch.float32, device=device)), 0) # normalize attention scores, A in shape N x C, 
        B = torch.mm(A.transpose(0, 1), V) # compute bag representation, B in shape C x V
                
        B = B.view(1, B.shape[0], B.shape[1]) # 1 x C x V
        C = self.fcc(B) # 1 x C x 1
        C = C.view(1, -1)
        return C, A, B 


class MILNet(nn.Module):
    def __init__(self, i_classifier, b_classifier):
        super(MILNet, self).__init__()
        self.i_classifier = i_classifier
        self.b_classifier = b_classifier
        
    def forward(self, x):
        feats, classes = self.i_classifier(x)
        prediction_bag, A, B = self.b_classifier(feats, classes)
        # get attention weights for the top predicted class, return (N,)
        top1_class = torch.argmax(prediction_bag, dim=1).item()
        A = A[:, top1_class]  # (N,)

        return classes, prediction_bag, A
    

class DSMILAggregator(BaseAggregator):
    """
    DSMIL aggregator module.
    """
    
    def __init__(self, in_dim: int, num_classes: int, dropout: float = 0.5, nonlinear: bool = True, passing_v: bool = False):
        super().__init__(in_dim, num_classes)
        i_classifier = FCLayer(in_size=in_dim, out_size=num_classes)
        b_classifier = BClassifier(input_size=in_dim, output_class=num_classes, dropout_v=dropout, nonlinear=nonlinear, passing_v=passing_v)
        self.classifier = MILNet(i_classifier, b_classifier)
        
        
    def default_criterion(self):
        """
        Default loss function for MIL tasks.
        """
        return nn.CrossEntropyLoss()
    
    def run_one_step(self, features: torch.Tensor, labels: torch.Tensor, criterion: Optional[nn.Module] = None) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Run a single training step.
        
        Args:
            features: Instance features of shape (N, D)
            labels: Bag-level labels of shape (1,) or (B,)
        
        Returns:
            loss: Computed loss
            logits: Bag-level logits of shape (1, C)
        """
        instance_predictions, logits, _ = self.classifier(features)
        bag_loss = criterion(logits, labels)
        max_prediction, _ = torch.max(instance_predictions, dim=0)
        instance_loss = criterion(max_prediction.unsqueeze(0), labels)
        loss = bag_loss * 0.5 + instance_loss * 0.5
        return loss, logits
    
    def forward(self, H: torch.Tensor) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Aggregate instance features to produce bag-level prediction.
        
        Args:
            H: Instance features of shape (N, D) where N = number of patches, D = feature dim
        
        Returns:
            logits: Bag-level logits of shape (1, C) where C = num_classes
            attention: Optional attention weights of shape (N,) or None
        """
        _, logits, attention = self.classifier(H)
        return logits, attention
    
    @classmethod
    def build(cls, in_dim: int, num_classes: int, dropout: float = 0.5, nonlinear: bool = True, passing_v: bool = False) -> DSMILAggregator:
        """
        Factory method to build the aggregator.
        
        Args:
            in_dim: Input feature dimension
            num_classes: Number of output classes
            dropout: Dropout rate
            nonlinear: Whether to use nonlinear activation
            passing_v: Whether to pass the instance features directly
        
        Returns:
            Initialized aggregator instance
        """
        return cls(in_dim=in_dim, num_classes=num_classes, dropout=dropout, nonlinear=nonlinear, passing_v=passing_v)

