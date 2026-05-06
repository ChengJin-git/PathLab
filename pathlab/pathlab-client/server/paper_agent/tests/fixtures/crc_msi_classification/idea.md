# Paper Intent

[TOPIC_CONTEXT]
{
  "disease": "colorectal cancer",
  "clinical_endpoint": "microsatellite instability status",
  "prediction_target": "MSI vs MSS",
  "modality": "H&E whole-slide images",
  "task_type": "wsi_classification",
  "method_family": "attention-based multiple instance learning",
  "classes": ["MSI", "MSS"],
  "confidence": "high",
  "sources": ["pre_training_chat_summary", "synthetic_crc_msi_fixture"]
}
[/TOPIC_CONTEXT]

## User Goal From Pre-training Chat
The user wanted to train a PathLab WSI classification model for colorectal cancer MSI status prediction from H&E whole-slide images and then generate a research-paper draft around the completed experiment.

## Writing Scope
- Emphasize computational pathology, MSI/MSS classification, WSI-level prediction, and attention-based MIL.
- Use PathLab locked evidence for cohort size, label distribution, split design, model configuration, metrics, and validation claims.
- Frame the experiment as an internal validation fixture unless external validation evidence is added.

## Unconfirmed / Avoid
- Do not claim multi-center, prospective, or external validation.
- Do not claim clinical deployment readiness.
- Do not claim survival or treatment-response prediction; the endpoint is MSI status classification.
