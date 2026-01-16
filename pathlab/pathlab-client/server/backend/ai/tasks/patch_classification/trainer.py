"""Patch Classification Trainer"""

import os
import json
import torch
from omegaconf import OmegaConf
import logging
from typing import Dict, Optional

from backend.ai.extractors import get_extractor
from backend.ai.utils.patch_dataset import build_datasets
from backend.ai.utils.metrics import ClassificationMetrics
from backend.ai.segmentors.tools.schedulers import build_scheduler
from backend.ai.utils.loss import ClassificationLoss
from backend.ai.tasks.patch_classification.linear_layer import LinearProbe
from backend.ai.schemas import TaskType, TrainResponse, TrainMetrics


logger = logging.getLogger("patch_classification_trainer")


class PatchClassificationTrainer():
    """
    Trainer for patch-level classification tasks.

    与 WSIClassificationTrainer 不同，这个 Trainer 使用 config-based 初始化，
    但同样返回统一格式的 TrainResponse。
    """

    task_type = TaskType.PATCH_CLASSIFICATION

    def __init__(
        self,
        config,
    ):
        """ """
        self.cfg = OmegaConf.create(config)
        self.device = torch.device(self.cfg.device)
            
        # Build datasets
        self.train_dataset, self.val_dataset, self.test_dataset = build_datasets(OmegaConf.to_container(self.cfg, resolve=True))
        logger.info("Train dataset size: {}".format(self.train_dataset.print_dataset_stats()))
        logger.info("Validation dataset size: {}".format(self.val_dataset.print_dataset_stats()))
        logger.info("Test dataset size: {}".format(self.test_dataset.print_dataset_stats()))
        
        # Build model
        self.backbone_extractor = get_extractor(
            name=self.cfg.model.backbone,
            pretrained=True,
            hf_token=self.cfg.model.get("hf_token", ""),
        ).to(self.device)
        
        # set the extractor's transform
        self.train_dataset.set_fm_transform(self.backbone_extractor.get_transforms())
        self.val_dataset.set_fm_transform(self.backbone_extractor.get_transforms())
        self.test_dataset.set_fm_transform(self.backbone_extractor.get_transforms())

        # Define classification head
        self.linear_layer = LinearProbe(
            feature_dim=self.backbone_extractor.output_dim,
            num_classes=self.cfg.model.num_classes,
            dropout_p=self.cfg.model.get("dropout_p", 0.0),
        ).to(self.device)

        if self.cfg.model.type == "linear":
            # freeze backbone
            for param in self.backbone_extractor.parameters():
                param.requires_grad = False
        
        self.model = torch.nn.Sequential(
                self.backbone_extractor,
                self.linear_layer,
            ).to(self.device)
        
        self.metrics = ClassificationMetrics(
            num_classes=self.cfg.model.num_classes,
            eval_metrics_cfg=OmegaConf.to_container(self.cfg.eval_metrics, resolve=True)
        )

        self.criterion = ClassificationLoss(
            loss_cfg=OmegaConf.to_container(self.cfg.loss, resolve=True),
            loss_weights=OmegaConf.to_container(self.cfg.loss_weights, resolve=True),
        )
        

    def train_step(
        self, 
        model: torch.nn.Module,
        batch,
        device,
        optimizer,
        optimizer_gradient_clip,
        scheduler,
        criterion,
        global_step,
    ):
        # a) load batch
        batch_img, gt = batch
        batch_img = batch_img.to(device)  # B x C x h x w
        gt = gt.to(device)  # B x (num_classes if multilabel) x h x w
        optimizer.zero_grad(set_to_none=True)

        # b) forward pass
        pred = model(batch_img)  # B x num_classes x h x w
        gt = torch.squeeze(gt).long()  # Adapt gt dimension to enable loss calculation

        # c) compute loss
        loss = criterion(pred, gt)

        # d) optimization
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            model.parameters(), optimizer_gradient_clip
        )
        optimizer.step()

        if global_step > 0:  # inheritance from old mmcv code
            scheduler.step()
        return loss

    def evaluate_model(
        self,
        model: torch.nn.Module,
        test_dataloader,
    ):
        model.eval()
        all_predictions = []
        all_ground_truths = []
        with torch.no_grad():
            for batch_img, gt in test_dataloader:
                batch_img = batch_img.to(self.device)
                pred = model(batch_img)
                all_predictions.append(pred.cpu())
                all_ground_truths.append(gt.cpu())
                logger.info(f"Evaluating batch: [{len(all_predictions)}/{len(test_dataloader)}] batches")
                
        all_predictions = torch.cat(all_predictions, dim=0)
        all_ground_truths = torch.cat(all_ground_truths, dim=0)
        final_metrics = self.metrics(all_predictions, all_ground_truths)
        return final_metrics

    def validate(
        self,
        model: torch.nn.Module,
        val_dataloader,
        metric_to_save,
        current_best_metric_to_save_value,
    ):
        new_metric_values_dict = self.evaluate_model(
            model,
            val_dataloader,
        )
        is_better = False
        if new_metric_values_dict[metric_to_save] > current_best_metric_to_save_value:
            is_better = True
        return is_better, new_metric_values_dict


    def train_model(self, db):
        """Train segmentation model"""
        train_loader = torch.utils.data.DataLoader(
            self.train_dataset, batch_size=self.cfg.bs, shuffle=True, num_workers=4
        )
        val_loader = torch.utils.data.DataLoader(
            self.val_dataset, batch_size=self.cfg.bs, shuffle=False, num_workers=4
        )
        test_loader = torch.utils.data.DataLoader(
            self.test_dataset, batch_size=self.cfg.bs, shuffle=False, num_workers=4
        )
        
        total_iter = self.cfg.epochs * len(train_loader)

        optimizer = torch.optim.AdamW(
            [
                {
                    "params": filter(
                        lambda p: p.requires_grad, self.model.parameters()
                    ),
                    "lr": self.cfg.optimizer.lr,
                    "betas": (self.cfg.optimizer.beta1, self.cfg.optimizer.beta2),
                    "weight_decay": self.cfg.optimizer.weight_decay,
                }
            ]
        )

        scheduler = build_scheduler(
            scheduler_type=self.cfg.scheduler.type,
            optimizer=optimizer,
            lr=self.cfg.optimizer.lr,
            total_iter=total_iter,
            constructor_kwargs=self.cfg.scheduler.constructor_kwargs,
        )
        
        # Training loop
        global_step = 0
        global_best_metric_values = {metric: 0.0 for metric in self.cfg.eval_metrics.keys()}

        history = {"epoch loss": [], 'iter loss': [], 'lr': []}

        for epoch in range(1, self.cfg.epochs + 1):
            epoch_loss = 0.0
            self.model.train()
            for batch in train_loader:
                loss = self.train_step(
                    model=self.model,
                    batch=batch,
                    device=self.device,
                    optimizer=optimizer,
                    optimizer_gradient_clip=self.cfg.optimizer.gradient_clip,
                    scheduler=scheduler,
                    criterion=self.criterion,
                    global_step=global_step,
                )
                global_step += 1
                epoch_loss += loss.item()
                history["iter loss"].append(loss.item())
                history["lr"].append(scheduler.get_last_lr()[0])
                logger.info(f"Epoch {epoch} Iteration {global_step}: loss={loss.item():.4f} lr={scheduler.get_last_lr()[0]:.6f}")
            
            epoch_loss /= len(train_loader)
            history["epoch loss"].append(epoch_loss)
            logger.info(f"Epoch {epoch}: Average loss={epoch_loss:.4f}")
            
            is_better, val_metric_values = self.validate(
                model=self.model,
                val_dataloader=val_loader,
                metric_to_save=self.cfg.metrics_to_save,
                current_best_metric_to_save_value=global_best_metric_values[self.cfg.metrics_to_save],
            )

            if is_better:
                logger.info(f"New best model found at epoch {epoch}: {val_metric_values}")
                global_best_metric_values = val_metric_values

                # test
                final_test_metrics = self.evaluate_model(
                    model=self.model,
                    test_dataloader=test_loader,
                )
                logger.info(f"Test metrics at epoch {epoch}: {final_test_metrics}")

                # Save best model checkpoint
                if not os.path.exists(self.cfg.save_dir):
                    os.makedirs(self.cfg.save_dir, exist_ok=True)
                best_model_path = os.path.join(self.cfg.save_dir, f'checkpoint_best.pth')
                torch.save(self.model.state_dict(), best_model_path)
                
                # save best metrics
                best_metrics_path = os.path.join(self.cfg.save_dir, f'best_metrics.json')
                with open(best_metrics_path, 'w') as f:
                    json.dump({
                        "val_metrics": val_metric_values,
                        "test_metrics": final_test_metrics,
                    }, f, indent=4)
                
                # save config
                config_path = os.path.join(self.cfg.save_dir, f'train_config.json')
                with open(config_path, 'w') as f:
                    json.dump(OmegaConf.to_container(self.cfg), f, indent=4)

                # 记录最佳 epoch
                best_epoch = epoch
                best_val_metrics = val_metric_values
                best_test_metrics = final_test_metrics

        # 返回统一格式
        return self._build_train_response(
            model_id=self.cfg.get("task_id", "patch_cls"),
            checkpoint_path=os.path.join(self.cfg.save_dir, 'checkpoint_best.pth'),
            loss_history=history["epoch loss"],
            lr_history=history.get("lr", []),
            val_metrics=best_val_metrics if 'best_val_metrics' in dir() else None,
            test_metrics=best_test_metrics if 'best_test_metrics' in dir() else None,
            best_epoch=best_epoch if 'best_epoch' in dir() else None,
        )

    def _build_train_response(
        self,
        model_id: str,
        checkpoint_path: str,
        loss_history: list,
        lr_history: Optional[list] = None,
        val_metrics: Optional[Dict[str, float]] = None,
        test_metrics: Optional[Dict[str, float]] = None,
        best_epoch: Optional[int] = None,
    ) -> TrainResponse:
        """构建统一的训练响应"""
        metrics = TrainMetrics(
            loss_history=loss_history,
            lr_history=lr_history or [],
            val_metrics=val_metrics,
            test_metrics=test_metrics,
            best_epoch=best_epoch,
        )
        return TrainResponse.success(
            task_id=self.cfg.get("task_id", model_id),
            task_type=self.task_type,
            model_id=model_id,
            checkpoint_path=checkpoint_path,
            metrics=metrics,
        )

