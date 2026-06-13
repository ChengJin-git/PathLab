"""
Test script for PatchSegmentationTrainer.

This script tests the segmentation training pipeline using the SegPC dataset.
"""

import sys
import os
import logging
from pathlib import Path

# Add the project root to path for imports
# project_root = Path(__file__).resolve().parents[5]
# print(project_root)
sys.path.insert(0, '/storage/jmabq/PathLab/pathlab/pathlab-client/server')

import torch
from backend.ai.tasks.patch_segmentation.trainer import SegmentationTrainer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_trainer_initialization():
    """Test trainer initialization with default config."""
    logger.info("=" * 60)
    logger.info("Testing trainer initialization...")
    
    # Dataset paths from segmentation_dataset.py
    base_path = "/jhcnas6/Cytology/Public/SegPC/seg"
    
    config = {
        "architecture": "unet",
        "backbone": "resnet34",  # Use lighter backbone for testing
        "dataset": {
            "classes": 2,  # SegPC has 2 classes (cytoplasm, nucleus)
            "channels": 3,
            "train": {
                "image_dir": f"{base_path}/train",
                "annotations_path": f"{base_path}/train.json",
            },
            "val": {
                "image_dir": f"{base_path}/val",
                "annotations_path": f"{base_path}/val.json",
            },
            "test": {
                "image_dir": f"{base_path}/test",
                "annotations_path": f"{base_path}/test.json",
            },
        },
        "training": {
            "epochs": 5,  # Small number for testing
            "lr": 1e-4,
            "early_stopping_patience": 3,
            "use_amp": True,
            "gradient_accumulation_steps": 1,
        },
        "save_dir": "./test_checkpoints",
    }
    
    trainer = SegmentationTrainer(
        task_id="test_task_001",
        uploads_root=Path("./uploads"),
        device="cuda" if torch.cuda.is_available() else "cpu",
        batch_size=8,
        config=config,
    )
    
    logger.info(f"Trainer initialized successfully!")
    logger.info(f"Device: {trainer.device}")
    logger.info(f"Model architecture: {trainer.config['architecture']}")
    logger.info(f"Backbone: {trainer.config['backbone']}")
    logger.info(f"Number of classes: {trainer.config['dataset']['classes']}")
    logger.info(f"Train dataset size: {len(trainer.train_dataset)}")
    logger.info(f"Val dataset size: {len(trainer.val_dataset)}")
    if trainer.test_dataset:
        logger.info(f"Test dataset size: {len(trainer.test_dataset)}")
    
    return trainer


def test_data_loading(trainer: SegmentationTrainer):
    """Test data loading and batch creation."""
    logger.info("=" * 60)
    logger.info("Testing data loading...")
    
    train_loader, val_loader, test_loader = trainer.build_loaders()
    
    # Get a sample batch
    images, masks = next(iter(train_loader))
    
    logger.info(f"Batch images shape: {images.shape}")
    logger.info(f"Batch masks shape: {masks.shape}")
    logger.info(f"Images dtype: {images.dtype}, range: [{images.min():.3f}, {images.max():.3f}]")
    logger.info(f"Masks dtype: {masks.dtype}, unique values: {torch.unique(masks)}")
    
    return train_loader, val_loader, test_loader


def test_model_forward(trainer: SegmentationTrainer, train_loader):
    """Test model forward pass."""
    logger.info("=" * 60)
    logger.info("Testing model forward pass...")
    
    images, masks = next(iter(train_loader))
    images = images.to(trainer.device)
    masks = masks.to(trainer.device)
    
    trainer.model.eval()
    with torch.no_grad():
        outputs = trainer.model(images)
    
    logger.info(f"Input shape: {images.shape}")
    logger.info(f"Output shape: {outputs.shape}")
    logger.info(f"Output range: [{outputs.min():.3f}, {outputs.max():.3f}]")
    
    # Test loss computation
    loss = trainer.loss_fn(outputs, masks)
    logger.info(f"Loss value: {loss.item():.4f}")
    
    return outputs


def test_metrics_computation(trainer: SegmentationTrainer, train_loader):
    """Test metrics computation."""
    logger.info("=" * 60)
    logger.info("Testing metrics computation...")
    
    images, masks = next(iter(train_loader))
    images = images.to(trainer.device)
    
    trainer.model.eval()
    with torch.no_grad():
        outputs = trainer.model(images)
    
    # Compute metrics
    metrics = trainer._compute_metrics(outputs.cpu(), masks)
    
    logger.info("Computed metrics:")
    for name, value in metrics.items():
        if isinstance(value, list):
            for i, v in enumerate(value):
                print(v)
        else:
            logger.info(f"  {name}: {value:.4f}")
    
    return metrics


def test_single_epoch_training(trainer: SegmentationTrainer):
    """Test a single epoch of training."""
    logger.info("=" * 60)
    logger.info("Testing single epoch training...")
    
    train_loader, val_loader, _ = trainer.build_loaders()
    
    # Build optimizer and scheduler
    optimizer = trainer._build_optimizer(trainer.model)
    scheduler = trainer._build_scheduler(optimizer, train_loader)
    
    # Create scaler for AMP
    use_amp = trainer.config.get("training", {}).get("use_amp", True) and trainer.device != "cpu"
    scaler = torch.cuda.amp.GradScaler() if use_amp else None
    
    # Train one epoch
    train_loss, train_metrics = trainer._train_one_epoch(
        trainer.model, train_loader, optimizer, scheduler, scaler, epoch=1
    )
    
    logger.info(f"Training loss: {train_loss:.4f}")
    logger.info(f"Training IoU: {train_metrics.get('iou', 0):.4f}")
    logger.info(f"Training Dice: {train_metrics.get('dice', 0):.4f}")
    
    # Validate
    val_loss, val_metrics = trainer._validate(trainer.model, val_loader)
    
    logger.info(f"Validation loss: {val_loss:.4f}")
    logger.info(f"Validation IoU: {val_metrics.get('iou', 0):.4f}")
    logger.info(f"Validation Dice: {val_metrics.get('dice', 0):.4f}")
    
    return train_metrics, val_metrics


