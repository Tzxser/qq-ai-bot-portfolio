from pathlib import Path

import pytest

from scripts.configure_group import update_env


def test_group_config_changes_only_group_flags(tmp_path):
    path = tmp_path / ".env"
    path.write_text("APP_SECRET='x'\nGROUP_FEATURES_ENABLED='false'\nALLOWED_GROUP_IDS=''\n", encoding="utf-8")
    update_env(path, "30003", True, False)
    text = path.read_text(encoding="utf-8")
    assert "APP_SECRET='x'" in text
    assert "GROUP_FEATURES_ENABLED='true'" in text
    assert "ALLOWED_GROUP_IDS='30003'" in text
    assert "WELCOME_ENABLED='false'" in text


def test_group_config_rejects_non_numeric(tmp_path):
    path = tmp_path / ".env"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        update_env(path, "not-a-group", True, None)
