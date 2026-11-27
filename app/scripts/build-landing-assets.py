#!/usr/bin/env python3
"""Rebuild the public-page images from pinned public-domain sources.

Outputs (src/renderer/public/images/landing/ and src/renderer/src/components/landing/):
  specimen-slide.webp     high-resolution Wilms tumour scan inside the case's real section outline
  specimen-patches.webp   the 12 highest-scoring tiles of that scan, cropped at full resolution
  specimenTiles.ts        per-tile scores and the picked tiles, in atlas order
  evidence-heatmap.webp   cellularity overlay for tissue-detail.webp
  evidenceAnnotations.ts  tumour-nest outlines traced from tissue-detail.webp

Sources are downloaded once into --cache and verified by SHA-256 before use.
Requires numpy and opencv-python (both in the PathLab runtime venv).
"""
import argparse, hashlib, json, pathlib, urllib.request

import cv2
import numpy as np

SOURCES = {
    # Mikael Häggström, public domain (Wikimedia Commons).
    'wilms_whole.png': ('https://upload.wikimedia.org/wikipedia/commons/a/a4/Whole_slide_image_of_Wilms%27_tumor.png',
                        '9c479216b26d29a0d03212655f6cc4b2ece2de70e5d80759051be831e926df04'),
    'wilms_part.jpg': ('https://upload.wikimedia.org/wikipedia/commons/c/c8/Part_of_whole_slide_image_of_a_Wilms%27_tumor_of_the_kidney.jpg',
                       'ac9e9c86dd1efd2148c4b60ff27a203a093dd551fda00a7216be16a76c173611'),
}
ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGES = ROOT / 'src/renderer/public/images/landing'
COMPONENTS = ROOT / 'src/renderer/src/components/landing'
INFERNO = np.array([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164]], np.float32)


def fetch(cache: pathlib.Path, name: str) -> pathlib.Path:
    url, digest = SOURCES[name]
    path = cache / name
    if not path.exists():
        request = urllib.request.Request(url, headers={'User-Agent': 'PathLab-asset-build/1.0'})
        path.write_bytes(urllib.request.urlopen(request, timeout=120).read())
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        raise SystemExit(f'{name}: sha256 {actual} does not match the pinned {digest}')
    return path


def inferno(values: np.ndarray) -> np.ndarray:
    xs = np.linspace(0, 1, len(INFERNO))
    return np.stack([np.interp(values, xs, INFERNO[:, k]) for k in range(3)], -1)


# Stage geometry, shared with the engine through the generated specimenTiles.ts.
SLIDE_HEIGHT = 1.0          # world units; width follows the image aspect
COLS = 28
PATCHES = 12
SLIDE_PX = 1400             # width of the on-glass texture
PATCH_PX = 256


