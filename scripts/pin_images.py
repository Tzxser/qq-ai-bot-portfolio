"""Pin already-pulled images by digest in local .env, without printing secrets."""
import subprocess
from envfile import ROOT, read_env, write_env

values = read_env()
docker = ["docker"]
if subprocess.run(docker + ["info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
    docker = ["sudo", "-n", "docker"]
for key in ("NAPCAT_IMAGE", "POSTGRES_IMAGE", "REDIS_IMAGE", "PYTHON_IMAGE"):
    ref = values[key]
    result = subprocess.run(docker + ["image", "inspect", "--format", "{{index .RepoDigests 0}}", ref],
                            capture_output=True, text=True, check=True)
    digest = result.stdout.strip()
    if "@sha256:" not in digest:
        raise SystemExit("Missing image digest: " + key)
    values[key] = digest
write_env(values)
print("IMAGE_DIGESTS_PINNED: 4")
