import logging
from pathlib import Path
import yaml
from bot.security.logging import RedactingFormatter


def test_log_redaction():
    formatter = RedactingFormatter(["private-test-key"])
    record = logging.LogRecord("test", logging.ERROR, "", 1,
        "failure private-test-key Bearer another-value", (), None)
    output = formatter.format(record)
    assert "private-test-key" not in output and "another-value" not in output


def test_compose_exposure_and_persistence():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    services = compose["services"]
    for name in ("bot", "postgres", "redis"):
        assert not services[name].get("ports")
    assert services["napcat"]["ports"] == ["127.0.0.1:6099:6099"]
    assert compose["networks"]["storage"]["internal"]
    for service in services.values():
        assert service["restart"] == "unless-stopped"
    for name in ("postgres", "redis", "napcat"):
        assert services[name]["volumes"]
    assert ".env" in (root / ".gitignore").read_text().splitlines()
