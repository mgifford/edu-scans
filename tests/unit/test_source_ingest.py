from pathlib import Path

from src.services.source_ingest import SourceIngestor


def test_ingest_csv_accepts_and_rejects(tmp_path: Path):
    csv_file = tmp_path / "sample.csv"
    csv_file.write_text(
        "country,gov_domain\n"
        "FR,service-public.fr\n"
        "FR,\n",
        encoding="utf-8",
    )

    ingestor = SourceIngestor(source_type="official")
    records, stats = ingestor.ingest_csv(csv_file, "https://example.test/list.csv")

    assert stats.accepted == 1
    assert stats.rejected == 1
    assert records[0].canonical_hostname == "service-public.fr"


def test_ingest_urls_requires_provenance():
    ingestor = SourceIngestor(source_type="curated")
    records, stats = ingestor.ingest_urls("DE", ["https://bund.de"], "")

    assert records == []
    assert stats.accepted == 0
    assert stats.rejected == 1
