"""WSI Survival Analysis Trainer - Discrete Time Survival."""
from __future__ import annotations

import json
import numpy as np
import math
from pathlib import Path
from typing import Dict, List, Any, Optional

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

from backend.ai.tasks.base import BaseTrainer
from backend.ai.extractors import get_extractor
from backend.ai.aggregators import get_aggregator
from backend.ai.utils.dataset import build_dataloader
from backend.ai.utils.vram_guard import (
    check_vram_before_model_load,
    check_vram_before_batch_processing,
    VRAMInsufficientError,
    VRAMExceededError,
)
from backend.ai.schemas import TaskType, TrainResponse, FeatureExtractionResponse
from backend.ai.tasks.feature_cache import (
    compute_params_hash,
    find_cached_features,
    get_cache_save_path,
    create_symlink_to_cache,
    read_params_from_coords_h5,
)
from backend.ai.tasks.wsi_classification.trainer import WSIClassificationTrainer
from backend.database.repositories import WSIRepository, TrainingTaskRepository

# -----------------------------------------------------------------------------
# Discrete Survival Loss
# -----------------------------------------------------------------------------
class NLLSurvivalLoss(nn.Module):
    """
    Negative Log Likelihood Loss for Discrete-Time Survival Analysis.
    
    Model outputs: Logits for K bins (hazards).
    """
    def __init__(self, eps=1e-7):
        super().__init__()
        self.eps = eps

    def forward(self, logits, y_bin, event):
        """
        logits: (batch, num_bins) - raw output from model
        y_bin: (batch,) - bin index where event/censoring occurred
        event: (batch,) - 1 if event occurred, 0 if censored
        """
        # Sigmoid to get hazard probabilities h(t|T>=t)
        hazards = torch.sigmoid(logits)
        
        # Survival term: log(1 - h)
        # We want to sum log(1-h) for all bins BEFORE y_bin
        # Create a mask for bins < y_bin
        batch_size, num_bins = logits.shape
        
        # Mask of shape (batch, num_bins) where mask[i, j] = 1 if j < y_bin[i]
        # This represents all the bins the patient SURVIVED through
        # range_tensor: [0, 1, ..., num_bins-1]
        range_tensor = torch.arange(num_bins, device=logits.device).unsqueeze(0)
        y_bin = y_bin.unsqueeze(1)
        
        survived_mask = (range_tensor < y_bin).float()
        
        # Event mask: mask[i, j] = 1 if j == y_bin[i] AND event[i] == 1
        event_mask = (range_tensor == y_bin).float() * event.unsqueeze(1)
        
        # Loss calculation
        # 1. Uncensored: log(h_bin) + Sum_{j<bin} log(1 - h_j)
        # 2. Censored: Sum_{j<bin} log(1 - h_j)  (assuming censored at start of bin)
        
        # Survival loss term (for all samples)
        # log(1 - h)
        surv_loss = survived_mask * torch.log(1 - hazards + self.eps)
        
        # Event loss term (only for uncensored samples)
        # log(h)
        event_loss = event_mask * torch.log(hazards + self.eps)
        
        # Total log likelihood
        log_likelihood = surv_loss + event_loss
        
        # Minimize negative log likelihood
        loss = -torch.sum(log_likelihood) / batch_size
        return loss

