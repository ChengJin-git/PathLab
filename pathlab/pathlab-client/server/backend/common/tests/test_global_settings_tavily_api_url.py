import json

from backend.common.config import Config


def test_get_global_settings_includes_tavily_api_url_default(tmp_path, monkeypatch):
    storage_file = tmp_path / "storage.json"
    monkeypatch.setattr(Config, "STORAGE_CONFIG_FILE", storage_file)

    settings = Config.get_global_settings()

    assert settings["tavily_api_url"] == "https://api.tavily.com"


def test_update_global_settings_persists_tavily_api_url(tmp_path, monkeypatch):
    storage_file = tmp_path / "storage.json"
    monkeypatch.setattr(Config, "STORAGE_CONFIG_FILE", storage_file)

    updated = Config.update_global_settings({"tavily_api_url": "https://tavily.internal"})

    assert updated["tavily_api_url"] == "https://tavily.internal"

    persisted = json.loads(storage_file.read_text(encoding="utf-8"))
    assert persisted["tavily_api_url"] == "https://tavily.internal"
