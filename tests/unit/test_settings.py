from src.lib.errors import ConfigError
from src.lib.settings import load_settings


def test_load_settings_defaults(monkeypatch):
    monkeypatch.delenv("SCHEDULER_CADENCE", raising=False)
    monkeypatch.delenv("CRAWL_RATE_LIMIT_PER_HOST", raising=False)
    monkeypatch.delenv("CRAWL_TIMEOUT_SECONDS", raising=False)

    settings = load_settings()

    assert settings.scheduler_cadence == "monthly"
    assert settings.crawl_rate_limit_per_host == 0.5
    assert settings.crawl_timeout_seconds == 20


def test_load_settings_invalid_cadence(monkeypatch):
    monkeypatch.setenv("SCHEDULER_CADENCE", "yearly")

    try:
        load_settings()
        assert False, "Expected ConfigError"
    except ConfigError as exc:
        assert "SCHEDULER_CADENCE" in str(exc)
