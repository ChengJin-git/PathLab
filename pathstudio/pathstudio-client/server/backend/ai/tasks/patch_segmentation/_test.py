import sys
import json
import logging

sys.path.append("/storage/jmabq/PathStudio/pathstudio/pathstudio-client/server")
from backend.ai.tasks.patch_segmentation.trainer import SegmentationTrainer


cfg_file_path = '/storage/jmabq/PathStudio/pathstudio/pathstudio-client/server/backend/ai/tasks/patch_segmentation/default_config.json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


with open(cfg_file_path, 'r') as f:
    config = json.load(f)
trainer = SegmentationTrainer(config)
trainer.train_model(None)
