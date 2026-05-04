"""Submission bundle export stage scaffold."""

from __future__ import annotations

import zipfile

from gateway.paper_generation.schemas import PaperManifest  # noqa: E402
from gateway.paper_generation.storage import PaperRunPaths  # noqa: E402

from .common import load_config, register_artifact


def run(paths: PaperRunPaths, manifest: PaperManifest) -> None:
    config = load_config(paths)
    for template in config.selected_templates:
        template_id = template.value
        final_dir = paths.final_for_template(template_id)
        if not final_dir.exists():
            raise FileNotFoundError(f"final directory missing for template {template_id}")
        bundle_name = f"{template_id}_bundle.zip"
        bundle_path = paths.exports_dir / bundle_name
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in sorted(final_dir.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, arcname=str(file_path.relative_to(final_dir)))
            archive.writestr(
                "README.md",
                "# PathLab Paper Agent Bundle\n\n"
                f"Paper ID: `{config.paper_id}`\n\n"
                f"Template: `{template_id}`\n\n"
                "This is a deterministic scaffold bundle. Private evidence files are excluded.\n",
            )
        register_artifact(
            manifest,
            f"exports/{bundle_name}",
            label=f"{template_id} submission bundle",
            content_type="application/zip",
        )
