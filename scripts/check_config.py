import os
import sys
from envfile import ROOT, read_env

sys.path.insert(0, str(ROOT))
from bot.config import ConfigError, Settings

try:
    os.environ.update(read_env())
    s = Settings.from_env()
except (ConfigError, ValueError) as exc:
    print(str(exc))
    raise SystemExit(1)
print("CONFIG_OK; DEEPSEEK_API_KEY=" + ("present" if s.api_key else "missing"))
if "--require-key" in sys.argv and not s.api_key:
    raise SystemExit(2)
