"""Safe local watchdog for QQ login state and the Bot's OneBot connection.

It never restarts NapCat: a QQ login-required state needs human verification,
and an automated NapCat restart can make that state harder to recover.
"""
import json
import subprocess
import time
from pathlib import Path

try:
    from envfile import ROOT
except ImportError:  # package import during local tests
    from .envfile import ROOT
try:
    from qq_status import status as napcat_status
except ImportError:  # package import during local tests
    from .qq_status import status as napcat_status

STATE = ROOT / "runtime" / "qq-watchdog.json"
COMPOSE = ROOT / "scripts" / "compose.sh"


def bot_status():
    result = subprocess.run(
        ["bash", str(COMPOSE), "exec", "-T", "bot", "python", "scripts/healthcheck.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
        return data if isinstance(data, dict) else {"healthy": False, "phase": "bot_invalid"}
    except (json.JSONDecodeError, IndexError):
        return {"healthy": False, "phase": "bot_unreachable"}


def load_state():
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(data):
    STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = STATE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(STATE)


def restart_bot():
    try:
        result = subprocess.run(
            ["bash", str(COMPOSE), "restart", "bot"], cwd=ROOT,
            capture_output=True, text=True, timeout=90,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run_once(now=None):
    now = now or time.time()
    qq = napcat_status()
    bot = bot_status()
    state = load_state()
    action = "none"
    if not qq.get("ok"):
        phase = qq.get("phase", "webui_unreachable")
        state["disconnect_streak"] = 0
    elif not qq.get("is_login"):
        phase = "login_required"
        state["disconnect_streak"] = 0
    elif not qq.get("core_ready"):
        phase = "qq_core_not_ready"
        state["disconnect_streak"] = 0
    elif not bot.get("onebot_connected"):
        phase = "onebot_disconnected_while_qq_online"
        state["disconnect_streak"] = int(state.get("disconnect_streak", 0)) + 1
        last_restart = float(state.get("last_restart", 0))
        if state["disconnect_streak"] >= 3 and now - last_restart >= 900:
            action = "bot_restart_succeeded" if restart_bot() else "bot_restart_failed"
            state["last_restart"] = now
            state["disconnect_streak"] = 0
    else:
        phase = "online"
        state["disconnect_streak"] = 0
    state["last_check"] = int(now)
    save_state(state)
    return {
        "phase": phase,
        "action": action,
        "onebot_connected": bot.get("onebot_connected") is True,
        "bot_healthy": bot.get("healthy") is True,
        "qq_login": qq.get("is_login") is True,
    }


if __name__ == "__main__":
    print(json.dumps(run_once(), sort_keys=True))
