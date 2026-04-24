"""Source ingestion interfaces for government domain lists."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.lib.errors import IngestionError
from src.services.domain_normalizer import normalize_domain


@dataclass(slots=True)
class SourceRecord:
    country_code: str
    input_hostname: str
    canonical_hostname: str
    source_type: str
    source_reference_url: str
    aliases: list[str]


@dataclass(slots=True)
class IngestionStats:
    accepted: int = 0
    rejected: int = 0


class SourceIngestor:
    """Adapter for ingesting domain records from CSV rows and URL lists."""

    def __init__(self, source_type: str) -> None:
        if source_type not in {"official", "curated", "archive", "other"}:
            raise IngestionError(f"Unsupported source_type: {source_type}")
        self.source_type = source_type

    def _build_record(self, country_code: str, hostname: str, source_reference_url: str) -> SourceRecord:
        if not country_code:
            raise IngestionError("country_code is required")
        if not hostname:
            raise IngestionError("hostname is required")
        if not source_reference_url:
            raise IngestionError("source_reference_url is required")

        normalized = normalize_domain(hostname)
        if not normalized.canonical_hostname:
            raise IngestionError(f"invalid hostname: {hostname}")

        return SourceRecord(
            country_code=country_code.upper(),
            input_hostname=hostname,
            canonical_hostname=normalized.canonical_hostname,
            source_type=self.source_type,
            source_reference_url=source_reference_url,
            aliases=normalized.aliases,
        )

    def ingest_csv(self, csv_path: Path, source_reference_url: str) -> tuple[list[SourceRecord], IngestionStats]:
        records: list[SourceRecord] = []
        stats = IngestionStats()
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                country_code = (row.get("country") or row.get("country_code") or "").strip()
                hostname = (row.get("gov_domain") or row.get("domain") or row.get("hostname") or "").strip()
                try:
                    records.append(self._build_record(country_code, hostname, source_reference_url))
                    stats.accepted += 1
                except IngestionError:
                    stats.rejected += 1
        return records, stats

    def ingest_urls(
        self,
        country_code: str,
        urls: Iterable[str],
        source_reference_url: str,
    ) -> tuple[list[SourceRecord], IngestionStats]:
        records: list[SourceRecord] = []
        stats = IngestionStats()
        for url in urls:
            try:
                records.append(self._build_record(country_code, url, source_reference_url))
                stats.accepted += 1
            except IngestionError:
                stats.rejected += 1
        return records, stats
