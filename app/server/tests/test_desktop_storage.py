def test_desktop_uses_the_same_storage_setting_as_settings(tmp_path, monkeypatch):
    from backend.common.config import Config
    from backend.common import settings_store

    monkeypatch.setenv('PATHLAB_APP_DATA_DIR', str(tmp_path / 'desktop'))
    monkeypatch.delenv('PATHLAB_UPLOADS_DIR', raising=False)
    monkeypatch.setattr(Config, 'STORAGE_CONFIG_FILE', None)
    monkeypatch.setattr(settings_store, '_CONFIG_FILE_OVERRIDE', None)
    root = tmp_path / 'selected-directory'
    Config.set_uploads_dir(str(root))
    monkeypatch.delenv('PATHLAB_UPLOADS_DIR')
    assert Config.get_uploads_dir() == root
    assert Config.get_uploads_dir_source() == 'config'
    assert settings_store._get_storage_config_file() == tmp_path / 'desktop/storage.json'


def test_desktop_knowledge_cache_is_outside_readonly_application(tmp_path, monkeypatch):
    from gateway.knowledge import chat

    monkeypatch.setenv('PATHLAB_APP_DATA_DIR', str(tmp_path))
    assert chat.get_training_rag_runtime_dir() == tmp_path / 'training_rag'
    assert chat.get_training_rag_cache_dir().is_relative_to(tmp_path)
