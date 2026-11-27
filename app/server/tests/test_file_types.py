import numpy as np
import tifffile

from backend.common.file_types import is_patch_file, is_patch_file_for_scan


def test_single_level_tiff_is_consistently_classified_as_patch(tmp_path):
    path = tmp_path / "patch.tiff"
    pixels = np.zeros((512, 768, 3), dtype=np.uint8)
    tifffile.imwrite(path, pixels, photometric="rgb", tile=(128, 128), metadata=None)

    assert is_patch_file(str(path), path.stat().st_size)
    assert is_patch_file_for_scan(str(path), path.stat().st_size)


def test_subifd_tiff_is_consistently_classified_as_wsi(tmp_path):
    path = tmp_path / "slide.tiff"
    level0 = np.zeros((512, 768, 3), dtype=np.uint8)
    level1 = np.zeros((128, 192, 3), dtype=np.uint8)

    with tifffile.TiffWriter(path, bigtiff=True) as writer:
        writer.write(
            level0,
            photometric="rgb",
            tile=(128, 128),
            subifds=1,
            metadata=None,
        )
        writer.write(
            level1,
            photometric="rgb",
            tile=(128, 128),
            subfiletype=1,
            metadata=None,
        )

    assert not is_patch_file(str(path), path.stat().st_size)
    assert not is_patch_file_for_scan(str(path), path.stat().st_size)


def test_unreadable_tiff_uses_size_fallback(tmp_path):
    path = tmp_path / "broken.tiff"
    path.write_bytes(b"not a tiff")

    assert is_patch_file(str(path), 1024)
    assert is_patch_file_for_scan(str(path), 1024)
    assert not is_patch_file(str(path), 64 * 1024 * 1024)


def test_large_single_level_tiff_keeps_size_fallback(tmp_path):
    path = tmp_path / "single-level.tiff"
    pixels = np.zeros((512, 768, 3), dtype=np.uint8)
    tifffile.imwrite(path, pixels, photometric="rgb", metadata=None)

    assert not is_patch_file(str(path), 64 * 1024 * 1024)
    assert not is_patch_file_for_scan(str(path), 64 * 1024 * 1024)
