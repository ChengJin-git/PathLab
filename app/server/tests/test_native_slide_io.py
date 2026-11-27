"""Small real on-disk TIFF fixture; no proprietary codecs or downloaded slides."""
import numpy as np
import tifffile


def test_native_tiff_region_and_thumbnail(tmp_path):
    from Aslide import Slide
    pixels = np.zeros((512, 512, 3), dtype=np.uint8)
    pixels[:, :, 0] = 190
    pixels[128:384, 128:384, 1] = 120
    file = tmp_path / 'local-slide.tif'
    tifffile.imwrite(file, pixels, photometric='rgb', tile=(128,128), metadata=None)
    with Slide(str(file)) as slide:
        assert slide.dimensions == (512,512)
        region = slide.read_region((128,128),0,(64,64)).convert('RGB')
        assert region.size == (64,64)
        assert np.asarray(region)[20,20].tolist() == [190,120,0]
        thumbnail = slide.get_thumbnail((128,128))
        assert max(thumbnail.size) <= 128
