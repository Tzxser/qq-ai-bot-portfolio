import time
from types import SimpleNamespace
import pytest


@pytest.fixture
def settings():
    return SimpleNamespace(api_key="test-only-key", base_url="https://example.invalid", model="test-model",
        onebot_token="test-only-token", app_secret="test-only-app-secret", max_pending=4,
        send_interval=0, max_input=4000, max_output=2000, group_enabled=False, allow_private=True,
        llm_timeout=1, llm_attempts=3, context_turns=8, context_chars=16000)


@pytest.fixture
def event():
    return {"post_type": "message", "message_type": "private", "sub_type": "friend",
        "self_id": 10001, "user_id": 20002, "message_id": 123, "time": int(time.time()),
        "message": [{"type": "text", "data": {"text": "你好"}}]}
