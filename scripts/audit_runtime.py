import json
import re
import subprocess
from envfile import ROOT

ids = subprocess.check_output(["bash", str(ROOT / "scripts/compose.sh"), "ps", "-aq"], text=True).split()
docker = ["docker"]
if subprocess.run(docker + ["info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
    docker = ["sudo", "-n", "docker"]
if len(ids) != 4:
    raise SystemExit("AUDIT_FAILED: expected four containers")
data = json.loads(subprocess.check_output(docker + ["inspect", *ids]))
for item in data:
    name = item["Config"]["Labels"]["com.docker.compose.service"]
    assert item["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped", name
    bindings = item["HostConfig"].get("PortBindings") or {}
    if name == "napcat":
        assert bindings == {"6099/tcp": [{"HostIp": "127.0.0.1", "HostPort": "6099"}]}
        assert item["HostConfig"]["LogConfig"]["Type"] == "none"
    else:
        assert not bindings, name
    if name in ("postgres", "redis", "napcat"):
        assert any(m["Type"] == "volume" for m in item["Mounts"]), name
    print(name + ": restart/exposure/persistence OK; health=" + item["State"].get("Health", {}).get("Status", "none"))
config = ROOT / "runtime" / "napcat" / "config"
for path in config.glob("*.json"):
    assert path.stat().st_mode & 0o777 == 0o600, "NapCat config permissions"
    if path.name == "napcat.json" or re.fullmatch(r"napcat_[0-9]+\.json", path.name):
        value = json.loads(path.read_text())
        assert value.get("fileLog") is False and value.get("consoleLog") is False, "NapCat log config"
print("NAPCAT_CONFIG_AUDIT_OK")
print("RUNTIME_AUDIT_OK")
