import re
import subprocess
from envfile import read_env


def git(*args):
    return subprocess.check_output(["git", *args])


secrets = [v.encode() for k, v in read_env().items()
           if v and any(word in k for word in ("PASSWORD", "TOKEN", "SECRET", "API_KEY"))]
tracked = git("ls-files", "-z").decode().split("\0")
for path in tracked:
    if path == ".env" or path.startswith(("runtime/", "backups/")):
        raise SystemExit("AUDIT_FAILED: protected file tracked")
objects = set()
for line in git("rev-list", "--objects", "--all").splitlines():
    objects.add(line.split(b" ", 1)[0].decode())
for oid in objects:
    if git("cat-file", "-t", oid).strip() != b"blob":
        continue
    data = git("cat-file", "blob", oid)
    if any(secret in data for secret in secrets) or re.search(rb"\bsk-[a-zA-Z0-9]{24,}\b", data):
        raise SystemExit("AUDIT_FAILED: secret-like content in Git history (value withheld)")
print("SECRET_AUDIT_OK: tracked paths and all history blobs checked")
