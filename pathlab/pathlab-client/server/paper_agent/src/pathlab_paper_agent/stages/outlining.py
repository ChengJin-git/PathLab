"""PaperOrchestra-style outline stage scaffold."""

from __future__ import annotations

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from .common import SECTION_ORDER, load_config, register_artifact, write_json


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = load_config(paths)
    outline = {
        "plotting_plan": [
            {
                "figure_id": "fig:overview",
                "kind": "conceptual",
                "source": "idea + method_block",
                "design_objective": "Show the PathLab WSI-to-paper evidence workflow.",
                "backend": "requires_user_revision",
            }
        ],
        "macro_lit_search": [
            "computational pathology whole slide image analysis",
            "AI-assisted pathology clinical validation",
        ],
        "micro_lit_clusters": [
            {
                "cluster": "multiple instance learning for pathology",
                "queries": [
                    "attention multiple instance learning whole slide images",
                    "computational pathology foundation models validation",
                ],
            }
        ],
        "section_plan": [
            {"section": section.replace("_", " ").title(), "goal": "scaffold"}
            for section in SECTION_ORDER
        ],
        "pathlab_extensions": {
            "templates": [template.value for template in config.selected_templates],
            "claim_plan": [],
            "guard_requirements": [
                "metric",
                "claim",
                "identifier",
                "consistency",
                "citation",
                "latex",
                "figure_table",
            ],
        },
    }
    write_json(paths.outline_json, outline)
    register_artifact(
        manifest,
        "drafts/outline.json",
        label="Outline",
        content_type="application/json",
    )
