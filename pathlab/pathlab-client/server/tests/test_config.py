import json
from importlib import import_module
from pathlib import Path
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.delenv("TURNSTILE_ENABLED", raising=False)
    monkeypatch.delenv("TURNSTILE_SITE_KEY", raising=False)
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    config_file = tmp_path / "storage.json"
    with patch("backend.common.config.Config.STORAGE_CONFIG_FILE", str(config_file)):
        Config = import_module("backend.common.config").Config

        Config.reset_runtime_cache_for_tests()
        yield Config
        Config.reset_runtime_cache_for_tests()


class TestGlobalSettings:
    def test_defaults_when_no_config_file(self, isolated_config):
        settings = isolated_config.get_global_settings()
        assert settings["openrouter_model"] == "qwen/qwen3.5-plus-02-15"
        assert settings["local_vllm_enabled"] is False
        assert settings["local_asr_enabled"] is False
        assert settings["openrouter_api_key"] == ""
        assert settings["huggingface_token"] == ""
        assert settings["dashscope_api_key"] == ""
        assert settings["exa_api_key"] == ""
        assert settings["turnstile_enabled"] is False
        assert settings["turnstile_site_key"] == ""
        assert settings["turnstile_secret_key"] == ""

    def test_update_persists_and_returns_full_settings(self, isolated_config):
        result = isolated_config.update_global_settings(
            {"openrouter_api_key": "sk-test-123", "openrouter_model": "gpt-4o"}
        )
        assert result["openrouter_api_key"] == "sk-test-123"
        assert result["openrouter_model"] == "gpt-4o"
        assert result["local_vllm_enabled"] is False

    def test_update_ignores_unknown_keys(self, isolated_config):
        result = isolated_config.update_global_settings(
            {"openrouter_api_key": "valid", "unknown_field": "ignored"}
        )
        assert result["openrouter_api_key"] == "valid"
        assert "unknown_field" not in result

    def test_cache_is_invalidated_after_update(self, isolated_config):
        isolated_config.get_global_settings()
        isolated_config.update_global_settings({"openrouter_api_key": "new-key"})
        settings = isolated_config.get_global_settings()
        assert settings["openrouter_api_key"] == "new-key"

    def test_update_vllm_settings(self, isolated_config):
        result = isolated_config.update_global_settings(
            {
                "local_vllm_enabled": True,
                "local_vllm_base_url": "http://myserver:8000/v1",
                "local_vllm_model": "llama-3",
                "local_vllm_api_key": "vllm-secret",
            }
        )
        assert result["local_vllm_enabled"] is True
        assert result["local_vllm_base_url"] == "http://myserver:8000/v1"
        assert result["local_vllm_model"] == "llama-3"
        assert result["local_vllm_api_key"] == "vllm-secret"

    def test_update_asr_settings(self, isolated_config):
        result = isolated_config.update_global_settings(
            {
                "local_asr_enabled": True,
                "local_asr_base_url": "ws://localhost:8001/api-ws/v1/realtime",
                "local_asr_model": "whisper-large",
                "local_asr_api_key": "asr-secret",
            }
        )
        assert result["local_asr_enabled"] is True
        assert result["local_asr_base_url"] == "ws://localhost:8001/api-ws/v1/realtime"
        assert result["local_asr_model"] == "whisper-large"

    def test_update_turnstile_settings(self, isolated_config):
        result = isolated_config.update_global_settings(
            {
                "turnstile_enabled": True,
                "turnstile_site_key": "site-key-abc",
                "turnstile_secret_key": "secret-key-xyz",
            }
        )
        assert result["turnstile_enabled"] is True
        assert result["turnstile_site_key"] == "site-key-abc"
        assert result["turnstile_secret_key"] == "secret-key-xyz"

    def test_env_overrides_config_file_for_turnstile(
        self, isolated_config, monkeypatch
    ):
        isolated_config.update_global_settings(
            {"turnstile_enabled": False, "turnstile_site_key": "from-file"}
        )
        monkeypatch.setenv("TURNSTILE_ENABLED", "true")
        monkeypatch.setenv("TURNSTILE_SITE_KEY", "from-env")
        isolated_config.reset_runtime_cache_for_tests()

        settings = isolated_config.get_global_settings()
        assert settings["turnstile_enabled"] is True
        assert settings["turnstile_site_key"] == "from-env"

    def test_returns_copy_not_reference(self, isolated_config):
        s1 = isolated_config.get_global_settings()
        s1["openrouter_model"] = "mutated"
        s2 = isolated_config.get_global_settings()
        assert s2["openrouter_model"] != "mutated"


class TestTaskTimeout:
    def test_default_timeout_is_three_days(self, isolated_config):
        assert isolated_config.get_task_timeout() == 86400 * 3

    def test_set_timeout_persists(self, isolated_config):
        isolated_config.set_task_timeout(7200)
        isolated_config.reset_runtime_cache_for_tests()
        assert isolated_config.get_task_timeout() == 7200

    def test_timeout_clamped_to_minimum_60(self, isolated_config):
        result = isolated_config.set_task_timeout(10)
        assert result == 60

    def test_timeout_clamped_to_maximum_259200(self, isolated_config):
        result = isolated_config.set_task_timeout(999999)
        assert result == 259200

    def test_cached_value_returned_without_disk_read(self, isolated_config):
        isolated_config.set_task_timeout(3600)
        assert isolated_config.get_task_timeout() == 3600
        assert isolated_config.get_task_timeout() == 3600


