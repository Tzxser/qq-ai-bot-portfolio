import json

from scripts import qq_watchdog


def test_login_required_does_not_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(qq_watchdog, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(qq_watchdog, "napcat_status", lambda: {
        "ok": True, "is_login": False, "login_phase": "waiting_qrcode",
    })
    monkeypatch.setattr(qq_watchdog, "bot_status", lambda: {
        "healthy": True, "onebot_connected": False,
    })
    restart = []
    monkeypatch.setattr(qq_watchdog, "restart_bot", lambda: restart.append(True))
    result = qq_watchdog.run_once(now=1000)
    assert result["phase"] == "login_required"
    assert restart == []


def test_three_online_disconnects_restart_bot(monkeypatch, tmp_path):
    monkeypatch.setattr(qq_watchdog, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(qq_watchdog, "napcat_status", lambda: {
        "ok": True, "is_login": True, "core_ready": True,
    })
    monkeypatch.setattr(qq_watchdog, "bot_status", lambda: {
        "healthy": True, "onebot_connected": False,
    })
    restart = []
    monkeypatch.setattr(qq_watchdog, "restart_bot", lambda: restart.append(True) or True)
    assert qq_watchdog.run_once(now=1000)["action"] == "none"
    assert qq_watchdog.run_once(now=1060)["action"] == "none"
    assert qq_watchdog.run_once(now=1120)["action"] == "bot_restart_succeeded"
    assert len(restart) == 1


def test_status_never_returns_token(monkeypatch, tmp_path):
    monkeypatch.setattr(qq_watchdog, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(qq_watchdog, "napcat_status", lambda: {
        "ok": True, "is_login": True,
    })
    monkeypatch.setattr(qq_watchdog, "bot_status", lambda: {
        "healthy": True, "onebot_connected": True,
    })
    result = qq_watchdog.run_once(now=1)
    assert "token" not in json.dumps(result).lower()
