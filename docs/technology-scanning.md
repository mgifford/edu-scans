---
title: Technology Scanning
layout: page
---

<!-- TECH_STATS_START -->

_Stats as of 2026-04-24 05:59 UTC — last scan: 2026-04-24_

**37** scan batches run

**37,578** of **82,714** available pages scanned (**45.4%** coverage)
**34,470** pages with technology detections (**91.7%** of scanned)
**373** unique technologies identified

---

## Technology Scan by Country

| Country | URLs Scanned | Pages with Detections | Available | Last Scan |
|---------|-------------|----------------------|-----------|----------|
| Austria | 821 | 790 | 821 | 2026-04-17 |
| Belgium | 1,309 | 1,220 | 1,309 | 2026-04-17 |
| Bulgaria | 291 | 262 | 291 | 2026-04-17 |
| Croatia | 233 | 230 | 233 | 2026-04-17 |
| Czechia | 843 | 800 | 843 | 2026-04-17 |
| Denmark | 1,521 | 1,493 | 1,521 | 2026-04-22 |
| Estonia | 396 | 350 | 396 | 2026-04-17 |
| Finland | 180 | 168 | 180 | 2026-04-17 |
| France | 2,826 | 2,501 | 10,007 | 2026-04-22 |
| Germany | 6,555 | 6,441 | 6,555 | 2026-04-23 |
| Greece | 1,748 | 1,617 | 1,748 | 2026-04-18 |
| Hungary | 390 | 349 | 390 | 2026-04-18 |
| Iceland | 139 | 135 | 139 | 2026-04-18 |
| Ireland | 522 | 492 | 522 | 2026-04-23 |
| Italy | 4,701 | 4,244 | 5,338 | 2026-04-23 |
| Latvia | 802 | 762 | 802 | 2026-04-18 |
| Lithuania | 120 | 108 | 120 | 2026-04-18 |
| Luxembourg | 571 | 264 | 571 | 2026-04-18 |
| Malta | 608 | 594 | 608 | 2026-04-18 |
| Netherlands | 937 | 910 | 937 | 2026-04-18 |
| Norway | 239 | 233 | 239 | 2026-04-18 |
| Poland | 2,695 | 2,498 | 14,938 | 2026-04-24 |
| Portugal | 2,239 | 1,792 | 3,503 | 2026-04-19 |
| Cyprus | 24 | 24 | 24 | 2026-04-20 |
| Romania | 533 | 227 | 799 | 2026-04-20 |
| Slovakia | 434 | 412 | 434 | 2026-04-21 |
| Slovenia | 200 | 187 | 200 | 2026-04-21 |
| Spain | 1,748 | 1,543 | 6,069 | 2026-04-21 |
| Sweden | 1,558 | 1,480 | 1,558 | 2026-04-21 |
| Switzerland | 2,117 | 2,080 | 2,117 | 2026-04-21 |
| United Kingdom | 278 | 264 | 19,502 | 2026-04-21 |

> Hover or focus any non-zero country-table count to preview matching pages. Activate the number to keep the preview open and download a CSV for that country and metric from [Download machine-readable technology data (JSON)](technology-data.json).

---

### Top Technologies

| # | Technology | Pages | Categories |
|--:|-----------|------:|-----------|
| 1 | jQuery | **18,995** | JavaScript libraries |
| 2 | PHP | **11,020** | Programming languages |
| 3 | Apache | **10,920** | Web servers |
| 4 | Bootstrap | **9,214** | UI frameworks |
| 5 | Font Awesome | **7,476** | Font scripts |
| 6 | Google Font API | **6,160** | Font scripts |
| 7 | Nginx | **6,044** | Reverse proxies, Web servers |
| 8 | MySQL | **5,493** | Databases |
| 9 | WordPress | **5,451** | Blogs, CMS |
| 10 | jQuery Migrate | **4,640** | JavaScript libraries |
| 11 | Windows Server | **3,450** | Operating systems |
| 12 | IIS | **3,402** | Web servers |
| 13 | jQuery UI | **3,339** | JavaScript libraries |
| 14 | Microsoft ASP.NET | **2,964** | Web frameworks |
| 15 | Drupal | **2,661** | CMS |
| 16 | jsDelivr | **2,353** | CDN |
| 17 | Cloudflare | **2,124** | CDN |
| 18 | Google Tag Manager | **2,048** | Tag managers |
| 19 | Lightbox | **1,916** | JavaScript libraries |
| 20 | Slick | **1,899** | JavaScript libraries |

### Top Technology Categories

| # | Category | Pages |
|--:|---------|------:|
| 1 | JavaScript libraries | **37,548** |
| 2 | Web servers | **22,074** |
| 3 | Programming languages | **15,099** |
| 4 | Font scripts | **13,959** |
| 5 | CMS | **12,061** |
| 6 | UI frameworks | **11,164** |
| 7 | Reverse proxies | **6,296** |
| 8 | Operating systems | **6,058** |
| 9 | Databases | **5,759** |
| 10 | Blogs | **5,475** |
| 11 | CDN | **5,271** |
| 12 | Web frameworks | **4,791** |
| 13 | JavaScript frameworks | **3,604** |
| 14 | Caching | **2,299** |
| 15 | Widgets | **2,263** |

