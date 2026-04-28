from importlib import import_module
from pathlib import Path
from typing import Protocol, cast

import pytest
from pydantic import ValidationError


class _TaskTaxonomyModule(Protocol):
    class TaskMetadata(Protocol):
        task_family: str
        data_type: str
        allowed_aggregation_levels: tuple[str, ...]
        label: str

    CANONICAL_TASK_IDS: tuple[str, ...]
    TASK_METADATA_BY_ID: dict[str, TaskMetadata]

    def is_canonical_task_type(self, task_type: object) -> bool: ...

    def is_classification_task(self, task_id: object) -> bool: ...

    def is_survival_task(self, task_id: object) -> bool: ...

    def is_segmentation_task(self, task_id: object) -> bool: ...

    def normalize_task_type(
        self,
        *,
        task_type: object,
        data_type: str | None = None,
        aggregation_level: str = "file",
    ) -> str: ...

    def get_task_metadata(self, task_id: object) -> TaskMetadata: ...

    def get_canonical_id_tuple(
        self,
        *,
        task_type: object,
        data_type: str | None = None,
        aggregation_level: str = "file",
    ) -> tuple[str, TaskMetadata]: ...

    def validate_task_axes(
        self,
        *,
        task_type: object,
        data_type: str,
        aggregation_level: str = "file",
    ) -> None: ...


taxonomy = cast(_TaskTaxonomyModule, cast(object, import_module("backend.ai.task_taxonomy")))


gateway_models = import_module("gateway.models")
gateway_utils = import_module("gateway.utils")


def test_canonical_task_ids_are_exactly_four_string_ids():
    expected_ids = {
        "wsi_classification",
        "patch_classification",
        "wsi_survival",
        "patch_segmentation",
    }
    assert set(taxonomy.CANONICAL_TASK_IDS) == expected_ids
    assert len(taxonomy.CANONICAL_TASK_IDS) == 4


def test_task_metadata_tracks_axes_separately():
    metadata = taxonomy.TASK_METADATA_BY_ID

    assert metadata["wsi_classification"].task_family == "classification"
    assert metadata["wsi_classification"].data_type == "wsi"
    assert metadata["wsi_classification"].allowed_aggregation_levels == ("file", "case")
    assert metadata["wsi_classification"].label == "WSI Classification"

    assert metadata["patch_segmentation"].task_family == "segmentation"
    assert metadata["patch_segmentation"].data_type == "patch"
    assert metadata["patch_segmentation"].allowed_aggregation_levels == ("file",)
    assert metadata["patch_segmentation"].label == "Patch Segmentation"


def test_task_metadata_has_all_required_labels():
    labels_by_id = {
        task_id: metadata.label for task_id, metadata in taxonomy.TASK_METADATA_BY_ID.items()
    }
    assert labels_by_id == {
        "wsi_classification": "WSI Classification",
        "patch_classification": "Patch Classification",
        "wsi_survival": "WSI Survival",
        "patch_segmentation": "Patch Segmentation",
    }


def test_task_metadata_is_frozen_dataclass_style():
    metadata = taxonomy.get_task_metadata("wsi_classification")

    with pytest.raises(AttributeError):
        setattr(metadata, "task_family", "changed")


@pytest.mark.parametrize(
    ("task_type", "data_type", "expected"),
    [
        ("wsi_classification", "wsi", "wsi_classification"),
        ("patch_classification", "patch", "patch_classification"),
        ("wsi_survival", "wsi", "wsi_survival"),
        ("patch_segmentation", "patch", "patch_segmentation"),
    ],
)
def test_canonical_task_type_normalizes_to_itself(
    task_type: str,
    data_type: str,
    expected: str,
):
    assert taxonomy.normalize_task_type(task_type=task_type, data_type=data_type) == expected


@pytest.mark.parametrize("canonical_id", ["wsi_classification", "wsi_survival"])
@pytest.mark.parametrize("aggregation_level", ["file", "case"])
def test_allowed_aggregation_levels_keep_canonical_task_id(
    canonical_id: str,
    aggregation_level: str,
):
    assert (
        taxonomy.normalize_task_type(
            task_type=canonical_id,
            data_type="wsi",
            aggregation_level=aggregation_level,
        )
        == canonical_id
    )


def test_is_canonical_task_type_accepts_only_canonical_ids():
    assert taxonomy.is_canonical_task_type("wsi_classification")
    assert taxonomy.is_canonical_task_type("wsi_survival")
    assert not taxonomy.is_canonical_task_type("classification")
    assert not taxonomy.is_canonical_task_type("patch_survival")