class TestMaxConcurrent:
    def test_default_is_1(self, isolated_config):
        assert isolated_config.get_max_concurrent(default=1) == 1

    def test_set_and_get(self, isolated_config):
        isolated_config.set_max_concurrent(4)
        assert isolated_config.get_max_concurrent() == 4

    def test_clamped_to_min_1(self, isolated_config):
        result = isolated_config.set_max_concurrent(0)
        assert result == 1

    def test_clamped_to_max_10(self, isolated_config):
        result = isolated_config.set_max_concurrent(20)
        assert result == 10


class TestTrainingPreflightDefaults:
    def test_defaults_are_positive(self, isolated_config):
        assert isolated_config.DEFAULT_TRAINING_PREFLIGHT_LOCAL_ROOT_TIMEOUT >= 1
        assert isolated_config.DEFAULT_TRAINING_PREFLIGHT_LOCAL_SAMPLE_TIMEOUT >= 1
        assert isolated_config.DEFAULT_TRAINING_PREFLIGHT_LOCAL_SAMPLE_SIZE > 0
        assert isolated_config.DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_ROOT_TIMEOUT >= 1
        assert isolated_config.DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_SAMPLE_TIMEOUT >= 1
        assert isolated_config.DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_SAMPLE_SIZE > 0

    def test_defaults_match_expected_policy_sizes(self, isolated_config):
        assert isolated_config.DEFAULT_TRAINING_PREFLIGHT_LOCAL_SAMPLE_SIZE == 8
        assert isolated_config.DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_SAMPLE_SIZE == 5


class TestMaintenanceMode:
    def test_default_maintenance_mode_is_false(self, isolated_config):
        assert isolated_config.get_maintenance_mode() is False

    def test_set_maintenance_mode(self, isolated_config):
        isolated_config.set_maintenance_mode(True)
        assert isolated_config.get_maintenance_mode() is True

    def test_set_maintenance_mode_with_restore_users(self, isolated_config):
        user_ids = ["user-1", "user-2"]
        isolated_config.set_maintenance_mode_state(True, restore_user_ids=user_ids)
        assert isolated_config.get_maintenance_mode() is True
        assert isolated_config.get_maintenance_mode_restore_user_ids() == user_ids

    def test_clear_maintenance_restore_user_ids(self, isolated_config):
        isolated_config.set_maintenance_mode_restore_user_ids(["user-1"])
        isolated_config.clear_maintenance_mode_restore_user_ids()
        assert isolated_config.get_maintenance_mode_restore_user_ids() == []


class TestMaintenanceNotice:
    def test_no_notice_by_default(self, isolated_config):
        assert isolated_config.get_maintenance_notice() is None

    def test_set_notice_returns_message_and_timestamp(self, isolated_config):
        result = isolated_config.set_maintenance_notice(
            "Server maintenance at midnight"
        )
        assert result is not None
        assert result["message"] == "Server maintenance at midnight"
        assert "updated_at" in result

    def test_set_empty_notice_clears_it(self, isolated_config):
        isolated_config.set_maintenance_notice("Initial notice")
        result = isolated_config.set_maintenance_notice("")
        assert result is None
        assert isolated_config.get_maintenance_notice() is None

    def test_set_whitespace_notice_clears_it(self, isolated_config):
        isolated_config.set_maintenance_notice("Notice")
        result = isolated_config.set_maintenance_notice("   ")
        assert result is None

    def test_notice_is_persisted(self, isolated_config):
        isolated_config.set_maintenance_notice("Persisted notice")
        notice = isolated_config.get_maintenance_notice()
        assert notice["message"] == "Persisted notice"


class TestConfigFileMerge:
    def test_multiple_writes_are_merged(self, isolated_config):
        isolated_config.update_global_settings({"openrouter_api_key": "key-1"})
        isolated_config.set_task_timeout(1800)
        config_file = Path(isolated_config._get_storage_config_file())
        data = json.loads(config_file.read_text())
        assert data["openrouter_api_key"] == "key-1"
        assert data["task_timeout"] == 1800


class TestUploadsDirConfig:
    def test_set_uploads_dir_persists_and_normalizes_path(
        self, isolated_config, tmp_path
    ):
        target = isolated_config.set_uploads_dir(str(tmp_path / "storage"))
        assert target == (tmp_path / "storage").resolve()
        assert isolated_config.get_uploads_dir() == target

    def test_ensure_directories_creates_autoresearch_roots(
        self, isolated_config, tmp_path
    ):
        target = isolated_config.set_uploads_dir(str(tmp_path / "storage"))

        isolated_config.ensure_directories()

        assert (target / "autoresearch").is_dir()
        assert (target / "autoresearch" / "autoresearch_sessions").is_dir()
