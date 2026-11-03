from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "start_webui_tunnel.ps1"


def test_webui_tunnel_helper_is_loopback_only_and_reconnects():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "127.0.0.1`:$LocalPort`:127.0.0.1`:$RemotePort" in source
    assert "ExitOnForwardFailure=yes" in source
    assert "ServerAliveInterval=30" in source
    assert "ServerAliveCountMax=3" in source
    assert "BatchMode=yes" in source
    assert "Start-Sleep -Seconds $delay" in source


def test_webui_tunnel_helper_does_not_stop_existing_local_processes():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Get-NetTCPConnection" in source
    assert "no process was stopped" in source
    assert "Stop-Process" not in source
