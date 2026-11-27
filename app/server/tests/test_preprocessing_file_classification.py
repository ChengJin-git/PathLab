from types import SimpleNamespace

from backend.preprocessing.main import _record_is_patch


def test_persisted_file_type_takes_priority_over_fallback(monkeypatch):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("fallback classifier should not run")

    monkeypatch.setattr("backend.preprocessing.main.is_patch_file", fail_if_called)

    assert _record_is_patch(SimpleNamespace(data_type="patch"), "image.tiff", 0)
    assert not _record_is_patch(SimpleNamespace(data_type="wsi"), "slide.tiff", 0)


def test_missing_persisted_file_type_uses_fallback(monkeypatch):
    monkeypatch.setattr(
        "backend.preprocessing.main.is_patch_file",
        lambda _path, _size: True,
    )

    assert _record_is_patch(SimpleNamespace(data_type=None), "legacy.tiff", 123)
