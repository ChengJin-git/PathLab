import builtins
import importlib
import sys


def test_gateway_utils_survives_aslide_dlopen_error(monkeypatch):
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "Aslide":
            raise OSError("dlopen(libkfbslide.so): invalid mach-o")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    sys.modules.pop("gateway.utils", None)

    module = importlib.import_module("gateway.utils")
    assert module.ASLIDE_AVAILABLE is False
    assert module.Slide is None