def section_mask(whole: np.ndarray, shape: tuple) -> np.ndarray:
    """Real tissue outline from the whole-slide scan, fitted to the high-resolution image."""
    rows = (whole.min(axis=2) > 240).mean(axis=1)
    bottom = next(y for y in range(500, 800) if rows[y] > 0.97)
    top = whole[:bottom]
    hsv = cv2.cvtColor(top, cv2.COLOR_BGR2HSV)
    marks = ((top.max(axis=2) < 110) & (hsv[..., 1] < 80)).astype(np.uint8) * 255
    marks[0:60, 0:200] = 255
    clean = cv2.inpaint(top, cv2.dilate(marks, np.ones((5, 5), np.uint8)), 6, cv2.INPAINT_TELEA)
    tissue = (clean.min(axis=2) < 215).astype(np.uint8) * 255
    tissue = cv2.morphologyEx(tissue, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(tissue)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = stats[largest, :4]
    outline = (labels[y:y + h, x:x + w] == largest).astype(np.uint8) * 255
    outline = cv2.resize(outline, (shape[1], shape[0]), interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(outline.astype(np.float32) / 255, (0, 0), shape[1] / 900)


def build_specimen(whole: np.ndarray, part: np.ndarray) -> None:
    height, width = part.shape[:2]
    # Keep the source's own glass background transparent too (its capsule edge is real).
    glass = np.clip((238 - part.min(axis=2).astype(np.float32)) / 40, 0, 1)
    alpha = section_mask(whole, part.shape) * glass
    extent_x = SLIDE_HEIGHT * width / height
    tile = extent_x / COLS
    rows = int(SLIDE_HEIGHT / tile)
    ppu = width / extent_x
    tile_px = tile * ppu
    y0 = (SLIDE_HEIGHT - rows * tile) / 2 * ppu

    f = part.astype(np.float32)
    dark = (((f.sum(axis=2) / 3) < 135) & (f[..., 0] > f[..., 1] + 18)).astype(np.float32)
    scores = np.zeros((rows, COLS), np.float32)
    valid = np.zeros((rows, COLS), bool)
    for r in range(rows):
        for c in range(COLS):
            ys, xs = int(y0 + r * tile_px), int(c * tile_px)
            ye, xe = int(y0 + (r + 1) * tile_px), int((c + 1) * tile_px)
            if alpha[ys:ye, xs:xe].mean() < 0.75:
                continue
            valid[r, c] = True
            scores[r, c] = dark[ys:ye, xs:xe].mean()
    scores = np.where(valid, (scores / scores[valid].max()) ** 0.8, 0)
    order = sorted(((scores[r, c], r, c) for r in range(rows) for c in range(COLS) if valid[r, c]), reverse=True)
    picked = []
    for _, r, c in order:
        if all(abs(r - pr) + abs(c - pc) > 3 for pr, pc in picked):
            picked.append((r, c))
        if len(picked) == PATCHES:
            break

    # The extracted patches are the picked tiles themselves, at full resolution.
    atlas = np.zeros((3 * PATCH_PX, 4 * PATCH_PX, 3), np.uint8)
    for rank, (r, c) in enumerate(picked):
        ys, xs = int(round(y0 + r * tile_px)), int(round(c * tile_px))
        crop = part[ys:ys + int(round(tile_px)), xs:xs + int(round(tile_px))]
        cell = cv2.resize(crop, (PATCH_PX, PATCH_PX), interpolation=cv2.INTER_CUBIC)
        ar, ac = divmod(rank, 4)
        atlas[ar * PATCH_PX:(ar + 1) * PATCH_PX, ac * PATCH_PX:(ac + 1) * PATCH_PX] = cell
    cv2.imwrite(str(IMAGES / 'specimen-patches.webp'), atlas, [cv2.IMWRITE_WEBP_QUALITY, 85])

    slide_h = round(SLIDE_PX * height / width)
    rgba = np.dstack([part, (alpha * 255).astype(np.uint8)])
    cv2.imwrite(str(IMAGES / 'specimen-slide.webp'), cv2.resize(rgba, (SLIDE_PX, slide_h), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_WEBP_QUALITY, 80])

    data = {
        'extent': [round(extent_x, 6), SLIDE_HEIGHT],
        'cols': COLS,
        'rows': rows,
        'scores': [round(float(v), 3) for v in scores.ravel()],
        'picked': [[int(c), int(r)] for r, c in picked],
    }
    (COMPONENTS / 'specimen/specimenTiles.ts').write_text(
        '// Generated by scripts/build-landing-assets.py from the pinned Wilms tumour scan.\n'
        '// scores: cellularity per tile (row-major, 0 = no tissue); picked: [col, row] by rank,\n'
        '// in the same order as the cells of specimen-patches.webp.\n'
        f'export const SPECIMEN_TILES = {json.dumps(data)} as const\n')


def build_evidence() -> None:
    img = cv2.imread(str(IMAGES / 'tissue-detail.webp'))
    height, width = img.shape[:2]
    f = cv2.GaussianBlur(img, (0, 0), 3).astype(np.float32)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    mean = (b + g + r) / 3
    # Tumour nests stain lavender; stroma is pink and fat is white.
    nests = (((r - b) < 22) & (mean < 205) & (mean > 60)).astype(np.uint8) * 255
    nests = cv2.morphologyEx(nests, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (35, 35)))
    nests = cv2.morphologyEx(nests, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (45, 45)))
    nests = (cv2.GaussianBlur(nests, (0, 0), 6) > 127).astype(np.uint8) * 255
    contours, _ = cv2.findContours(nests, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    contours = [c for c in sorted(contours, key=cv2.contourArea, reverse=True)[:4] if cv2.contourArea(c) > 40000]
    polygons = [cv2.approxPolyDP(c, 4, True)[:, 0, :] for c in contours]
    region = np.zeros((height, width), np.uint8)
    cv2.fillPoly(region, polygons, 255)

    f2 = cv2.GaussianBlur(img, (0, 0), 2).astype(np.float32)
    gray = f2.sum(axis=2) / 3
    nuclei = ((gray < cv2.GaussianBlur(gray, (0, 0), 30) - 16) & ((f2[..., 0] - f2[..., 1]) > 18) & (region > 0)).astype(np.float32)
    density = cv2.GaussianBlur(nuclei, (0, 0), 55) * 0.7 + cv2.GaussianBlur((region > 0).astype(np.float32), (0, 0), 55) * 0.3
    density /= density.max()
    colour = inferno(density)
    alpha = np.clip((density - 0.15) / 0.6, 0, 1) * 0.72
    heat = np.dstack([colour[..., 2], colour[..., 1], colour[..., 0], alpha * 255]).astype(np.uint8)
    cv2.imwrite(str(IMAGES / 'evidence-heatmap.webp'), cv2.resize(heat, (width // 2, height // 2), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_WEBP_QUALITY, 80])

    paths = ['M ' + ' L '.join(f'{x} {y}' for x, y in polygon) + ' Z' for polygon in polygons]
    (COMPONENTS / 'evidenceAnnotations.ts').write_text(
        '// Generated by scripts/build-landing-assets.py: tumour-nest outlines traced from\n'
        '// tissue-detail.webp (source pixels, 2048 x 1532). Illustrative region annotations.\n'
        f'export const NEST_OUTLINES: readonly string[] = {json.dumps(paths, indent=2)}\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', default=str(ROOT / '.cache/landing-assets'))
    cache = pathlib.Path(parser.parse_args().cache)
    cache.mkdir(parents=True, exist_ok=True)
    whole = cv2.imread(str(fetch(cache, 'wilms_whole.png')))
    part = cv2.imread(str(fetch(cache, 'wilms_part.jpg')))
    build_specimen(whole, part)
    build_evidence()
    print('landing assets written')


if __name__ == '__main__':
    main()
