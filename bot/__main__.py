from aiohttp import web
from bot.app import create_app
from bot.config import ConfigError

try:
    web.run_app(create_app(), host="0.0.0.0", port=8080, access_log=None,
                shutdown_timeout=210, print=None)
except ConfigError as exc:
    raise SystemExit(str(exc)) from None
except Exception as exc:
    raise SystemExit("Bot startup/runtime failure: " + type(exc).__name__) from None