📥 Machine-readable results: [Download machine-readable technology data (JSON)](technology-data.json)

<!-- TECH_STATS_END -->

---

## Overview

The technology scanner fetches each government page and uses
[python-Wappalyzer](https://github.com/chorsley/python-Wappalyzer) to identify
technologies from HTTP response headers and HTML content.  Detected
technologies (CMS, web server, JavaScript frameworks, analytics, etc.) and
their versions are stored in the metadata database and written back into an
annotated `*_tech.toon` TOON file.

Scans run **automatically every 6 hours** via GitHub Actions so that the full
set of URLs across all countries can be covered gradually without overloading
government servers.

---

## Usage

### Scan a single country

```bash
python3 -m src.cli.scan_technology --country ICELAND --rate-limit 2
```

### Scan all countries

```bash
python3 -m src.cli.scan_technology --all --rate-limit 2
```

### Scan all countries with a runtime cap (recommended for CI)

```bash
python3 -m src.cli.scan_technology --all --max-runtime 110 --rate-limit 2.0
```

### Command-line options

| Option | Default | Description |
|---|---|---|
| `--country CODE` | — | Country code to scan (e.g. `FRANCE`, `ICELAND`) |
| `--all` | — | Scan all countries in the TOON directory |
| `--toon-dir PATH` | `data/toon-seeds/countries` | Directory with `.toon` seed files |
| `--rate-limit N` | `2.0` | Maximum HTTP requests per second |
| `--max-runtime N` | `0` (no limit) | Maximum runtime in minutes.  The scanner stops gracefully before this limit so that partial results can be saved.  Set to ~10 minutes less than the GitHub Actions `timeout-minutes` value. |

---

## GitHub Actions

The **Scan Technology Stack** workflow (`.github/workflows/scan-technology.yml`)
runs automatically every 6 hours and can also be triggered manually from the
Actions tab:

1. Go to **Actions → Scan Technology Stack → Run workflow**
2. Optionally enter a country code (leave blank to scan all countries)
3. Optionally adjust the rate limit

Artifacts uploaded after each run:

| Artifact | Contents |
|---|---|
| `tech-scan-<run_number>` | `data/metadata.db`, scan output log, annotated `*_tech.toon` files |
| `validation-metadata` | `data/metadata.db` (shared with URL validation and social media scans) |

---

## Output

### Annotated TOON file

Each page entry in the output `*_tech.toon` file gains a `technologies` field:

```json
{
  "url": "https://example.gov/",
  "is_root_page": true,
  "technologies": {
    "Nginx": { "versions": ["1.24"], "categories": ["Web servers"] },
    "WordPress": { "versions": ["6.2"], "categories": ["CMS", "Blogs"] }
  }
}
```

If detection failed for a URL, a `tech_error` field is added instead:

```json
{
  "url": "https://unreachable.gov/",
  "tech_error": "Connection error: ..."
}
```

### Database table

Results are stored in the `url_tech_results` table:

| Column | Type | Description |
|---|---|---|
| `url` | TEXT | Page URL |
| `country_code` | TEXT | Country identifier |
| `scan_id` | TEXT | Unique scan run ID |
| `technologies` | TEXT | JSON object of detected technologies |
| `error_message` | TEXT | Error message (if detection failed) |
| `scanned_at` | TEXT | ISO-8601 timestamp |

Query example:

```sql
SELECT url, technologies
FROM url_tech_results
WHERE country_code = 'ICELAND'
ORDER BY scanned_at DESC;
```

---

## Architecture

```mermaid
flowchart TD
    A["scan-technology.yml\n(GitHub Actions — every 6 hours)"]
    A --> B["scan_technology.py (CLI)"]
    B --> C["TechScanner.scan_country()"]
    C --> D["TechDetector.detect_urls_batch()"]
    D --> E["For each URL"]
    E --> F["httpx.get() → HTML + headers"]
    F --> G["Wappalyzer.analyze_with_versions_and_categories()"]
    G --> H["Save to url_tech_results table\n(incremental, per URL)"]
    H --> I["Write *_tech.toon output file"]
```

---

## Notes

- **Rate limiting** is applied between requests to avoid overloading government
  servers.  The default is 2 requests per second.
- Technology fingerprinting is best-effort; some sites may return no detections
  if they use custom or obfuscated stacks.
- Unlike the URL validator, failed tech scans do **not** mark a URL for removal
  — errors are recorded but the URL is kept in future scan cycles.
- Results are persisted **incrementally** (one URL at a time) so that partial
  results are preserved even if the GitHub Actions job times out.
- The `*_tech.toon` output files are excluded from version control (see
  `.gitignore`).
