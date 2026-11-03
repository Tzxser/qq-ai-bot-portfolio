"""Exercise backup completion and cleanup without touching Docker or live data."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Linux backup script")


@pytest.mark.parametrize("failure", ["", "dump", "snapshot"])
def test_backup_resumes_services_and_checksums_secrets(tmp_path, failure):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts/backup.sh", scripts / "backup.sh")
    (tmp_path / ".env").write_text("TEST_ONLY='not-a-credential'\n")
    config = tmp_path / "runtime/napcat/config"
    config.mkdir(parents=True)
    (config / "webui.json").write_text("{}")
    (scripts / "compose.sh").write_text("""#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> calls.txt
case "$1" in
    stop|start|pause|unpause) exit 0 ;;
    ps) printf 'test-napcat-container' ;;
    exec)
        if [[ "$*" == *pg_dump* ]]; then
            [[ "$BACKUP_TEST_FAILURE" != dump ]] || exit 8
            printf 'test dump'
        elif [[ "$*" == *pg_restore* ]]; then cat >/dev/null
        elif [[ "$*" == *dump.rdb* ]]; then printf 'test redis snapshot'
        fi ;;
    *) exit 7 ;;
esac
""")
    commands = tmp_path / "bin"
    commands.mkdir()
    docker = commands / "docker"
    docker.write_text("""#!/usr/bin/env bash
set -eu
case "$1" in
    info) exit 0 ;;
    inspect) printf 'test-image' ;;
    run)
        printf 'snapshot\\n' >> calls.txt
        [[ "$BACKUP_TEST_FAILURE" != snapshot ]] || exit 9
        target=$(find backups -mindepth 1 -maxdepth 1 -type d)
        (umask 077; tar -cf "$target/qq-session.tar" --files-from /dev/null) ;;
    *) exit 7 ;;
esac
""")
    docker.chmod(0o700)
    result = subprocess.run(["bash", "scripts/backup.sh"], cwd=tmp_path,
                            env={**os.environ, "BACKUP_TEST_FAILURE": failure,
                                 "PATH": str(commands) + os.pathsep + os.environ["PATH"]},
                            capture_output=True, text=True, timeout=15)
    calls = (tmp_path / "calls.txt").read_text().splitlines()
    assert "stop bot" in calls and "start bot" in calls
    assert not any(line.startswith(("stop napcat", "restart", "down")) for line in calls)
    if "pause napcat" in calls:
        assert "unpause napcat" in calls
        assert calls.index("unpause napcat") < calls.index("start bot")
    if failure:
        assert result.returncode != 0
        assert "BACKUP_OK" not in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert "BACKUP_OK" in result.stdout
        archive = next((tmp_path / "backups").glob("*/SHA256SUMS"))
        assert ".env" in archive.read_text()
        subprocess.run(["sha256sum", "--check", "SHA256SUMS"], cwd=archive.parent,
                       check=True, capture_output=True)
        assert all(p.stat().st_mode & 0o777 == 0o600 for p in archive.parent.iterdir())
