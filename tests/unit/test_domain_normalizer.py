from src.services.domain_normalizer import are_same_host, normalize_domain


def test_normalize_domain_from_url_and_aliases():
    normalized = normalize_domain(
        "https://Bürger.DE/path?q=1",
        aliases=["http://xn--brger-kva.de", "buerger.de"],
    )

    assert normalized.canonical_hostname == "xn--brger-kva.de"
    assert "buerger.de" in normalized.aliases


def test_are_same_host_comparison():
    assert are_same_host("https://example.gov/path", "example.gov")
    assert not are_same_host("service.gov", "other.gov")
