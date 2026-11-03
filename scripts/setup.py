import json
import os
import re
import secrets
import sys

from envfile import ROOT, read_env, write_env


def setup():
    os.umask(0o077)
    values = read_env(ROOT / ".env.example")
    values.update(read_env())
    for key in ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "ONEBOT_ACCESS_TOKEN", "WEBUI_TOKEN", "APP_SECRET"):
        if not values.get(key):
            values[key] = secrets.token_hex(32)
    if hasattr(os, "getuid"):
        values["NAPCAT_UID"] = str(os.getuid() or 1000)
        values["NAPCAT_GID"] = str(os.getgid() or 1000)
    write_env(values)
    config = ROOT / "runtime" / "napcat" / "config"
    config.mkdir(parents=True, exist_ok=True)
    for directory in (ROOT / "runtime", config.parent, config):
        directory.chmod(0o700)
    onebot = {"network": {"httpServers": [], "httpSseServers": [], "httpClients": [],
        "websocketServers": [], "plugins": [], "websocketClients": [{
            "name": "bot-core", "enable": True, "url": "ws://bot:8080/onebot/v11/ws",
            "messagePostFormat": "array", "reportSelfMessage": False,
            "reconnectInterval": 5000, "heartInterval": 30000,
            "token": values["ONEBOT_ACCESS_TOKEN"], "debug": False}]}}
    files = {"onebot11.json": onebot,
             "napcat.json": {"fileLog": False, "consoleLog": False,
                 "fileLogLevel": "error", "consoleLogLevel": "error"},
             "webui.json": {"host": "0.0.0.0", "port": 6099, "token": values["WEBUI_TOKEN"],
                 "loginRate": 3, "enableXForwardedFor": False}}
    # Preserve login/account preferences while enforcing this deployment's security fields.
    for name, data in files.items():
        target = config / name
        previous = json.loads(target.read_text()) if target.exists() else {}
        previous.update(data)
        target.write_text(json.dumps(previous), encoding="utf-8")
        target.chmod(0o600)
    for target in config.glob("onebot11_*.json"):
        target.write_text(json.dumps(onebot), encoding="utf-8")
        target.chmod(0o600)
    for target in config.glob("napcat_*.json"):
        if not re.fullmatch(r"napcat_[0-9]+\.json", target.name):
            continue
        target.write_text(json.dumps(files["napcat.json"]), encoding="utf-8")
        target.chmod(0o600)
    print("SETUP_OK: internal secrets/configuration stored; no values displayed")
    print("DEEPSEEK_API_KEY: " + ("present" if values.get("DEEPSEEK_API_KEY") else "missing"))


if __name__ == "__main__":
    try:
        setup()
    except Exception as exc:
        print("SETUP_FAILED: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
