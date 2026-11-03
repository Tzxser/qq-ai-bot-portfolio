import pytest
from bot.config import ConfigError, Settings


def valid(monkeypatch):
    for key in ("ONEBOT_ACCESS_TOKEN", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "APP_SECRET"):
        monkeypatch.setenv(key, "fixture-value-" * 4)
    monkeypatch.setenv("DEEPSEEK_MODEL", "test-model")
    # The integration container loads the production .env as an env_file.
    # Keep configuration unit fixtures deterministic and fail-closed even
    # when production group features are enabled for a live acceptance run.
    for key in ("GROUP_ENABLED", "GROUP_FEATURES_ENABLED", "ALLOWED_GROUP_IDS", "WELCOME_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


def test_missing_key_is_waiting_state(monkeypatch):
    valid(monkeypatch)
    s = Settings.from_env()
    assert not s.api_key
    assert not s.group_enabled
    assert "fixture-value" not in repr(s)


def test_v21_group_defaults_are_fail_closed(monkeypatch):
    valid(monkeypatch)
    s = Settings.from_env()
    assert s.group_features_enabled is False
    assert s.allowed_group_ids == ()
    # Production may hold the user-provided target in protected .env; never
    # assert or print its value in a test snapshot.
    assert not s.association_lead_target_qq or s.association_lead_target_qq.isdecimal()


def test_v21_ids_are_numeric_and_target_is_validated(monkeypatch):
    valid(monkeypatch)
    monkeypatch.setenv("GROUP_FEATURES_ENABLED", "true")
    monkeypatch.setenv("ALLOWED_GROUP_IDS", "30003,30004")
    monkeypatch.setenv("ASSOCIATION_LEAD_TARGET_QQ", "90009")
    s = Settings.from_env()
    assert s.allowed_group_ids == ("30003", "30004")
    assert s.association_lead_target_qq == "90009"
    monkeypatch.setenv("ALLOWED_GROUP_IDS", "not-an-id")
    with pytest.raises(ConfigError):
        Settings.from_env()


@pytest.mark.parametrize("key,value", [("ONEBOT_ACCESS_TOKEN", "short"),
    ("DEEPSEEK_MODEL", ""), ("DEEPSEEK_BASE_URL", "http://insecure.test"),
    ("DEEPSEEK_BASE_URL", "https://user:pass@example.test"),
    ("LLM_MAX_ATTEMPTS", "0"), ("MAX_PENDING_MESSAGES", "99999"),
    ("GROUP_ENABLED", "sometimes"), ("LLM_PROVIDER", "unknown")])
def test_invalid_config_is_rejected_without_value(monkeypatch, key, value):
    valid(monkeypatch)
    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigError) as exc:
        Settings.from_env()
    assert key in str(exc.value)
    if value and value != "0":
        assert value not in str(exc.value)
