"""End-to-end detector training, validation checkpoint selection and restart recovery."""

import json
import random
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from backend.ai.cancellation import is_task_cancelled, TrainingCancelledException
from backend.ai.detectors.models import build_detector
from backend.ai.detectors.specs import DetectionConfig
from backend.ai.utils.detection_dataset import DetectionDataset, collate_detection
from backend.services.result_analysis.detection_metrics import evaluate_detection


class DetectionTrainer:
    def __init__(
        self,
        task_id,
        config,
        dataset,
        classes,
        save_dir,
        device=None,
        seed=42,
        hf_token="",
    ):
        self.task_id = task_id
        self.config = DetectionConfig.model_validate(config)
        self.classes = classes
        self.directory = Path(save_dir)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        torch.manual_seed(seed)
        random.seed(seed)
        np.random.seed(seed)
        self.model = build_detector(self.config, classes, hf_token=hf_token).to(
            self.device
        )
        self.loaders = {}
        for split in ("train", "val", "test"):
            data = DetectionDataset(
                **dataset[split], classes=classes, augment=split == "train"
            )
            if not len(data) and split != "test":
                raise ValueError(f"Detection requires a nonempty {split} split")
            self.loaders[split] = DataLoader(
                data,
                batch_size=self.config.batch_size,
                shuffle=split == "train",
                collate_fn=collate_detection,
            )

    def check_cancelled(self):
        from backend.ai.permission_revocation import (
            is_permission_revoked,
            PermissionRevokedException,
        )

        if is_permission_revoked(self.task_id):
            raise PermissionRevokedException(f"Permission revoked: {self.task_id}")
        if is_task_cancelled(self.task_id):
            raise TrainingCancelledException(
                f"Detection training cancelled: {self.task_id}"
            )

    def evaluate(self, split):
        self.model.eval()
        samples = []
        with torch.inference_mode():
            for images, targets in self.loaders[split]:
                self.check_cancelled()
                outputs = self.model([image.to(self.device) for image in images])
                for output, target in zip(outputs, targets):
                    # One-stage detectors reserve label 0 for background too.
                    keep = output["labels"] > 0
                    samples.append(
                        {
                            "prediction": {
                                k: output[k][keep].cpu().tolist()
                                for k in ("boxes", "labels", "scores")
                            },
                            "target": {
                                k: target[k].tolist()
                                for k in ("boxes", "labels", "iscrowd")
                            },
                        }
                    )
        return evaluate_detection(
            samples, self.classes, max_detections=self.config.max_detections
        )[0]

    def train(self, progress):
        cfg = self.config
        optimizers = {
            "adam": torch.optim.Adam,
            "adamw": torch.optim.AdamW,
            "sgd": torch.optim.SGD,
        }
        optimizer = optimizers[cfg.optimizer](
            (p for p in self.model.parameters() if p.requires_grad),
            lr=cfg.learning_rate,
            weight_decay=cfg.weight_decay,
        )
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, cfg.epochs)
        history = {"train_loss": [], "val_metrics": [], "learning_rates": []}
        best, best_epoch, start, best_metrics = -1.0, 0, 0, {}
        resume_path = self.directory / "resume_checkpoint.pth"
        if resume_path.exists():
            state = torch.load(resume_path, map_location=self.device, weights_only=True)
            if state["config"] != cfg.model_dump() or state["classes"] != self.classes:
                raise ValueError(
                    "Detection resume checkpoint configuration differs from task"
                )
            self.model.load_state_dict(state["model_state_dict"])
            optimizer.load_state_dict(state["optimizer"])
            scheduler.load_state_dict(state["scheduler"])
            start, best, best_epoch = state["epoch"], state["best"], state["best_epoch"]
            history, best_metrics = state["history"], state["best_metrics"]
            torch.set_rng_state(state["rng"].cpu())
            if torch.cuda.is_available() and state.get("cuda_rng"):
                torch.cuda.set_rng_state_all(
                    [value.cpu() for value in state["cuda_rng"]]
                )
        for epoch in range(start, cfg.epochs):
            self.check_cancelled()
            self.model.train()
            total = 0.0
            for images, targets in self.loaders["train"]:
                self.check_cancelled()
                images = [image.to(self.device) for image in images]
                # Crowd regions are ignored for training and evaluated by COCO crowd rules.
                targets = [
                    {
                        k: v[t["iscrowd"] == 0].to(self.device)
                        for k, v in t.items()
                        if k in ("boxes", "labels")
                    }
                    for t in targets
                ]
                optimizer.zero_grad(set_to_none=True)
                loss = sum(self.model(images, targets).values())
                if not torch.isfinite(loss):
                    raise ValueError("Non-finite detection training loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                total += float(loss.detach())
            metrics = self.evaluate("val")
            score = metrics.get("map")
            if score is None:
                raise ValueError(
                    "Validation split needs non-crowd detection ground truth for checkpoint selection"
                )
            history["train_loss"].append(total / len(self.loaders["train"]))
            history["val_metrics"].append(metrics)
            history["learning_rates"].append(optimizer.param_groups[0]["lr"])
            scheduler.step()
            checkpoint = dict(
                config=cfg.model_dump(),
                classes=self.classes,
                model_state_dict=self.model.state_dict(),
            )
            if score > best:
                best, best_epoch, best_metrics = score, epoch + 1, metrics
                torch.save(checkpoint, self.directory / "best_model.pth")
            checkpoint.update(
                optimizer=optimizer.state_dict(),
                scheduler=scheduler.state_dict(),
                epoch=epoch + 1,
                best=best,
                best_epoch=best_epoch,
                best_metrics=best_metrics,
                history=history,
                rng=torch.get_rng_state(),
                cuda_rng=(
                    torch.cuda.get_rng_state_all() if torch.cuda.is_available() else []
                ),
            )
            temp = resume_path.with_suffix(".tmp")
            torch.save(checkpoint, temp)
            temp.replace(resume_path)
            progress(epoch + 1, history["train_loss"][-1], metrics)
            if epoch + 1 - best_epoch >= cfg.early_stopping_patience:
                break
        self.model.load_state_dict(
            torch.load(
                self.directory / "best_model.pth",
                map_location=self.device,
                weights_only=True,
            )["model_state_dict"]
        )
        result = dict(
            history=history,
            best_epoch=best_epoch,
            best_val_metrics=best_metrics,
            test_metrics=(
                self.evaluate("test") if len(self.loaders["test"].dataset) else None
            ),
        )
        (self.directory / "metrics.json").write_text(
            json.dumps(result, allow_nan=False)
        )
        (self.directory / "config.json").write_text(
            json.dumps(
                {
                    **cfg.model_dump(),
                    "classes": self.classes,
                    "task_type": "patch_detection",
                }
            )
        )
        resume_path.unlink(missing_ok=True)
        return result

    def release_resources(self):
        self.model = None
        self.loaders.clear()
