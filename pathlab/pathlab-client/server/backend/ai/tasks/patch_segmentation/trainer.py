"""WSI Classification Trainer - integrates feature extraction and ABMIL training."""

import os
import json
import torch
from omegaconf import OmegaConf
import logging
from functools import partial

from backend.ai.segmentors import get_segmentor
from backend.ai.utils.data_splitter import segmentation_data_splitter
from backend.ai.utils.segmentation_dataset import SegmentationDataset
from backend.ai.segmentors.tools.transforms import (
    make_segmentation_train_transforms,
    make_segmentation_eval_transforms,
)
from backend.ai.segmentors.tools.schedulers import build_scheduler
from backend.ai.segmentors.tools.loss import MultiSegmentationLoss
from backend.ai.segmentors.tools.metrics import calculate_segmentation_metrics, calculate_intersect_and_union, SEGMENTATION_METRICS
from backend.ai.segmentors.tools.inference import make_inference

logger = logging.getLogger("segmentation_trainer")


class SegmentationTrainer():
    """
    Trainer for WSI-level segmentation tasks.
    """

    def __init__(
        self,
        config,
    ):
        """ """
        self.cfg = OmegaConf.create(config)
        self.device = torch.device(self.cfg.device)

        if self.cfg.dataset.single_annotation_path is not None:
            self.train_annots_path, self.val_annots_path, self.test_annots_path = (
                segmentation_data_splitter(
                    annotations_full_path=self.cfg.dataset.single_annotation_path,
                    train_ratio=self.cfg.dataset.train,
                    val_ratio=self.cfg.dataset.val,
                    test_ratio=self.cfg.dataset.test,
                )
            )
        else:
            self.train_annots_path = self.cfg.dataset.train_annotation_path
            self.val_annots_path = self.cfg.dataset.val_annotation_path
            self.test_annots_path = self.cfg.dataset.test_annotation_path
        
        self.train_dataset = self.build_dataset(mode="train")
        self.val_dataset = self.build_dataset(mode="val")
        self.test_dataset = self.build_dataset(mode="test")

        self.model = get_segmentor(
            name=self.cfg.model.backbone,
            num_classes=self.train_dataset.total_categories+1,
            backbone=self.cfg.model.backbone,
            backbone_out_layers=self.cfg.model.backbone_out_layers,
            hf_token=self.cfg.model.get("hf_token", ""),
        ).to(self.device)

    def build_dataset(self, mode):
        """
        kwargs are passed to DataLoader
        """
        if mode == "train":
            annotations_path = self.train_annots_path
            data_transforms = make_segmentation_train_transforms(
                **self.cfg.transforms.train
            )
        elif mode == "val":
            annotations_path = self.val_annots_path
            data_transforms = make_segmentation_eval_transforms(
                **self.cfg.transforms.eval
            )
        elif mode == "test":
            annotations_path = self.test_annots_path
            data_transforms = make_segmentation_eval_transforms(
                **self.cfg.transforms.eval
            )
        else:
            raise ValueError(f"Unknown mode: {mode}")

        dataset = SegmentationDataset(
            img_dir=self.cfg.dataset.image_root,
            annotations_path=annotations_path,
            transform=data_transforms,
        )
        return dataset

    def train_step(
        self, 
        segmentation_model: torch.nn.Module,
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
        pred = segmentation_model(batch_img)  # B x num_classes x h x w
        gt = torch.squeeze(gt).long()  # Adapt gt dimension to enable loss calculation

        # c) compute loss
        if gt.shape[-2:] != pred.shape[-2:]:
            pred = torch.nn.functional.interpolate(
                input=pred, size=gt.shape[-2:], mode="bilinear", align_corners=False
            )
        loss = criterion(pred, gt)

        # d) optimization
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            segmentation_model.parameters(), optimizer_gradient_clip
        )
        optimizer.step()

        if global_step > 0:  # inheritance from old mmcv code
            scheduler.step()

        return loss

    def evaluate_segmentation_model(
        self,
        segmentation_model: torch.nn.Module,
        test_dataloader,
        eval_res,
        eval_stride,
        num_classes,
        inference_mode,
    ):
        segmentation_model.eval()
        all_metric_values = []

        for batch_img, gt in test_dataloader:
            batch_img = [img.to(self.device) for img in batch_img]
            gt = gt.to(self.device)[0]
            
            aggregated_preds = torch.zeros(1, num_classes, gt.shape[-2], gt.shape[-1]).to(self.device)
            for img_idx, img in enumerate(batch_img):
                aggregated_preds += make_inference(
                    img,
                    segmentation_model,
                    inference_mode=inference_mode,
                    rescale_to=gt.shape[-2:],
                    n_output_channels=num_classes,
                    crop_size=(eval_res, eval_res),
                    stride=(eval_stride, eval_stride),
                    apply_horizontal_flip=(img_idx and img_idx >= len(batch_img) / 2),
                    output_activation=partial(torch.nn.functional.softmax, dim=1),
                )
            aggregated_preds = (aggregated_preds / len(batch_img)).argmax(dim=1, keepdim=True).to(self.device)
            intersect_and_union = calculate_intersect_and_union(
                aggregated_preds[0],
                gt,
                num_classes=num_classes,
                reduce_zero_label=True,
            )
            all_metric_values.append(intersect_and_union)
            del img, gt, aggregated_preds, intersect_and_union

        all_metric_values = torch.stack(all_metric_values)
 
        final_metrics = calculate_segmentation_metrics(
            all_metric_values,
            metrics=["mIoU", "dice", "fscore"],
        )
        final_metrics = {k: round(v.cpu().item() * 100, 2) for k, v in final_metrics.items()}
        return final_metrics

    def validate(
        self,
        segmentation_model: torch.nn.Module,
        val_dataloader,
        eval_res,
        eval_stride,
        num_classes,
        metric_to_save,
        current_best_metric_to_save_value,
        inference_mode='whole',
    ):
        new_metric_values_dict = self.evaluate_segmentation_model(
            segmentation_model,
            val_dataloader,
            eval_res,
            eval_stride,
            num_classes,
            inference_mode=inference_mode,
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
            self.val_dataset, batch_size=1, shuffle=False, num_workers=4
        )
        test_loader = torch.utils.data.DataLoader(
            self.test_dataset, batch_size=1, shuffle=False, num_workers=4
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

        criterion = MultiSegmentationLoss(
            diceloss_weight=self.cfg.train.diceloss_weight, celoss_weight=self.cfg.train.celoss_weight
        )
        
        # Training loop
        global_step = 0
        global_best_metric_values = {metric: 0.0 for metric in SEGMENTATION_METRICS}

        history = {"epoch loss": [], 'iter loss': []}

        for epoch in range(1, self.cfg.epochs + 1):
            epoch_loss = 0.0
            self.model.train()
            for batch in train_loader:
                loss = self.train_step(
                    segmentation_model=self.model,
                    batch=batch,
                    device=self.device,
                    optimizer=optimizer,
                    optimizer_gradient_clip=self.cfg.optimizer.gradient_clip,
                    scheduler=scheduler,
                    criterion=criterion,
                    global_step=global_step,
                )
                global_step += 1
                epoch_loss += loss.item()
                history["iter loss"].append(loss.item())
                logger.info(f"Epoch {epoch} Iteration {global_step}: loss={loss.item():.4f}")
            epoch_loss /= len(train_loader)
            history["epoch loss"].append(epoch_loss)
            logger.info(f"Epoch {epoch}: Average loss={epoch_loss:.4f}")
            
            is_better, val_metric_values = self.validate(
                segmentation_model=self.model,
                val_dataloader=val_loader,
                eval_res=self.cfg.eval.crop_size,
                eval_stride=self.cfg.eval.stride,
                num_classes=self.train_dataset.total_categories+1,
                metric_to_save=self.cfg.eval.metric_to_save,
                current_best_metric_to_save_value=global_best_metric_values[self.cfg.eval.metric_to_save],
            )

            if is_better:
                logger.info(f"New best model found at epoch {epoch}: {val_metric_values}")
                global_best_metric_values = val_metric_values

                # test
                final_test_metrics = self.evaluate_segmentation_model(
                    segmentation_model=self.model,
                    test_dataloader=test_loader,
                    eval_res=self.cfg.eval.crop_size,
                    eval_stride=self.cfg.eval.stride,
                    num_classes=self.train_dataset.total_categories+1,
                    inference_mode=self.cfg.eval.mode,
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

        return {
            "history": history,
        }