def test_feature_dataset_call_sites_do_not_use_legacy_task_type_keyword():
    server_root = Path(__file__).resolve().parents[1]
    paths = [
        server_root / "backend/ai/tasks/wsi_classification/trainer.py",
        server_root / "backend/ai/tasks/wsi_survival/trainer.py",
        server_root / "gateway/routes/inference_wsi_classification.py",
        server_root / "gateway/routes/inference_wsi_survival.py",
        server_root / "gateway/routes/inference_external_validation.py",
    ]

    leaked_lines = []
    for path in paths:
        for line_number, line in enumerate(path.read_text().splitlines(), start=1):
            if 'task_type="classification"' in line or 'task_type="survival"' in line:
                leaked_lines.append(f"{path.relative_to(server_root)}:{line_number}: {line.strip()}")

    assert leaked_lines == []


def test_canonical_id_tuple_and_metadata_lookup():
    canonical_id, metadata = taxonomy.get_canonical_id_tuple(
        task_type="patch_classification",
        data_type="patch",
        aggregation_level="file",
    )
    assert canonical_id == "patch_classification"
    assert metadata == taxonomy.get_task_metadata("patch_classification")
    assert metadata.task_family == "classification"
    assert metadata.data_type == "patch"
    assert metadata.allowed_aggregation_levels == ("file",)


@pytest.mark.parametrize(
    ("task_type", "data_type", "aggregation_level", "message_fragment"),
    [
        ("wsi_survival", "patch", "file", "unsupported task/data_type combination"),
        (
            "patch_segmentation",
            "wsi",
            "file",
            "unsupported task/data_type combination",
        ),
        (
            "patch_classification",
            "patch",
            "case",
            "unsupported aggregation_level",
        ),
        (
            "patch_segmentation",
            "patch",
            "case",
            "unsupported aggregation_level",
        ),
        ("wsi_classification", "wsi", "slide", "aggregation_level must be one of"),
    ],
)
def test_invalid_axis_combinations_raise_clear_errors(
    task_type: str,
    data_type: str,
    aggregation_level: str,
    message_fragment: str,
):
    with pytest.raises(ValueError, match=message_fragment):
        taxonomy.validate_task_axes(
            task_type=task_type,
            data_type=data_type,
            aggregation_level=aggregation_level,
        )


def test_training_task_request_normalizes_wsi_classification_to_canonical_id():
    request = gateway_models.TrainingTaskRequest(
        task_name="wsi cls",
        task_type="wsi_classification",
        data_type="wsi",
        preprocessing={"tile_size": 224},
        model={"architecture": "resnet18"},
    )

    assert request.task_type == "wsi_classification"
    assert request.data_type == "wsi"


def test_training_task_request_rejects_legacy_classification_task_type():
    with pytest.raises(ValidationError, match="task_type must be one of"):
        gateway_models.TrainingTaskRequest(
            task_name="legacy cls",
            task_type="classification",
            data_type="wsi",
            preprocessing={"tile_size": 224},
            model={"architecture": "resnet18"},
        )


@pytest.mark.parametrize(
    ("request_cls_name", "task_type", "expected"),
    [
        ("DatasetUpdateTypeRequest", "patch_segmentation", "patch_segmentation"),
        ("DatasetUpdateTypeRequest", "wsi_survival", "wsi_survival"),
        ("AnnotationExtractRequest", "patch_classification", "patch_classification"),
        ("AnnotationExtractRequest", "patch_segmentation", "patch_segmentation"),
    ],
)
def test_task_only_request_models_accept_canonical_values(
    request_cls_name: str,
    task_type: str,
    expected: str,
):
    request_cls = getattr(gateway_models, request_cls_name)
    kwargs = {"task_type": task_type}
    if request_cls_name == "AnnotationExtractRequest":
        kwargs["dataset_name"] = "anno"
    request = request_cls(**kwargs)
    assert request.task_type == expected


def test_task_only_request_models_reject_ambiguous_classification():
    with pytest.raises(ValidationError, match="task_type must be one of"):
        gateway_models.DatasetUpdateTypeRequest(task_type="classification")


def test_annotation_extract_request_rejects_wsi_classification():
    with pytest.raises(ValidationError, match="Annotation extraction creates patch datasets"):
        gateway_models.AnnotationExtractRequest(
            dataset_name="roi patches",
            task_type="wsi_classification",
        )


