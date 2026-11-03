"""Simple quoted dotenv reader/writer; never execute .env as shell code."""
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_env(path=None):
    path = Path(path or ROOT / ".env")
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError("Invalid environment file format")
        if len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        result[key] = value
    return result


def write_env(values, path=None):
    path = Path(path or ROOT / ".env")
    for value in values.values():
        if any(c in value for c in ("'", "\n", "\r", "\x00")):
            raise ValueError("Unsupported environment value characters")
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".env.")
    try:
        os.chmod(temp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
            out.writelines(f"{key}='{value}'\n" for key, value in values.items())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
