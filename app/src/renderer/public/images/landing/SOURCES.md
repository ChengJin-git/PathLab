# Public-page image sources

Retrieved and reviewed on 2026-11-06. Images are served locally; pages do not hotlink to the source sites.

## tissue-detail.webp

- Work: *Histopathology of invasive ductal carcinoma, high magnification* (H&E stain).
- Author: Mikael Häggström, M.D.
- Source: https://commons.wikimedia.org/wiki/File:Histopathology_of_invasive_ductal_carcinoma,_high_magnification.jpg
- Original: https://upload.wikimedia.org/wikipedia/commons/1/1c/Histopathology_of_invasive_ductal_carcinoma%2C_high_magnification.jpg
- License: CC0 1.0 Universal Public Domain Dedication, as stated on the file page.
- License text: https://creativecommons.org/publicdomain/zero/1.0/
- Original dimensions: 2048 × 1532. Converted to WebP (quality 86); no recoloring or generated tissue.
- Use: base layer of the slide / annotations / results stack on the landing page (its only use). Attribution and provenance are retained in this file.
- Selection: 9/10 for clear H&E morphology, a professional source, explicit CC0 license, and readable composition at web sizes.

## Specimen stage (landing hero, sign-in)

Both sources are by Mikael Häggström, M.D., and marked public domain on Wikimedia Commons; they show the same case of Wilms' tumour.

- *Whole slide image of Wilms' tumor* — https://commons.wikimedia.org/wiki/File:Whole_slide_image_of_Wilms%27_tumor.png (1281 × 1619, SHA-256 `9c479216b26d29a0d03212655f6cc4b2ece2de70e5d80759051be831e926df04`).
- *Part of whole slide image of a Wilms' tumor of the kidney* — https://commons.wikimedia.org/wiki/File:Part_of_whole_slide_image_of_a_Wilms%27_tumor_of_the_kidney.jpg (5849 × 4379, SHA-256 `ac9e9c86dd1efd2148c4b60ff27a203a093dd551fda00a7216be16a76c173611`).

`scripts/build-landing-assets.py` downloads both, checks the hashes and writes:

- `specimen-slide.webp` — the second (high-resolution) image shown inside the section outline traced from the first image's whole-slide scan, with the glass background transparent. The tissue pixels are the source's; only the outline is borrowed from the scan of the same case.
- `specimen-patches.webp` — the 12 highest-scoring tiles of that image, cropped at full resolution, in rank order.
- `specimen/specimenTiles.ts` — per-tile scores (share of haematoxylin-dark pixels) and the picked tiles, so the animation lifts exactly the tiles shown in the atlas.

The scores drive an illustration, not a model output or a diagnosis.

## Layer stack annotations

`evidenceAnnotations.ts` and `evidence-heatmap.webp` are generated from `tissue-detail.webp` by `scripts/build-landing-assets.py`: tumour-nest outlines are traced from the stain colour (lavender nests against pink stroma and white fat), and the overlay is a cellularity map inside those nests. Both are illustrative, not segmentation results or diagnoses. Source organizations and photographers do not endorse PathLab.

## Design references (not redistributed assets)

- Apple HIG, Motion: https://developer.apple.com/design/human-interface-guidelines/motion
- Apple HIG, Materials: https://developer.apple.com/design/human-interface-guidelines/materials
- Apple HIG, Typography: https://developer.apple.com/design/human-interface-guidelines/typography
- Apple HIG, Accessibility: https://developer.apple.com/design/human-interface-guidelines/accessibility
- QuPath annotation tools: https://qupath.readthedocs.io/en/latest/docs/starting/annotating.html
- Anthropic research-system design: https://www.anthropic.com/engineering/multi-agent-research-system (planning, iterative exploration, source-linked outputs; reference only, no third-party UI assets reused).

Reference principles: a large tissue canvas, a separate layer inspector, unobtrusive controls over imagery, legible typography, and restrained depth. No Apple or QuPath screenshots, logos, or implementation code are included.
