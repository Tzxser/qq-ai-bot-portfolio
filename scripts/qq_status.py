"""Read NapCat login state without printing any credential or account ID."""
import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from envfile import ROOT, read_env
except ImportError:  # pragma: no cover - allows direct standalone use
    ROOT = Path(__file__).resolve().parents[1]

    def read_env(path=None):
        result = {}
        for line in Path(path or ROOT / ".env").read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key and len(value) >= 2 and value[0] == value[-1] == "'":
                result[key] = value[1:-1]
        return result


def request(base, path, payload, credential=None, timeout=8):
    headers = {"Content-Type": "application/json"}
    if credential:
        headers["Authorization"] = "Bearer " + credential
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def status(base=None, token=None):
    values = read_env()
    base = base or os.environ.get("NAPCAT_WEBUI_URL", "http://127.0.0.1:6099")
    token = token if token is not None else values.get("WEBUI_TOKEN") or os.environ.get("WEBUI_TOKEN", "")
    if not token:
        return {"ok": False, "phase": "webui_token_missing"}
    credential = None
    try:
        digest = hashlib.sha256((token + ".napcat").encode("utf-8")).hexdigest()
        credential = request(base, "/api/auth/login", {"hash": digest})["data"]["Credential"]
        data = request(base, "/api/QQLogin/CheckLoginStatus", {}, credential)["data"]
        quick = request(base, "/api/QQLogin/GetQuickLoginList", {}, credential).get("data")
        return {
            "ok": True,
            "is_login": data.get("isLogin") is True,
            "is_offline": data.get("isOffline") is True,
            "core_ready": data.get("coreReady") is True,
            "login_phase": data.get("loginPhase") or "unknown",
            "quick_login_count": len(quick) if isinstance(quick, list) else 0,
        }
    except (urllib.error.URLError, TimeoutError, KeyError, TypeError, ValueError):
        return {"ok": False, "phase": "webui_unreachable_or_invalid"}
    finally:
        if credential:
            try:
                request(base, "/api/auth/logout", {}, credential)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    result = status(args.url)
    print(json.dumps(result, sort_keys=True, ensure_ascii=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
