# pyright: reportImplicitRelativeImport=false

from gateway.routes.external_validation_analysis import (
    ExtvalDatasetInfo,
    ExtvalModelInfo,
    check_extval_compatibility,
)


def test_extval_allows_wsi_dataset_with_different_cached_feature_dims():
    model_info = ExtvalModelInfo(
        data_type="wsi",
        task_type="wsi_classification",
        classes=["mutant", "wild-type"],
        feature_extractor="H-Optimus-0",
        wsi_ids=set(),
        source_dataset_id=None,
        seg_task_architecture="",
        seg_task_backbone="",
        seg_saved_architecture="",
        seg_saved_backbone="",
        segmentation_labels=[],
        training_dataset_ids=set(),
    )
    dataset_info = ExtvalDatasetInfo(
        dataset_id="brca-mut-pik3ca-cptac",
        data_type="wsi",
        task_type="wsi_classification",
        aggregation_level="file",
        labels=["wild-type", "mutant"],
        segmentation_labels=[],
        feature_extractors=["conch"],
        wsi_ids=set(),
    )

    assert check_extval_compatibility(model_info, dataset_info) is None
