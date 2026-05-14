---
title: Technology Scanning
layout: page
---

<!-- TECH_STATS_START -->

_Stats as of 2026-05-14 06:24 UTC — last scan: 2026-05-14_

**11** scan batches run

**7,158** of **7,626** available pages scanned (**93.9%** coverage)
**6,214** pages with technology detections (**86.8%** of scanned)
**296** unique technologies identified

---

## Technology Scan by Country

| Country | URLs Scanned | Pages with Detections | Available | Last Scan |
|---------|-------------|----------------------|-----------|----------|
| Usa Edu Master | 3,749 | 2,818 | 3,763 | 2026-05-13 |
| Usa Edu Master Subdomains | 4,442 | 4,148 | 3,763 | 2026-05-14 |
| Usa Edu Top100 | 100 | 89 | 100 | 2026-05-13 |

> Hover or focus any non-zero country-table count to preview matching pages. Activate the number to keep the preview open and download a CSV for that country and metric from [Download machine-readable technology data (JSON)](technology-data.json).

---

### Top Technologies

| # | Technology | Pages | Categories |
|--:|-----------|------:|-----------|
| 1 | jQuery | **3,690** | JavaScript libraries |
| 2 | Google Tag Manager | **2,663** | Tag managers |
| 3 | PHP | **2,556** | Programming languages |
| 4 | Font Awesome | **2,461** | Font scripts |
| 5 | Google Font API | **2,137** | Font scripts |
| 6 | Bootstrap | **1,743** | UI frameworks |
| 7 | Apache | **1,614** | Web servers |
| 8 | MySQL | **1,414** | Databases |
| 9 | WordPress | **1,410** | Blogs, CMS |
| 10 | Nginx | **1,298** | Reverse proxies, Web servers |
| 11 | Cloudflare | **1,235** | CDN |
| 12 | jQuery Migrate | **1,168** | JavaScript libraries |
| 13 | jsDelivr | **863** | CDN |
| 14 | Windows Server | **759** | Operating systems |
| 15 | IIS | **751** | Web servers |
| 16 | Varnish | **656** | Caching |
| 17 | Microsoft ASP.NET | **593** | Web frameworks |
| 18 | Slick | **581** | JavaScript libraries |
| 19 | Amazon Web Services | **576** | PaaS |
| 20 | Yoast SEO | **531** | SEO |
| 21 | jQuery UI | **510** | JavaScript libraries |
| 22 | Modernizr | **484** | JavaScript libraries |
| 23 | Drupal | **477** | CMS |
| 24 | YouTube | **436** | Video players |
| 25 | WP Engine | **395** | PaaS |
| 26 | MariaDB | **330** | Databases |
| 27 | Pantheon | **330** | PaaS |
| 28 | Lightbox | **323** | JavaScript libraries |
| 29 | animate.css | **305** | UI frameworks |
| 30 | Amazon Cloudfront | **301** | CDN |

### Top Technology Categories

| # | Category | Pages |
|--:|---------|------:|
| 1 | JavaScript libraries | **7,862** |
| 2 | Font scripts | **4,648** |
| 3 | Web servers | **4,185** |
| 4 | Programming languages | **2,897** |
| 5 | Tag managers | **2,674** |
| 6 | CDN | **2,563** |
| 7 | UI frameworks | **2,285** |
| 8 | CMS | **2,132** |
| 9 | Databases | **2,033** |
| 10 | PaaS | **1,726** |
| 11 | Blogs | **1,451** |
| 12 | Reverse proxies | **1,385** |
| 13 | Operating systems | **1,109** |
| 14 | Caching | **980** |
| 15 | Web frameworks | **766** |

📥 Machine-readable results: [Download machine-readable technology data (JSON)](technology-data.json) · [Download as CSV](technology-data.csv)

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
set of URLs across all seed files can be covered gradually without overloading
government servers.

---

## Usage

### Scan a single seed

```bash
python3 -m src.cli.scan_technology --country USA_EDU_MASTER --rate-limit 2
```

### Scan all seed files

```bash
python3 -m src.cli.scan_technology --all --rate-limit 2
```

### Scan all seed files with a runtime cap (recommended for CI)

```bash
python3 -m src.cli.scan_technology --all --max-runtime 110 --rate-limit 2.0
```

### Command-line options

| Option | Default | Description |
|---|---|---|
| `--country CODE` | — | Seed code to scan (e.g. `USA_EDU_MASTER`) |
| `--all` | — | Scan all seed files in the TOON directory |
| `--toon-dir PATH` | `data/toon-seeds` | Directory with `.toon` seed files |
| `--rate-limit N` | `2.0` | Maximum HTTP requests per second |
| `--max-runtime N` | `0` (no limit) | Maximum runtime in minutes.  The scanner stops gracefully before this limit so that partial results can be saved.  Set to ~10 minutes less than the GitHub Actions `timeout-minutes` value. |

---

## GitHub Actions

The **Scan Technology Stack** workflow (`.github/workflows/scan-technology.yml`)
runs automatically every 6 hours and can also be triggered manually from the
Actions tab:

1. Go to **Actions → Scan Technology Stack → Run workflow**
2. Optionally enter a seed code (leave blank to scan all seed files)
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
| `country_code` | TEXT | Legacy field name for seed identifier (e.g. `USA_EDU_MASTER`) |
| `scan_id` | TEXT | Unique scan run ID |
| `technologies` | TEXT | JSON object of detected technologies |
| `error_message` | TEXT | Error message (if detection failed) |
| `scanned_at` | TEXT | ISO-8601 timestamp |

Query example:

```sql
SELECT url, technologies
FROM url_tech_results
WHERE country_code = 'USA_EDU_MASTER'
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
