"""Select the one already signed-in account; never read or display QQ credentials.

Run on the host after the first QQ login: python3 -m scripts.configure_account
"""
import json
import re
from pathlib import Path

from scripts.envfile import ROOT, read_env, write_env


def configure_account(root=ROOT):
    root = Path(root)
    config = root / "runtime" / "napcat" / "config"
    accounts = [m.group(1) for p in config.glob("onebot11_*.json")
                if (m := re.fullmatch(r"onebot11_([0-9]+)\.json", p.name))]
    if len(accounts) != 1:
        raise ValueError("Expected one previously signed-in account")
    values = read_env(root / ".env")
    if not values:
        raise ValueError("Deployment environment missing")
    values["NAPCAT_ACCOUNT"] = accounts[0]
    write_env(values, root / ".env")
    webui = config / "webui.json"
    webui_data = json.loads(webui.read_text())
    webui_data["autoLoginAccount"] = accounts[0]
    webui.write_text(json.dumps(webui_data), encoding="utf-8")
    for name in ("napcat.json", "napcat_" + accounts[0] + ".json"):
        target = config / name
        previous = json.loads(target.read_text()) if target.exists() else {}
        previous.update(fileLog=False, consoleLog=False,
                        fileLogLevel="error", consoleLogLevel="error")
        target.write_text(json.dumps(previous), encoding="utf-8")
    config.chmod(0o700)
    for target in config.glob("*.json"):
        if target.is_file() and not target.is_symlink():
            target.chmod(0o600)
    print("QQ_ACCOUNT_CONFIGURED: existing session selected; protected config; no values displayed")


if __name__ == "__main__":
    try:
        configure_account()
    except Exception as exc:
        raise SystemExit("QQ_ACCOUNT_CONFIGURATION_FAILED: " + type(exc).__name__) from None
