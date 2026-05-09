---
title: Technology Scanning
layout: page
---

<!-- TECH_STATS_START -->

_Stats as of 2026-05-09 06:05 UTC — last scan: 2026-05-06_

**7** scan batches run

**3,755** of **3,863** available pages scanned (**97.2%** coverage)
**2,817** pages with technology detections (**75.0%** of scanned)
**253** unique technologies identified

---

## Technology Scan by Country

| Country | URLs Scanned | Pages with Detections | Available | Last Scan |
|---------|-------------|----------------------|-----------|----------|
| Usa Edu Master | 3,749 | 2,811 | 3,763 | 2026-05-06 |
| Usa Edu Top100 | 100 | 89 | 100 | 2026-05-06 |

> Hover or focus any non-zero country-table count to preview matching pages. Activate the number to keep the preview open and download a CSV for that country and metric from [Download machine-readable technology data (JSON)](technology-data.json).

---

### Top Technologies

| # | Technology | Pages | Categories |
|--:|-----------|------:|-----------|
| 1 | jQuery | **1,818** | JavaScript libraries |
| 2 | PHP | **1,609** | Programming languages |
| 3 | Google Tag Manager | **1,592** | Tag managers |
| 4 | Font Awesome | **1,245** | Font scripts |
| 5 | Google Font API | **1,120** | Font scripts |
| 6 | MySQL | **920** | Databases |
| 7 | WordPress | **917** | Blogs, CMS |
| 8 | Bootstrap | **779** | UI frameworks |
| 9 | Nginx | **753** | Reverse proxies, Web servers |
| 10 | jQuery Migrate | **735** | JavaScript libraries |
| 11 | Cloudflare | **700** | CDN |
| 12 | Apache | **690** | Web servers |
| 13 | jsDelivr | **418** | CDN |
| 14 | Varnish | **418** | Caching |
| 15 | Yoast SEO | **393** | SEO |
| 16 | Slick | **359** | JavaScript libraries |
| 17 | MariaDB | **294** | Databases |
| 18 | Pantheon | **294** | PaaS |
| 19 | YouTube | **285** | Video players |
| 20 | Windows Server | **278** | Operating systems |
| 21 | IIS | **276** | Web servers |
| 22 | WP Engine | **261** | PaaS |
| 23 | Modernizr | **239** | JavaScript libraries |
| 24 | animate.css | **220** | UI frameworks |
| 25 | Amazon Web Services | **215** | PaaS |
| 26 | Elementor | **212** | Page builders |
| 27 | Drupal | **212** | CMS |
| 28 | OWL Carousel | **197** | Widgets |
| 29 | Lightbox | **196** | JavaScript libraries |
| 30 | reCAPTCHA | **184** | Security |

### Top Technology Categories

| # | Category | Pages |
|--:|---------|------:|
| 1 | JavaScript libraries | **4,110** |
| 2 | Font scripts | **2,384** |
| 3 | Web servers | **1,896** |
| 4 | Programming languages | **1,695** |
| 5 | Tag managers | **1,599** |
| 6 | Databases | **1,341** |
| 7 | CDN | **1,304** |
| 8 | CMS | **1,287** |
| 9 | UI frameworks | **1,128** |
| 10 | PaaS | **981** |
| 11 | Blogs | **949** |
| 12 | Reverse proxies | **760** |
| 13 | Caching | **640** |
| 14 | Operating systems | **429** |
| 15 | Miscellaneous | **420** |

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
