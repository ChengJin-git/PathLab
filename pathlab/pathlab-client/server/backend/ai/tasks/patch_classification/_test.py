import sys
import json
import logging

sys.path.append("/storage/jmabq/PathLab/pathlab/pathlab-client/server")
from backend.ai.tasks.patch_classification.trainer import PatchClassificationTrainer


cfg_file_path = '/storage/jmabq/PathLab/pathlab/pathlab-client/server/backend/ai/tasks/patch_classification/default_config.json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


with open(cfg_file_path, 'r') as f:
    config = json.load(f)
trainer = PatchClassificationTrainer(config)
trainer.train_model(None)