# -----------------------------------------------------------------------------
# Metrics Utils
# -----------------------------------------------------------------------------
def calculate_c_index(y_true, y_pred, event):
    """
    Calculate Harrell's C-Index manually O(N^2).
    
    y_true: True times
    y_pred: Predicted risk scores (higher = higher risk = shorter survivor)
    event: Event status (1=event, 0=censored)
    """
    n = len(y_true)
    if n < 2:
        return 0.5
    
    permissible = 0
    concordant = 0
    
    for i in range(n):
        for j in range(i + 1, n):
            # Check if pair is comparable
            # Comparable if:
            # 1. Both events occurred (event[i]=1, event[j]=1)
            # 2. One event, one censored, AND time_event < time_censored
            
            t_i, t_j = y_true[i], y_true[j]
            e_i, e_j = event[i], event[j]
            r_i, r_j = y_pred[i], y_pred[j]
            
            is_comp = False
            
            if e_i == 1 and e_j == 1:
                is_comp = True
            elif e_i == 1 and e_j == 0 and t_i < t_j:
                is_comp = True
            elif e_i == 0 and e_j == 1 and t_j < t_i:
                is_comp = True
                
            if is_comp:
                permissible += 1
                
                # We want concordant if higher risk corresponds to lower time
                # If t_i < t_j (i died first), we expect r_i > r_j (i higher risk)
                
                if t_i < t_j:
                    if r_i > r_j:
                        concordant += 1
                    elif r_i == r_j:
                        concordant += 0.5
                elif t_j < t_i:
                    if r_j > r_i:
                        concordant += 1
                    elif r_i == r_j:
                        concordant += 0.5
                else: # t_i == t_j
                    if e_i == 1 and e_j == 1:
                         # diff risk, same time? penalty? usually considered tied outcome
                         if r_i == r_j:
                             concordant += 1 # or 0.5?
                         else:
                             concordant += 0.5
    
    if permissible == 0:
        return 0.5
        
    return concordant / permissible


