"""Build a deterministic execution plan from data readiness + task profile.

Plan-2026-04-30 data-readiness Task 5: this module is the *source of truth*
for step ordering. ``requires_feature_extraction`` on the profile is just a
hint — the plan reflects what readiness actually found on disk.

Plan statuses:
- ``ready``              — execution can begin now (one or two concrete steps).
- ``needs_acquisition``  — local/prepared data missing, acquisition enabled and
                           not yet attempted; runner should invoke acquisition,
                           then re-run readiness.
- ``blocked``            — acquisition disabled or already exhausted; surface
                           ``missing`` for actionable guidance.
- ``stopped_after_acquisition`` — data is available, but the user explicitly
                           requested acquisition/data-prep only; no execution
                           steps should be sent to the code agent.

The builder NEVER emits placeholder paths like
``<feature_extraction.DATA_OUTPUT_DIR>/...``. Callers that expect raw WSI
two-step plans MUST pass concrete ``data_output_dir`` and
``generated_features_dir`` strings.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..dataset.readiness import DataReadinessResult
from ..dataset.types import TaskProfile
from ..domain.mil_selector import DEFAULT_MIL_MODEL, normalize_mil_model_name
from .external_contract import normalize_external_test_contract, update_external_dataset


@dataclass(frozen=True)
class ExecutionStep:
    id: str
    skill: str
    title: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionStep":
        return cls(
            id=str(data.get("id", "")),
            skill=str(data.get("skill", "")),
            title=str(data.get("title", "")),
            inputs=dict(data.get("inputs") or {}),
            outputs=dict(data.get("outputs") or {}),
            depends_on=list(data.get("depends_on") or []),
            instructions=list(data.get("instructions") or []),
        )


@dataclass(frozen=True)
class ExecutionPlan:
    status: str
    primary_skill: str = ""
    current_step: int = 0
    steps: list[ExecutionStep] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [s.to_dict() for s in self.steps]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ExecutionPlan":
        data = data or {}
        return cls(
            status=str(data.get("status", "blocked")),
            primary_skill=str(data.get("primary_skill", "")),
            current_step=int(data.get("current_step", 0) or 0),
            steps=[
                ExecutionStep.from_dict(s)
                for s in (data.get("steps") or [])
                if isinstance(s, dict)
            ],
            missing=list(data.get("missing") or []),
            notes=list(data.get("notes") or []),
        )


_FEATURE_CONSUMER_TASKS = {"mil_classification", "survival_analysis"}
_PATCH_READY_STATUSES = {"patch_features_ready", "patch_images_ready"}
DEFAULT_FEATURE_EXTRACTOR = "uni2"
_FEATURE_EXTRACTOR_ALIASES = {
    "UNI2": "uni2",
    "UNI": "uni",
    "CONCH": "conch",
    "CONCH15": "conch15",
    "CONCH 1.5": "conch15",
    "Virchow2": "virchow2",
    "Virchow": "virchow",
    "ResNet50": "resnet50",
}


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "ready"}


def normalize_feature_extractor_name(value: str = "") -> str:
    """Return the runtime registry key for a requested feature extractor."""
    name = str(value or "").strip()
    if not name:
        return DEFAULT_FEATURE_EXTRACTOR
    return _FEATURE_EXTRACTOR_ALIASES.get(
        name,
        _FEATURE_EXTRACTOR_ALIASES.get(name.upper(), name),
    )


def _features_ready_step(
    *,
    skill: str,
    readiness: DataReadinessResult,
    mil_model_name: str = DEFAULT_MIL_MODEL,
) -> ExecutionStep:
    inputs: dict[str, Any] = {
        "data_role": "internal",
        "features_dir": readiness.features_dir,
        "splits_file": readiness.splits_file,
    }
    instructions = [
        f"Set FEATURES_DIR={readiness.features_dir}",
        f"Set SPLITS_FILE={readiness.splits_file}",
        "Existing feature tensors detected; do not run feature_extraction.",
    ]
    if skill == "mil_classification":
        mil_model_name = normalize_mil_model_name(mil_model_name)
        inputs["mil_model_name"] = mil_model_name
        instructions.extend([
            f"Set PATHSCIENTIST_MIL_MODEL={mil_model_name}",
            "Model selection is frozen by the pre-execution contract; "
            "do not change the MIL architecture across iterations unless "
            "the user explicitly requests architecture exploration.",
        ])
    return ExecutionStep(
        id="train_downstream",
        skill=skill,
        title=f"Train {skill}",
        inputs=inputs,
        outputs={},
        depends_on=[],
        instructions=instructions,
    )


def _patch_ready_step(
    *,
    skill: str,
    readiness: DataReadinessResult,
    extractor_name: str = DEFAULT_FEATURE_EXTRACTOR,
) -> ExecutionStep:
    extractor_name = normalize_feature_extractor_name(extractor_name)
    inputs: dict[str, Any] = {
        "data_role": "internal",
        "data_dir": readiness.data_dir,
    }
    if readiness.features_dir:
        inputs["features_dir"] = readiness.features_dir
    if readiness.images_dir:
        inputs["images_dir"] = readiness.images_dir
    if readiness.splits_file:
        inputs["splits_file"] = readiness.splits_file

    instructions = [
        f"Set DATA_DIR={readiness.data_dir}",
        "This is patch-level classification; do not run slide-level WSI "
        "feature_extraction or MIL.",
    ]
    if readiness.images_dir:
        instructions.extend([
            f"Set PATHLAB_EXTRACTOR={extractor_name}",
            f"Use frozen patch encoder {extractor_name} for patch images before "
            "the classifier head.",
        ])
    if readiness.features_dir:
        instructions.append(
            "Existing patch feature tensors detected; train the patch "
            "classifier directly.",
        )
    if readiness.splits_file:
        instructions.append(f"Use SPLITS_FILE={readiness.splits_file}")

    return ExecutionStep(
        id="train_downstream",
        skill=skill,
        title=f"Train {skill}",
        inputs=inputs,
        outputs={},
        depends_on=[],
        instructions=instructions,
    )



def _label_inference_step(readiness: DataReadinessResult) -> ExecutionStep:
    manifest_file = ""
    if readiness.wsi_dir:
        root = readiness.wsi_dir.rstrip("/").rsplit("/", 1)[0]
        if root and root != readiness.wsi_dir:
            manifest_file = f"{root}/dataset_manifest.json"
    return ExecutionStep(
        id="infer_labels",
        skill="mil_classification",
        title="Infer dataset labels",
        inputs={
            "data_role": "internal",
            "wsi_dir": readiness.wsi_dir,
            "dataset_manifest_file": manifest_file,
            "label_inference_required": True,
        },
        outputs={
            "labels_file": readiness.labels_file,
            "splits_file": readiness.splits_file,
        },
        depends_on=[],
        instructions=[
            "Infer labels before any training or feature extraction metric run.",
            f"Inspect WSI_DIR={readiness.wsi_dir} and dataset_manifest_file={manifest_file}.",
            "Use registered PathLab metadata, dataset layout, filenames, manifests, "
            "and public deterministic metadata sources; do not invent labels.",
            f"Write labels.csv to {readiness.labels_file} with slide_id,label and optional case_id/split columns.",
            f"Write splits.json to {readiness.splits_file} with non-empty train/val/test and labels entries.",
            "Keep slide_id values exactly aligned with the mounted WSI filenames/manifest map.",
            "This is data setup, not a metric-bearing training iteration.",
        ],
    )


def _label_inference_plan(
    *,
    skill: str,
    readiness: DataReadinessResult,
    data_output_dir: str,
    generated_features_dir: str,
    extractor_name: str = DEFAULT_FEATURE_EXTRACTOR,
    mil_model_name: str = DEFAULT_MIL_MODEL,
) -> list[ExecutionStep]:
    infer = _label_inference_step(readiness)
    if readiness.features_dir:
        train = _features_ready_step(
            skill=skill,
            readiness=DataReadinessResult(
                status="features_ready",
                source=readiness.source,
                features_dir=readiness.features_dir,
                splits_file=readiness.splits_file,
                features_dir_host=readiness.features_dir_host,
                splits_file_host=readiness.splits_file_host,
            ),
            mil_model_name=mil_model_name,
        )
        train = ExecutionStep(
            id=train.id,
            skill=train.skill,
            title=train.title,
            inputs=dict(train.inputs),
            outputs=dict(train.outputs),
            depends_on=["infer_labels"],
            instructions=list(train.instructions) + [
                "Do not start training until infer_labels has written labels.csv and splits.json.",
            ],
        )
        return [infer, train]

    steps = _raw_wsi_two_step(
        skill=skill,
        readiness=DataReadinessResult(
            status="raw_wsi_ready",
            source=readiness.source,
            wsi_dir=readiness.wsi_dir,
            labels_file=readiness.labels_file,
            splits_file=readiness.splits_file,
            wsi_dir_host=readiness.wsi_dir_host,
            labels_file_host=readiness.labels_file_host,
            splits_file_host=readiness.splits_file_host,
        ),
        data_output_dir=data_output_dir,
        generated_features_dir=generated_features_dir,
        extractor_name=extractor_name,
        mil_model_name=mil_model_name,
    )
    steps[0] = ExecutionStep(
        id=steps[0].id,
        skill=steps[0].skill,
        title=steps[0].title,
        inputs=dict(steps[0].inputs),
        outputs=dict(steps[0].outputs),
        depends_on=["infer_labels"],
        instructions=list(steps[0].instructions) + [
            "Do not extract features until infer_labels has written labels.csv and splits.json.",
        ],
    )
    return [infer, *steps]


def _raw_wsi_two_step(
    *,
    skill: str,
    readiness: DataReadinessResult,
    data_output_dir: str,
    generated_features_dir: str,
    extractor_name: str = DEFAULT_FEATURE_EXTRACTOR,
    mil_model_name: str = DEFAULT_MIL_MODEL,
) -> list[ExecutionStep]:
    extractor_name = normalize_feature_extractor_name(extractor_name)
    mil_model_name = normalize_mil_model_name(mil_model_name)
    extract = ExecutionStep(
        id="extract_features",
        skill="feature_extraction",
        title="Extract WSI features",
        inputs={
            "data_role": "internal",
            "wsi_dir": readiness.wsi_dir,
            "data_output_dir": data_output_dir,
            "extractor_name": extractor_name,
            "script_path": "feature_extraction_launcher.sh",
            "script_type": "bash",
            "run_kind": "feature_extraction",
            "script_inputs": [
                "feature_extraction_launcher.sh",
                "feature_extraction_worker.py",
                "feature_extraction_aggregate.py",
            ],
        },
        outputs={"features_dir": generated_features_dir},
        depends_on=[],
        instructions=[
            f"Set DATA_OUTPUT_DIR={data_output_dir}",
            f"Set WSI_DIR={readiness.wsi_dir}",
            f"Set PATHSCIENTIST_FEATURE_EXTRACTOR={extractor_name}",
            f"Use extractor_name={extractor_name}; do not choose or substitute "
            "a different extractor unless explicitly requested.",
            f"Generated feature tensors will land at {generated_features_dir}.",
            "Execute feature extraction via run_experiment using "
            "script_path=feature_extraction_launcher.sh, script_type=bash, "
            "run_kind=feature_extraction, and the listed script_inputs.",
            "This is data setup, not a metric-bearing experiment iteration.",
        ],
    )
    train_inputs: dict[str, Any] = {
        "data_role": "internal",
        "features_dir": generated_features_dir,
        "splits_file": readiness.splits_file,
    }
    train_instructions = [
        f"Set FEATURES_DIR={generated_features_dir} (output of extract_features)",
        f"Set SPLITS_FILE={readiness.splits_file}",
        "Do not load this skill until feature_extraction has produced files.",
    ]
    if skill == "mil_classification":
        train_inputs["mil_model_name"] = mil_model_name
        train_instructions.extend([
            f"Set PATHSCIENTIST_MIL_MODEL={mil_model_name}",
            "Model selection is frozen by the pre-execution contract; "
            "do not change the MIL architecture across iterations unless "
            "the user explicitly requests architecture exploration.",
        ])
    train = ExecutionStep(
        id="train_downstream",
        skill=skill,
        title=f"Train {skill}",
        inputs=train_inputs,
        outputs={},
        depends_on=["extract_features"],
        instructions=train_instructions,
    )
    return [extract, train]


def _external_test_step(
    *,
    contract: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
) -> ExecutionStep:
    """Build an external evaluation step for a fixed model artifact."""
    inputs = normalize_external_test_contract(contract or {})
    return ExecutionStep(
        id="external_test",
        skill="external_test",
        title="Run external test",
        inputs=inputs,
        outputs={
            "metrics": "$OUTPUT_DIR/metrics.json",
            "predictions": "$OUTPUT_DIR/predictions.csv",
            "report": "$OUTPUT_DIR/external_test_report.json",
        },
        depends_on=list(depends_on or []),
        instructions=[
            "Load the external_test skill and run external_test.py.",
            "Do not train, fine-tune, or update model weights.",
            "Use run_experiment with run_kind=external_test.",
            "Run quick_check=true before the full external test.",
            "Write metrics to OUTPUT_DIR/metrics.json and predictions.csv.",
        ],
    )


def _external_feature_extraction_step(
    *,
    contract: dict[str, Any],
    depends_on: list[str],
    data_output_dir: str = "",
    extractor_name: str = DEFAULT_FEATURE_EXTRACTOR,
) -> tuple[ExecutionStep | None, dict[str, Any], list[str]]:
    """Build a role-tagged feature_extraction step for external raw WSIs."""
    inputs_contract = normalize_external_test_contract(contract or {})
    features_ready = _truthy_flag(inputs_contract.get("external_features_ready"))
    has_features = bool(str(inputs_contract.get("external_features_dir") or "").strip())
    has_wsi = bool(str(inputs_contract.get("external_wsi_dir") or "").strip())
    if has_features and features_ready:
        return None, inputs_contract, []
    if not has_wsi:
        return None, inputs_contract, ["external_wsi_dir_or_external_features_dir"]

    extractor_name = normalize_feature_extractor_name(
        str(inputs_contract.get("external_extractor_name") or extractor_name)
    )
    output_root = str(inputs_contract.get("external_data_output_dir") or "").strip()
    pathlab_root = str(inputs_contract.get("external_pathlab_uploads_dir") or "").strip()
    if not output_root and pathlab_root:
        output_root = pathlab_root
    if not output_root and data_output_dir:
        output_root = f"{str(data_output_dir).rstrip('/')}/external_validation"
    generated_dir = str(inputs_contract.get("external_generated_features_dir") or "").strip()
    if not generated_dir and pathlab_root:
        generated_dir = f"{pathlab_root.rstrip('/')}/features/{extractor_name}"
    elif not generated_dir and output_root:
        generated_dir = f"{output_root.rstrip('/')}/pt_files/{extractor_name}"
    if not output_root or not generated_dir:
        return None, inputs_contract, [
            "external_data_output_dir",
            "external_generated_features_dir",
        ]

    inputs_contract = update_external_dataset(
        inputs_contract,
        {
            "data_output_dir": output_root,
            "generated_features_dir": generated_dir,
            "features_dir": generated_dir,
        },
    )

    step = ExecutionStep(
        id="extract_external_features",
        skill="feature_extraction",
        title="Extract external WSI features",
        inputs={
            "data_role": "external",
            "wsi_dir": inputs_contract["external_wsi_dir"],
            "data_output_dir": output_root,
            "extractor_name": extractor_name,
            "script_path": "feature_extraction_launcher.sh",
            "script_type": "bash",
            "run_kind": "feature_extraction",
            "script_inputs": [
                "feature_extraction_launcher.sh",
                "feature_extraction_worker.py",
                "feature_extraction_aggregate.py",
            ],
        },
        outputs={"features_dir": generated_dir},
        depends_on=list(depends_on),
        instructions=[
            "Role: external validation data. Extract features for the external cohort only.",
            f"Set DATA_OUTPUT_DIR={output_root}",
            f"Set WSI_DIR={inputs_contract['external_wsi_dir']}",
            f"Set PATHSCIENTIST_FEATURE_EXTRACTOR={extractor_name}",
            "Use the same frozen extractor as the internal training feature space.",
            f"Generated external feature tensors will land at {generated_dir}.",
            "This is data setup for external validation, not training and not a metric-bearing iteration.",
        ],
    )
    return step, inputs_contract, []


_ACQUISITION_RETRY_STATES = {"none", "skipped"}
_ACQUISITION_EXHAUSTED_STATES = {"failed", "skipped_policy", "prepared"}


def _maybe_truncate_for_stop_after(
    plan: ExecutionPlan, stop_after_skill: str,
) -> ExecutionPlan:
    """When the user wants to stop after a specific skill (e.g.
    ``feature_extraction``), drop subsequent steps from the plan.

    2026-05-10 stop-after refactor (review of session_64561aa7962b): the
    user wrote "完成后开始 feature extraction，但不要开始训练". Pre-fix,
    grounding had no field for stop intent so the plan kept its full
    [feature_extraction, mil_classification] step list; the runner
    walked off the end of feature_extraction straight into 9 hours of
    MIL training. The truncation honors the explicit stop boundary
    while keeping ``primary_skill`` as the user's ultimate goal so
    brief / synthesis still reflect "what they originally wanted".

    No-op when ``stop_after_skill`` is empty, or names a skill that's
    not in the plan steps (don't drop steps for a typo).
    """
    if not stop_after_skill or not plan.steps:
        return plan
    skills = [s.skill for s in plan.steps]
    if stop_after_skill not in skills:
        return plan
    cut = skills.index(stop_after_skill) + 1
    if cut >= len(plan.steps):
        return plan  # Already the last step.
    truncated_steps = plan.steps[:cut]
    note = (
        f"User requested stop_after_skill={stop_after_skill!r}; "
        f"downstream steps dropped from this plan."
    )
    return ExecutionPlan(
        status=plan.status,
        primary_skill=plan.primary_skill,
        current_step=plan.current_step,
        steps=truncated_steps,
        missing=list(plan.missing),
        notes=list(plan.notes) + [note],
    )


def build_execution_plan(
    *,
    profile: TaskProfile,
    selected_skill: str,
    readiness: DataReadinessResult,
    allow_acquisition: bool = False,
    acquisition_status: str = "none",
    data_output_dir: str = "",
    generated_features_dir: str = "",
    extractor_name: str = DEFAULT_FEATURE_EXTRACTOR,
    mil_model_name: str = DEFAULT_MIL_MODEL,
    stop_after_skill: str = "",
    external_test_enabled: bool = False,
    external_test_contract: dict[str, Any] | None = None,
) -> ExecutionPlan:
    """Translate ``(profile, readiness, acquisition_status)`` into an actionable plan."""
    skill = (selected_skill or profile.preferred_skill or "").strip()
    primary_skill = skill or profile.task_type
    stop_after_skill = (stop_after_skill or "").strip()

    def _wrap(plan: ExecutionPlan) -> ExecutionPlan:
        # 2026-05-10 stop-after refactor: every return path goes through
        # this so a stop_after_skill request truncates the plan before
        # the runner sees it.
        return _maybe_truncate_for_stop_after(plan, stop_after_skill)

    def _with_external_test(plan: ExecutionPlan) -> ExecutionPlan:
        if not external_test_enabled:
            return plan
        if any(step.skill == "external_test" for step in plan.steps):
            return plan
        external_contract = normalize_external_test_contract(external_test_contract or {})
        external_extract_step, external_contract, external_missing = _external_feature_extraction_step(
            contract=external_contract,
            depends_on=[],
            data_output_dir=data_output_dir,
            extractor_name=extractor_name,
        )
        if external_missing:
            return ExecutionPlan(
                status="blocked",
                primary_skill=plan.primary_skill,
                current_step=plan.current_step,
                steps=[],
                missing=list(dict.fromkeys(list(plan.missing) + external_missing)),
                notes=list(plan.notes) + [
                    "External validation requested, but no ready external features "
                    "or raw external WSI path was found during preflight.",
                ],
            )

        steps = list(plan.steps)
        if external_extract_step is not None:
            insert_at = next(
                (
                    index
                    for index, step in enumerate(steps)
                    if step.skill != "feature_extraction"
                ),
                len(steps),
            )
            steps.insert(insert_at, external_extract_step)

        extraction_step_ids = [
            step.id for step in steps if step.skill == "feature_extraction"
        ]
        train_step_ids = [
            step.id for step in steps if step.id == "train_downstream"
        ]
        normalized_steps: list[ExecutionStep] = []
        for step in steps:
            depends_on = list(step.depends_on)
            if step.id == "train_downstream":
                depends_on = list(dict.fromkeys(depends_on + extraction_step_ids))
            normalized_steps.append(
                ExecutionStep(
                    id=step.id,
                    skill=step.skill,
                    title=step.title,
                    inputs=dict(step.inputs),
                    outputs=dict(step.outputs),
                    depends_on=depends_on,
                    instructions=list(step.instructions),
                )
            )

        test_depends_on = train_step_ids or (
            [normalized_steps[-1].id] if normalized_steps else []
        )
        normalized_steps.append(
            _external_test_step(
                contract=external_contract,
                depends_on=test_depends_on,
            )
        )
        return ExecutionPlan(
            status=plan.status,
            primary_skill=plan.primary_skill,
            current_step=plan.current_step,
            steps=normalized_steps,
            missing=list(plan.missing),
            notes=list(plan.notes) + [
                (
                    "External raw WSI requested; running external feature_extraction "
                    "before training, then external evaluation."
                    if external_extract_step is not None
                    else "External test requested; running evaluation after model-producing steps."
                ),
            ],
        )

    if (
        stop_after_skill == "acquisition"
        and (
            readiness.status != "missing_data"
            or acquisition_status not in _ACQUISITION_RETRY_STATES
        )
    ):
        notes = [
            "User requested stop_after_skill='acquisition'; "
            "data acquisition/preparation is the terminal boundary and "
            "feature_extraction/training steps are suppressed.",
        ]
        if readiness.status == "missing_data":
            notes.append(
                f"Acquisition ended with status={acquisition_status}; "
                "not requiring labels/splits/features because this is an "
                "acquisition-only request.",
            )
        return ExecutionPlan(
            status="stopped_after_acquisition",
            primary_skill=primary_skill,
            steps=[],
            missing=[],
            notes=notes,
        )

    if skill == "external_test" or profile.task_type == "external_test":
        external_contract = normalize_external_test_contract(external_test_contract or {})
        return _wrap(ExecutionPlan(
            status="ready",
            primary_skill="external_test",
            steps=[
                _external_test_step(contract=external_contract),
            ],
            notes=[
                "Standalone external_test requested; no training step will run.",
            ],
        ))

    if readiness.status in _PATCH_READY_STATUSES:
        return _wrap(_with_external_test(ExecutionPlan(
            status="ready",
            primary_skill=primary_skill,
            steps=[
                _patch_ready_step(
                    skill=skill,
                    readiness=readiness,
                    extractor_name=extractor_name,
                )
            ],
            notes=[
                "Patch-level data detected; running patch_classification directly.",
            ],
        )))

    if readiness.status == "features_ready":
        return _wrap(_with_external_test(ExecutionPlan(
            status="ready",
            primary_skill=primary_skill,
            steps=[
                _features_ready_step(
                    skill=skill,
                    readiness=readiness,
                    mil_model_name=mil_model_name,
                )
            ],
            notes=[
                "Existing feature tensors + splits detected; "
                "running downstream training directly.",
            ],
        )))

    if readiness.status == "raw_wsi_needs_labels":
        if not readiness.features_dir and (not data_output_dir or not generated_features_dir):
            return _wrap(ExecutionPlan(
                status="blocked",
                primary_skill=primary_skill,
                missing=["data_output_dir", "generated_features_dir"],
                notes=[
                    "raw WSI detected but caller did not pass concrete paths "
                    "for feature_extraction outputs",
                ],
            ))
        steps = _label_inference_plan(
            skill=skill,
            readiness=readiness,
            data_output_dir=data_output_dir,
            generated_features_dir=generated_features_dir,
            extractor_name=extractor_name,
            mil_model_name=mil_model_name,
        )
        return _wrap(_with_external_test(ExecutionPlan(
            status="ready",
            primary_skill=primary_skill,
            steps=steps,
            notes=[
                "registered raw WSI detected without labels; agent must infer "
                "labels and splits before feature extraction/training.",
            ],
        )))

    if readiness.status == "raw_wsi_ready":
        if not data_output_dir or not generated_features_dir:
            return _wrap(ExecutionPlan(
                status="blocked",
                primary_skill=primary_skill,
                missing=["data_output_dir", "generated_features_dir"],
                notes=[
                    "raw WSI detected but caller did not pass concrete paths "
                    "for feature_extraction outputs",
                ],
            ))
        steps = _raw_wsi_two_step(
            skill=skill,
            readiness=readiness,
            data_output_dir=data_output_dir,
            generated_features_dir=generated_features_dir,
            extractor_name=extractor_name,
            mil_model_name=mil_model_name,
        )
        return _wrap(_with_external_test(ExecutionPlan(
            status="ready",
            primary_skill=primary_skill,
            steps=steps,
            notes=[
                "raw WSI detected; running feature_extraction first, then training.",
            ],
        )))

    if readiness.status == "not_applicable":
        # Patch / segmentation: one step with the selected skill.
        return _wrap(_with_external_test(ExecutionPlan(
            status="ready",
            primary_skill=primary_skill,
            steps=[
                ExecutionStep(
                    id="train_downstream",
                    skill=skill,
                    title=f"Train {skill}",
                ),
            ],
        )))

    # readiness.status == "missing_data"
    if (
        allow_acquisition
        and acquisition_status in _ACQUISITION_RETRY_STATES
    ):
        return _wrap(ExecutionPlan(
            status="needs_acquisition",
            primary_skill=primary_skill,
            steps=[],
            missing=list(readiness.missing or []),
            notes=[
                "Local/prepared data is missing; the runner must attempt "
                "acquisition/download before training.",
            ],
        ))

    return _wrap(ExecutionPlan(
        status="blocked",
        primary_skill=primary_skill,
        steps=[],
        missing=list(readiness.missing or []),
        notes=[
            "Required data is missing and acquisition is disabled or exhausted; "
            "supply paths or enable auto_acquire_data with a working provider.",
        ],
    ))
