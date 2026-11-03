import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


class ConfigError(ValueError):
    pass


@dataclass(repr=False)
class Settings:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    onebot_token: str = field(repr=False)
    postgres_password: str = field(repr=False)
    redis_password: str = field(repr=False)
    app_secret: str = field(repr=False)
    pg_host: str = "postgres"
    pg_user: str = "qqbot"
    pg_db: str = "qqbot"
    redis_host: str = "redis"
    group_enabled: bool = False
    allow_private: bool = True
    cooldown: float = 5
    send_interval: float = 1.5
    llm_timeout: float = 45
    llm_attempts: int = 3
    max_input: int = 4000
    max_output: int = 2000
    qq_part_limit: int = 4000
    max_answer_parts: int = 2
    context_turns: int = 8
    context_chars: int = 16000
    retention_days: int = 30
    max_pending: int = 32
    # V2.1 group features are intentionally off until an explicitly authorized
    # group is configured.  Keep group_enabled for backwards compatibility.
    group_features_enabled: bool = False
    allowed_group_ids: tuple[str, ...] = ()
    bot_owner_ids: tuple[str, ...] = ()
    ignore_bot_ids: tuple[str, ...] = ()
    group_welcome_enabled: bool = False
    association_lead_enabled: bool = False
    association_lead_target_qq: str = ""
    group_send_interval: float = 3.0
    group_user_cooldown: float = 6.0
    group_queue_size: int = 5
    handoff_requester_cooldown: float = 1800.0
    handoff_group_cooldown: float = 600.0
    handoff_global_per_hour: int = 3
    welcome_window: float = 20.0
    welcome_stale_seconds: float = 180.0
    group_user_per_minute: int = 4
    group_user_per_hour: int = 30
    group_per_minute: int = 10
    global_llm_concurrency: int = 2
    group_daily_requests: int = 300
    group_daily_input_tokens: int = 1000000
    group_daily_generated_tokens: int = 200000
    group_recent_turns: int = 3
    group_history_chars: int = 6400
    group_idle_ttl: float = 1800.0
    group_absolute_ttl: float = 7200.0
    group_llm_attempts: int = 2
    group_max_output: int = 800
    group_input_token_cap: int = 6000
    recovery_local_enabled: bool = True
    recovery_history_enabled: bool = False
    recovery_pending_ttl: int = 7200
    recovery_automatic_age: int = 900
    recovery_max_answer_topics: int = 3
    recovery_max_user_topics: int = 1
    recovery_send_interval: float = 10.0
    recovery_max_answer_parts: int = 2

    @classmethod
    def from_env(cls):
        def val(key, default=""):
            return os.environ.get(key, default).strip()

        def number(key, default, low, high, cast=int):
            try:
                n = cast(val(key, str(default)))
                if not low <= n <= high:
                    raise ValueError
                return n
            except ValueError:
                raise ConfigError(f"Invalid {key}") from None

        def boolean(key, default):
            s = val(key, str(default)).lower()
            if s not in ("true", "false"):
                raise ConfigError(f"Invalid {key}")
            return s == "true"

        def ids(key):
            raw = val(key)
            if not raw:
                return ()
            values = tuple(item.strip() for item in raw.split(",") if item.strip())
            if any(not item.isdecimal() or int(item) <= 0 for item in values):
                raise ConfigError(f"Invalid {key}")
            return values

        secrets = {}
        for key in ("ONEBOT_ACCESS_TOKEN", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "APP_SECRET"):
            s = val(key)
            if len(s) < 32 or any(c.isspace() for c in s):
                raise ConfigError(f"Missing or weak {key}")
            secrets[key] = s
        if val("LLM_PROVIDER", "deepseek") != "deepseek":
            raise ConfigError("Unsupported LLM_PROVIDER")
        base = val("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        url = urlsplit(base)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ConfigError("DEEPSEEK_BASE_URL must be a clean HTTPS endpoint")
        model = val("DEEPSEEK_MODEL")
        if not model:
            raise ConfigError("Missing DEEPSEEK_MODEL")
        # New configuration wins when present; old GROUP_ENABLED remains a
        # compatible alias for existing deployments and test fixtures.
        group_flag = boolean("GROUP_FEATURES_ENABLED", boolean("GROUP_ENABLED", False))
        lead_target = val("ASSOCIATION_LEAD_TARGET_QQ")
        if lead_target and (not lead_target.isdecimal() or int(lead_target) <= 0):
            raise ConfigError("Invalid ASSOCIATION_LEAD_TARGET_QQ")
        return cls(
            api_key=val("DEEPSEEK_API_KEY"), base_url=base, model=model,
            onebot_token=secrets["ONEBOT_ACCESS_TOKEN"],
            postgres_password=secrets["POSTGRES_PASSWORD"],
            redis_password=secrets["REDIS_PASSWORD"], app_secret=secrets["APP_SECRET"],
            pg_host=val("POSTGRES_HOST", "postgres"), pg_user=val("POSTGRES_USER", "qqbot"),
            pg_db=val("POSTGRES_DB", "qqbot"), redis_host=val("REDIS_HOST", "redis"),
            group_enabled=group_flag, allow_private=boolean("ALLOW_PRIVATE", True),
            cooldown=number("USER_COOLDOWN_SECONDS", 5, 1, 3600, float),
            send_interval=number("GLOBAL_SEND_INTERVAL_SECONDS", 1.5, 1, 60, float),
            llm_timeout=number("LLM_TIMEOUT_SECONDS", 45, 1, 120, float),
            llm_attempts=number("LLM_MAX_ATTEMPTS", 3, 1, 4),
            max_input=number("MAX_INPUT_CHARS", 4000, 1, 16000),
            max_output=number("MAX_OUTPUT_CHARS", 2000, 1, 4000),
            qq_part_limit=number("QQ_PART_LIMIT", 4000, 500, 4000),
            max_answer_parts=number("MAX_ANSWER_PARTS", 2, 1, 2),
            context_turns=number("CONTEXT_TURNS", 8, 1, 32),
            context_chars=number("CONTEXT_MAX_CHARS", 16000, 100, 64000),
            retention_days=number("HISTORY_RETENTION_DAYS", 30, 1, 365),
            max_pending=number("MAX_PENDING_MESSAGES", 32, 1, 128),
            group_features_enabled=group_flag,
            allowed_group_ids=ids("ALLOWED_GROUP_IDS"),
            bot_owner_ids=ids("BOT_OWNER_IDS"),
            ignore_bot_ids=ids("IGNORE_BOT_IDS"),
            group_welcome_enabled=boolean("WELCOME_ENABLED", False),
            association_lead_enabled=boolean("ASSOCIATION_LEAD_ENABLED", False),
            association_lead_target_qq=lead_target,
            group_send_interval=number("GROUP_SEND_INTERVAL_SECONDS", 3, 1, 60, float),
            group_user_cooldown=number("GROUP_USER_COOLDOWN_SECONDS", 6, 1, 3600, float),
            group_queue_size=number("GROUP_QUEUE_SIZE", 5, 1, 64),
            handoff_requester_cooldown=number("HANDOFF_REQUESTER_COOLDOWN_SECONDS", 1800, 1, 86400, float),
            handoff_group_cooldown=number("HANDOFF_GROUP_COOLDOWN_SECONDS", 600, 1, 86400, float),
            handoff_global_per_hour=number("HANDOFF_GLOBAL_PER_HOUR", 3, 1, 100),
            welcome_window=number("WELCOME_WINDOW_SECONDS", 20, 1, 120, float),
            welcome_stale_seconds=number("WELCOME_STALE_SECONDS", 180, 30, 3600, float),
            group_user_per_minute=number("GROUP_USER_LLM_PER_MINUTE", 4, 1, 100),
            group_user_per_hour=number("GROUP_USER_LLM_PER_HOUR", 30, 1, 1000),
            group_per_minute=number("GROUP_LLM_PER_MINUTE", 10, 1, 1000),
            global_llm_concurrency=number("GLOBAL_LLM_CONCURRENCY", 2, 1, 32),
            group_daily_requests=number("GROUP_DAILY_REQUEST_ATTEMPTS", 300, 1, 100000),
            group_daily_input_tokens=number("GROUP_DAILY_INPUT_TOKENS", 1000000, 1000, 100000000),
            group_daily_generated_tokens=number("GROUP_DAILY_GENERATED_TOKENS", 200000, 1000, 100000000),
            group_recent_turns=number("GROUP_RECENT_TURNS", 3, 1, 16),
            group_history_chars=number("GROUP_HISTORY_CHARS", 6400, 100, 30000),
            group_idle_ttl=number("GROUP_IDLE_TTL_SECONDS", 1800, 60, 86400, float),
            group_absolute_ttl=number("GROUP_ABSOLUTE_TTL_SECONDS", 7200, 300, 172800, float),
            group_llm_attempts=number("GROUP_LLM_MAX_ATTEMPTS", 2, 1, 2),
            group_max_output=number("GROUP_MAX_OUTPUT_TOKENS", 800, 100, 1600),
            group_input_token_cap=number("GROUP_INPUT_TOKEN_CAP", 6000, 500, 10000),
            recovery_local_enabled=boolean("RECOVERY_LOCAL_ENABLED", True),
            recovery_history_enabled=boolean("RECOVERY_HISTORY_ENABLED", False),
            recovery_pending_ttl=number("RECOVERY_PENDING_TTL_SECONDS", 7200, 300, 172800),
            recovery_automatic_age=number("RECOVERY_AUTOMATIC_AGE_SECONDS", 900, 60, 7200),
            recovery_max_answer_topics=number("RECOVERY_MAX_TOPICS_PER_EPOCH", 3, 1, 20),
            recovery_max_user_topics=number("RECOVERY_MAX_TOPICS_PER_USER_EPOCH", 1, 1, 5),
            recovery_send_interval=number("RECOVERY_SEND_INTERVAL_SECONDS", 10, 3, 120, float),
            recovery_max_answer_parts=number("RECOVERY_MAX_ANSWER_PARTS", 2, 1, 2),
        )