class WSISurvivalTrainer(WSIClassificationTrainer):
    """
    WSI Survival Analysis Trainer.
    
    Inherits from WSIClassificationTrainer to reuse feature extraction logic.
    Overrides training loop for Discrete-Time Survival Analysis.
    """
    
    task_type = TaskType.WSI_SURVIVAL
    
    async def train_model(
        self,
        wsi_ids: List[str],
        aggregator_name: str,
        num_classes: int, # Here likely 4 bins
        epochs: int,
        lr: float,
        logger: Any,
        db: Any,
    ) -> TrainResponse:
        """
        Train survival model.
        num_classes: Number of discrete time bins (default: 4)
        """
        # Load features (reuse parent method)
        features_dir = self.uploads_root / "training" / self.task_id / "features"
        feats = self._load_features(features_dir, wsi_ids)
        
        # Load labels (time and status)
        times = []
        statuses = []
        valid_ids = []
        
        for wsi_id in wsi_ids:
            wsi = await WSIRepository.get_by_id(db, wsi_id)
            if wsi and wsi.event_time is not None and wsi.event_status is not None:
                times.append(float(wsi.event_time))
                statuses.append(int(wsi.event_status))
                valid_ids.append(wsi_id)
            else:
                await logger.warning(f"Skipping WSI {wsi_id} - missing survival data")
        
        if not valid_ids:
            raise ValueError("No WSIs with valid survival data found")
            
        wsi_ids = valid_ids
        n_samples = len(times)
        
        # Discretize time into bins logic
        # We need to determine bin edges from uncensored data quantiles
        uncensored_times = [t for t, s in zip(times, statuses) if s == 1]
        
        if not uncensored_times:
            # Fallback if no events
            uncensored_times = times
            
        # Compute quantiles for n_bins
        # num_classes is used as n_bins
        n_bins = max(2, num_classes) # Minimum 2 bins
        
        quantiles = np.linspace(0, 100, n_bins + 1)
        bin_edges = np.percentile(uncensored_times, quantiles)
        # Ensure unique edges
        bin_edges = np.unique(bin_edges)
        if len(bin_edges) < n_bins + 1:
            # If duplicates (e.g. many events at same time), fill with max
             bin_edges = np.linspace(min(times), max(times), n_bins + 1)
        
        # Assign bins
        # np.digitize returns indices of bins to which values belong
        # bins: [b0, b1, b2, b3, b4]. 
        # digitize(x, bins) -> 1 if b0 <= x < b1.
        # We want 0-indexed. -> digitize(...) - 1
        
        # Note: digitize logic:
        # bins[i-1] <= x < bins[i] -> index i
        
        # We want: 0 if < b1. 1 if < b2...
        # Let's use simpler logic:
        # Bin bounds: [0, q1, q2, q3, inf]
        # We use standard searchsorted
        
        # We ignore the first edge (usually 0) for upper bound comparison
        class_bounds = bin_edges[1:] # (q1, q2, q3, q4)
        
        # Actually it's cleaner to strictify:
        # Bin 0: time < q1
        # Bin 1: q1 <= time < q2
        # ...
        
        discretized_labels = []
        for t in times:
            # Find which bin this time falls into
            # Logic: index of first bound > t
            # If t is larger than all bounds, it takes last bin
            
            bin_idx = 0
            for i, bound in enumerate(class_bounds):
                if t <= bound: # Using <= to handle edges
                    bin_idx = i
                    break
            else:
                bin_idx = len(class_bounds) - 1
            
            discretized_labels.append(bin_idx)
            
        # Convert to tensor
        y_bins = torch.tensor(discretized_labels, dtype=torch.long, device=self.device)
        y_events = torch.tensor(statuses, dtype=torch.float32, device=self.device)
        
        # Model setup
        # Determine feature dimension
        any_tensor = next(iter(feats.values()))
        in_dim = int(any_tensor.shape[1])
        
        # Aggregator outputs logits for n_bins
        # Note: num_classes argument corresponds to n_bins for survival
        model = get_aggregator(aggregator_name, in_dim=in_dim, num_classes=n_bins).to(self.device)
        
        criterion = NLLSurvivalLoss()
        optimizer = optim.Adam(model.parameters(), lr=lr)
        
        # Training loop
        history = {"loss": [], "c_index": []}
        model.train()
        
        for epoch in range(1, epochs + 1):
            running_loss = 0.0
            
            # Predict all for C-Index calculation
            epoch_preds = []
            
            # Simple full batch loop (gradient accumulation if needed, but usually fits)
            # Actually we process one by one or small batches.
            # BaseTrainer calls this usually with loose VRAM constraints if standard aggregator
            # WSIClassificationTrainer loops one by one.
            
            optimizer.zero_grad()
            batch_loss = 0.0
            
            # Use gradient accumulation to simulate batch size = all (since N is small)
            # Or use batch size = 32
            batch_accum = 32
            count = 0
            
            for i, wsi_id in enumerate(wsi_ids):
                H = feats[wsi_id].to(self.device)
                logits, _ = model(H) # (1, n_bins)
                
                # Single sample loss
                # Extract bin and event
                # y_bins is (N,), slice it
                target_bin = y_bins[i].unsqueeze(0)
                target_event = y_events[i].unsqueeze(0)
                
                loss = criterion(logits, target_bin, target_event)
                
                # Backward
                loss.backward()
                
                running_loss += float(loss.item())
                batch_loss += float(loss.item())
                
                # Store logits to calculate risk (hazards)
                hazards = torch.sigmoid(logits).detach().cpu().numpy() # (1, n_bins)
                # Risk score: Sum of hazards ~ cumulative hazard? 
                # Or just expected survival time (negated)?
                # Exp Surv = Sum(prob(t in bin k) * time_k)
                # Simpler C-Index risk: Sum of hazards (cumulative hazard) works well as risk score
                risk = np.sum(hazards) 
                epoch_preds.append(risk)
                
                count += 1
                if count % batch_accum == 0:
                    optimizer.step()
                    optimizer.zero_grad()
            
            # Step remaining
            if count % batch_accum != 0:
                optimizer.step()
                optimizer.zero_grad()
            
            epoch_loss = running_loss / max(1, n_samples)
            
            # Calculate C-Index on specific set (training set here)
            c_index = calculate_c_index(times, epoch_preds, statuses)
            
            history["loss"].append(epoch_loss)
            history["c_index"].append(c_index)
            
            await logger.info(
                f"Epoch {epoch}/{epochs} - loss: {epoch_loss:.4f} - c-index: {c_index:.4f}",
                metadata={"epoch": epoch, "loss": epoch_loss, "c_index": c_index}
            )
            
            progress = 66 + int(epoch / epochs * 34)
            await TrainingTaskRepository.update_status(db, self.task_id, "training", progress=progress)
            await db.commit()
            
        # Save checkpoints (similar to classification)
        model_id = f"{aggregator_name}_{self.task_id}"
        model_dir = self.uploads_root / "models" / model_id
        model_dir.mkdir(parents=True, exist_ok=True)
        ckpt_path = model_dir / "aggregator.pth"
        
        torch.save({
            "state_dict": model.state_dict(),
            "in_dim": in_dim,
            "num_classes": n_bins,
            "bin_edges": bin_edges, # Save bin edges for inference
        }, ckpt_path)
        
        # Save config
        (model_dir / "config.json").write_text(json.dumps({
            "task_id": self.task_id,
            "task_type": self.task_type,
            "model": aggregator_name,
            "in_dim": in_dim,
            "num_classes": n_bins,
            "epochs": epochs,
            "lr": lr,
            "bin_edges": bin_edges.tolist(),
        }, ensure_ascii=False, indent=2))
        
        # Save prediction results
        await self._save_survival_results(
            model=model,
            feats=feats,
            wsi_ids=wsi_ids,
            times=times,
            statuses=statuses,
            task_id=self.task_id,
            bin_edges=bin_edges,
            logger=logger,
            db=db
        )
        
        return self._build_train_response(
            model_id=model_id,
            checkpoint_path=str(ckpt_path),
            loss_history=history["loss"],
        )

    
    async def _save_survival_results(
        self,
        model,
        feats,
        wsi_ids,
        times,
        statuses,
        task_id,
        bin_edges,
        logger,
        db
    ):
        model.eval()
        ai_results_root = self.uploads_root / "ai_results"
        has_raw_attention = hasattr(model, 'forward_with_raw_attention')
        
        all_risks = []
        
        with torch.inference_mode():
            for i, wsi_id in enumerate(wsi_ids):
                H = feats[wsi_id].to(self.device)
                
                if has_raw_attention:
                    logits, attention, raw_attention = model.forward_with_raw_attention(H)
                else:
                    logits, attention = model(H)
                    raw_attention = None
                
                # Compute hazards
                hazards = torch.sigmoid(logits).cpu().numpy().flatten()
                
                # Compute survival function S(t) = prod(1-h) for discrete bins
                # S_k = S(t > bin_k_end) = Prod_{j=0}^k (1 - h_j)
                surv = np.cumprod(1 - hazards)
                
                # Risk score (cumulative hazard sum)
                risk_score = np.sum(hazards)
                all_risks.append(risk_score)
                
                result_dir = ai_results_root / wsi_id
                result_dir.mkdir(parents=True, exist_ok=True)
                
                result_data = {
                    "wsi_id": wsi_id,
                    "task_id": task_id,
                    "risk_score": float(risk_score),
                    "hazards": hazards.tolist(),
                    "surv_probs": surv.tolist(),
                    "event_time": times[i],
                    "event_status": statuses[i],
                    "bin_edges": bin_edges.tolist()
                }
                
                with open(result_dir / f"train_{task_id}_result.json", 'w') as f:
                    json.dump(result_data, f, indent=2)

                # Save attention if available
                if raw_attention is not None:
                     np.save(result_dir / f"train_{task_id}_attention_raw.npy", raw_attention.cpu().numpy())
                     
        # Calculate overall C-Index
        overall_c_index = calculate_c_index(times, all_risks, statuses)
        
        await logger.info(
            f"Survival Training Finished. Final C-Index: {overall_c_index:.4f}",
            metadata={"c_index": overall_c_index}
        )
