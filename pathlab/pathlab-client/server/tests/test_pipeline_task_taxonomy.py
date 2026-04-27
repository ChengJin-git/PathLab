from gateway import pipeline


def test_training_pipeline_task_family_accepts_canonical_task_ids():
    assert pipeline._training_task_family("wsi_survival") == "survival"
    assert pipeline._training_task_family("patch_segmentation") == "segmentation"
    assert pipeline._training_task_family("patch_classification") == "classification"
    assert pipeline._training_task_family("wsi_classification") == "classification"


def test_training_pipeline_task_family_raises_on_legacy_values():
    import pytest
    with pytest.raises(ValueError, match="unknown canonical task id: survival"):
        pipeline._training_task_family("survival")
    with pytest.raises(ValueError, match="unknown canonical task id: segmentation"):
        pipeline._training_task_family("segmentation")
    with pytest.raises(ValueError, match="unknown canonical task id: classification"):
        pipeline._training_task_family("classification")
