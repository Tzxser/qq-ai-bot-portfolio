"""Restore into a uniquely named disposable database, never into the live database."""
import json
import subprocess
import sys
import uuid
from pathlib import Path
from envfile import ROOT, read_env

archive = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else None
if archive is None or not archive.is_file() or ROOT.joinpath("backups").resolve() not in archive.parents:
    raise SystemExit("Usage: python3 scripts/verify_backup.py backups/<timestamp>/postgres.dump")
user = read_env().get("POSTGRES_USER", "qqbot")
database = "qqbot_verify_" + uuid.uuid4().hex
command = ["bash", str(ROOT / "scripts/compose.sh"), "exec", "-T", "postgres"]


def run(*args, stdin=None):
    return subprocess.run(command + list(args), stdin=stdin, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=True)


created = False
try:
    run("createdb", "-U", user, database)
    created = True
    with archive.open("rb") as source:
        run("pg_restore", "-U", user, "-d", database, "--exit-on-error", "--no-owner", "--no-privileges", stdin=source)
    version = run("psql", "-U", user, "-d", database, "-Atc", "SELECT max(version) FROM schema_versions").stdout.strip()
    if version != b"1":
        raise RuntimeError("Unexpected schema version")
    print("BACKUP_RESTORE_VERIFIED: isolated database restored with schema v1")
except Exception as exc:
    print("BACKUP_RESTORE_FAILED: " + type(exc).__name__)
    raise SystemExit(1)
finally:
    if created:
        run("dropdb", "-U", user, database)
