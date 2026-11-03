import logging
import re


class RedactingFormatter(logging.Formatter):
    def __init__(self, secrets):
        super().__init__("%(asctime)s %(levelname)s %(message)s")
        self.secrets = [s for s in secrets if s]

    def format(self, record):
        rendered = super().format(record)
        for secret in self.secrets:
            rendered = rendered.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)(bearer\s+)\S+", r"\1[REDACTED]", rendered)


def configure(settings):
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter([settings.api_key, settings.onebot_token,
        settings.postgres_password, settings.redis_password, settings.app_secret]))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    logging.getLogger("aiohttp.access").disabled = True
