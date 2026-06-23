import sys
from types import SimpleNamespace

from backend.preprocessing.coords_utils import safe_load_h5_coords_attrs


def test_safe_load_h5_coords_attrs_returns_two_tuple_on_unexpected_error(
    tmp_path, monkeypatch
):
    h5_path = tmp_path / "coords.h5"
    h5_path.write_bytes(b"x")

    class _BoomFile:
        def __enter__(self):
            raise RuntimeError("boom")

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_h5py = SimpleNamespace(File=lambda *args, **kwargs: _BoomFile())
    monkeypatch.setitem(sys.modules, "h5py", fake_h5py)

    attrs, error = safe_load_h5_coords_attrs(h5_path, delete_if_corrupted=False)

    assert attrs is None
    assert "boom" in (error or "")