def test_full_training(trainer: SegmentationTrainer):
    """Test full training loop."""
    logger.info("=" * 60)
    logger.info("Testing full training loop...")
    logger.info("This may take a few minutes...")
    
    results = trainer.train_model()
    
    logger.info("\n" + "=" * 60)
    logger.info("Training Results Summary:")
    logger.info(f"Best epoch: {results['best_epoch']}")
    logger.info(f"Best validation IoU: {results['best_metric']:.4f}")
    logger.info(f"Total training time: {results['total_training_time']/60:.2f} minutes")
    
    if results.get('test_metrics'):
        logger.info("\nTest Metrics:")
        for name, value in results['test_metrics'].items():
            if isinstance(value, (int, float)):
                logger.info(f"  {name}: {value:.4f}")
    
    return results


def run_quick_test():
    """Run a quick test with minimal epochs."""
    logger.info("\n" + "=" * 80)
    logger.info("RUNNING QUICK TEST (2 epochs)")
    logger.info("=" * 80 + "\n")
    
    base_path = "/jhcnas6/Cytology/Public/SegPC/seg"
    
    config = {
        "architecture": "unet",
        "backbone": "resnet18",  # Lightest backbone for quick test
        "dataset": {
            "classes": 2,
            "channels": 3,
            "train": {
                "image_dir": f"{base_path}/train",
                "annotations_path": f"{base_path}/train.json",
            },
            "val": {
                "image_dir": f"{base_path}/val",
                "annotations_path": f"{base_path}/val.json",
            },
        },
        "training": {
            "epochs": 2,
            "lr": 1e-4,
            "early_stopping_patience": 5,
            "use_amp": True,
        },
        "save_dir": "./quick_test_checkpoints",
    }
    
    trainer = SegmentationTrainer(
        task_id="quick_test",
        uploads_root=Path("./uploads"),
        device="cuda" if torch.cuda.is_available() else "cpu",
        batch_size=4,
        config=config,
    )
    
    results = trainer.train_model()
    
    logger.info("\n" + "=" * 60)
    logger.info("Quick Test Completed!")
    logger.info(f"Final IoU: {results['best_metric']:.4f}")
    logger.info("=" * 60)
    
    return results


def run_all_tests():
    """Run all tests sequentially."""
    logger.info("\n" + "=" * 80)
    logger.info("RUNNING ALL TESTS FOR PatchSegmentationTrainer")
    logger.info("=" * 80 + "\n")
    
    try:
        # Test 1: Initialization
        trainer = test_trainer_initialization()
        
        # Test 2: Data loading
        train_loader, val_loader, test_loader = test_data_loading(trainer)
        
        # Test 3: Forward pass
        test_model_forward(trainer, train_loader)
        
        # Test 4: Metrics computation
        test_metrics_computation(trainer, train_loader)
        
        # Test 5: Single epoch training
        test_single_epoch_training(trainer)
        
        logger.info("\n" + "=" * 80)
        logger.info("ALL UNIT TESTS PASSED!")
        logger.info("=" * 80)
        
        # Optional: Full training test
        user_input = input("\nRun full training test? (y/n): ").strip().lower()
        if user_input == 'y':
            test_full_training(trainer)
        
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test PatchSegmentationTrainer")
    parser.add_argument(
        "--mode", 
        type=str, 
        default="quick",
        choices=["quick", "full", "all"],
        help="Test mode: 'quick' for 2-epoch test, 'full' for full training, 'all' for all unit tests"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
        help="Batch size for training"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=None,
        help="Number of epochs (overrides default)"
    )
    parser.add_argument(
        "--backbone",
        type=str,
        default="resnet34",
        help="Encoder backbone (e.g., resnet18, resnet34, resnet50)"
    )
    
    args = parser.parse_args()
    
    if args.mode == "quick":
        run_quick_test()
    elif args.mode == "all":
        run_all_tests()
    else:  # full
        logger.info("\n" + "=" * 80)
        logger.info("RUNNING FULL TRAINING TEST")
        logger.info("=" * 80 + "\n")
        
        base_path = "/jhcnas6/Cytology/Public/SegPC/seg"
        
        config = {
            "architecture": "unet",
            "backbone": args.backbone,
            "dataset": {
                "classes": 2,
                "channels": 3,
                "train": {
                    "image_dir": f"{base_path}/train",
                    "annotations_path": f"{base_path}/train.json",
                },
                "val": {
                    "image_dir": f"{base_path}/val",
                    "annotations_path": f"{base_path}/val.json",
                },
                "test": {
                    "image_dir": f"{base_path}/test",
                    "annotations_path": f"{base_path}/test.json",
                },
            },
            "training": {
                "epochs": args.epochs or 50,
                "lr": 1e-4,
                "early_stopping_patience": 10,
                "use_amp": True,
                "scheduler": "cosine_warm_restarts",
            },
            "save_dir": "./full_training_checkpoints",
        }
        
        trainer = SegmentationTrainer(
            task_id="full_training_test",
            uploads_root=Path("./uploads"),
            device="cuda" if torch.cuda.is_available() else "cpu",
            batch_size=args.batch_size,
            config=config,
        )
        
        results = test_full_training(trainer)
