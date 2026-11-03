import json

import pytest

from scripts.configure_account import configure_account
from scripts.envfile import read_env, write_env


def test_select_existing_account_preserve_secrets_and_protocol(tmp_path):
    config = tmp_path / "runtime" / "napcat" / "config"
    config.mkdir(parents=True)
    write_env({"WEBUI_TOKEN": "test-webui-token", "DEEPSEEK_API_KEY": "test-api-key"}, tmp_path / ".env")
    (config / "onebot11_10001.json").write_text('{}')
    (config / "webui.json").write_text('{"token":"test-webui-token"}')
    (config / "napcat_10001.json").write_text(json.dumps({"consoleLog": True, "custom": 42}))
    protocol = config / "napcat_protocol_10001.json"
    protocol.write_text('{"protocol": "preserve-me"}')
    before = protocol.read_bytes()
    configure_account(tmp_path)
    configure_account(tmp_path)
    values = read_env(tmp_path / ".env")
    assert values == {"WEBUI_TOKEN": "test-webui-token", "DEEPSEEK_API_KEY": "test-api-key",
                      "NAPCAT_ACCOUNT": "10001"}
    assert protocol.read_bytes() == before
    assert json.loads((config / "webui.json").read_text()) == {
        "token": "test-webui-token", "autoLoginAccount": "10001"}
    assert json.loads((config / "napcat_10001.json").read_text())["custom"] == 42
    for name in ("napcat.json", "napcat_10001.json"):
        data = json.loads((config / name).read_text())
        assert data["consoleLog"] is False and data["fileLog"] is False


@pytest.mark.parametrize("accounts", [[], ["10001", "10002"]])
def test_missing_or_ambiguous_account_leaves_environment_unchanged(tmp_path, accounts):
    config = tmp_path / "runtime" / "napcat" / "config"
    config.mkdir(parents=True)
    write_env({"WEBUI_TOKEN": "test-webui-token"}, tmp_path / ".env")
    for account in accounts:
        (config / f"onebot11_{account}.json").write_text('{}')
    before = (tmp_path / ".env").read_bytes()
    with pytest.raises(ValueError, match="Expected one"):
        configure_account(tmp_path)
    assert (tmp_path / ".env").read_bytes() == before