def test_start_batch_import_rejects_invalid_aggregation():
    with pytest.raises(
        ValidationError, match="unsupported aggregation_level"
    ):
        gateway_models.StartBatchImportRequest(
            task_type="patch_segmentation",
            aggregation_level="case",
        )


def test_batch_register_normalizes_classification_from_file_data_type():
    request = gateway_models.BatchRegisterRequest(
        task_type="patch_classification",
        files=[
            gateway_models.BatchRegisterFileInfo(
                path="/tmp/a.png",
                data_type="patch",
            )
        ],
    )

    assert request.task_type == "patch_classification"


def test_batch_register_request_rejects_legacy_classification_task_type():
    with pytest.raises(ValidationError, match="task_type must be one of"):
        gateway_models.BatchRegisterRequest(
            task_type="classification",
            files=[
                gateway_models.BatchRegisterFileInfo(
                    path="/tmp/a.svs",
                    data_type="wsi",
                )
            ],
        )


def test_base_dataset_request_normalizes_segmentation():
    request = gateway_models.BaseDatasetRequest(
        task_type="patch_segmentation",
        aggregation_level="file",
    )
    assert request.task_type == "patch_segmentation"


def test_base_dataset_request_defaults_to_canonical_wsi_classification():
    request = gateway_models.BaseDatasetRequest()

    assert request.task_type == "wsi_classification"


def test_base_dataset_request_rejects_legacy_classification_task_type():
    with pytest.raises(ValidationError, match="task_type must be one of"):
        gateway_models.BaseDatasetRequest(task_type="classification")


def test_start_batch_import_rejects_legacy_classification_task_type():
    with pytest.raises(ValidationError, match="task_type must be one of"):
        gateway_models.StartBatchImportRequest(
            task_type="classification",
            aggregation_level="file",
            files=[
                gateway_models.BatchRegisterFileInfo(
                    path="/tmp/a.svs",
                    data_type="wsi",
                )
            ],
        )


@pytest.mark.parametrize(
    ("task_type", "expected_label"),
    [
        ("wsi_classification", "WSI Classification"),
        ("patch_classification", "Patch Classification"),
        ("wsi_survival", "WSI Survival"),
        ("patch_segmentation", "Patch Segmentation"),
    ],
)
def test_task_metadata_label_matches_canonical_id(task_type: str, expected_label: str):
    metadata = taxonomy.get_task_metadata(task_type)
    assert metadata.label == expected_label


def test_segmentation_task_type_constant_is_canonical():
    assert gateway_utils.SEGMENTATION_TASK_TYPE == "patch_segmentation"


def test_normalize_task_type_requires_data_type_for_non_canonical():
    with pytest.raises(ValueError, match="task_type must be one of"):
        taxonomy.normalize_task_type(task_type="classification")


@pytest.mark.parametrize(
    ("task_id", "expected_family"),
    [
        ("wsi_classification", "classification"),
        ("patch_classification", "classification"),
        ("wsi_survival", "survival"),
        ("patch_segmentation", "segmentation"),
    ],
)
def test_is_family_helpers_for_canonical_ids(task_id: str, expected_family: str):
    is_cls = taxonomy.is_classification_task(task_id)
    is_surv = taxonomy.is_survival_task(task_id)
    is_seg = taxonomy.is_segmentation_task(task_id)

    if expected_family == "classification":
        assert is_cls
        assert not is_surv
        assert not is_seg
    elif expected_family == "survival":
        assert not is_cls
        assert is_surv
        assert not is_seg
    else:
        assert not is_cls
        assert not is_surv
        assert is_seg


def test_is_classification_task_raises_on_legacy_value():
    with pytest.raises(ValueError, match="unknown canonical task id: classification"):
        taxonomy.is_classification_task("classification")


def test_is_survival_task_raises_on_legacy_value():
    with pytest.raises(ValueError, match="unknown canonical task id: survival"):
        taxonomy.is_survival_task("survival")


def test_is_segmentation_task_raises_on_legacy_value():
    with pytest.raises(ValueError, match="unknown canonical task id: segmentation"):
        taxonomy.is_segmentation_task("segmentation")


def test_segmentation_contract_ignores_legacy_segmentation_family():
    gateway_utils.ensure_segmentation_contract(
        "segmentation",
        "patch",
        "case",
        context="legacy segmentation probe",
    )
