"""PathLab patch segmentation training template (stub).

Plan T5 leaves segmentation as future work — this stub exists only to
satisfy the routable-skill / loadable-template invariant
(``test_all_registered_skill_templates_load``). When the agent loads
this skill, it gets an explicit error pointing at the gap rather than
a missing-file crash that takes down the tool loop.

When segmentation training lands, replace this body with the real
training pipeline (UNet/DeepLab + dice/IoU metrics + AMP).
"""
import sys


def main() -> None:
    sys.stderr.write(
        "patch_segmentation template is a stub — segmentation training "
        "is not implemented in this PathScientist build. Pick a different "
        "skill (e.g. patch_classification, mil_classification) or write "
        "code from scratch.\n"
    )
    raise SystemExit(2)


if __name__ == "__main__":
    main()
