from src.lib.logging import configure_logging, get_logger


def test_logger_contains_context_fields(caplog):
    configure_logging("INFO")
    logger = get_logger("tests", scan_id="scan-1", country_code="FR", hostname="service-public.fr")

    with caplog.at_level("INFO"):
        logger.info("hello")

    assert any("hello" in rec.message for rec in caplog.records)
    assert any(getattr(rec, "scan_id", "") == "scan-1" for rec in caplog.records)
