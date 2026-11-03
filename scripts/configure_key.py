import getpass
import sys
import warnings

from envfile import read_env, write_env

if not sys.stdin.isatty():
    raise SystemExit("Run interactively in your server terminal")
warnings.simplefilter("error", getpass.GetPassWarning)
values = read_env()
if not values:
    raise SystemExit("Run setup.py first")
try:
    key = getpass.getpass("DeepSeek API Key (hidden input): ").strip()
except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
    raise SystemExit("Input cancelled; no change") from None
if not key or any(c.isspace() for c in key):
    raise SystemExit("Empty or invalid input; no change")
values["DEEPSEEK_API_KEY"] = key
write_env(values)
print("DEEPSEEK_API_KEY: present; value not displayed")
