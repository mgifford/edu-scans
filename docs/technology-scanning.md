---
title: Technology Scanning
layout: page
---

<!-- TECH_STATS_START -->

_Stats as of 2026-06-11 06:53 UTC — last scan: 2026-06-11_

**51** scan batches run

**11,839** of **20,294** available pages scanned (**58.3%** coverage)
**9,688** pages with technology detections (**81.8%** of scanned)
**304** unique technologies identified

---

## Technology Scan by Country

| Country | URLs Scanned | Pages with Detections | Available | Last Scan |
|---------|-------------|----------------------|-----------|----------|
| Usa Edu Master | 3,749 | 2,825 | 3,763 | 2026-06-11 |
| Usa Edu Master Subdomains | 11,833 | 9,674 | 16,431 | 2026-06-07 |
| Usa Edu Top100 | 100 | 89 | 100 | 2026-06-10 |

> Hover or focus any non-zero country-table count to preview matching pages. Activate the number to keep the preview open and download a CSV for that country and metric from [Download machine-readable technology data (JSON)](technology-data.json).

---

### Top Technologies

| # | Technology | Pages | Categories |
|--:|-----------|------:|-----------|
| 1 | jQuery | **4,719** | JavaScript libraries |
| 2 | Font Awesome | **3,140** | Font scripts |
| 3 | Google Tag Manager | **3,118** | Tag managers |
| 4 | PHP | **2,796** | Programming languages |
| 5 | Google Font API | **2,671** | Font scripts |
| 6 | Bootstrap | **2,437** | UI frameworks |
| 7 | Nginx | **2,194** | Reverse proxies, Web servers |
| 8 | Apache | **2,073** | Web servers |
| 9 | Cloudflare | **1,581** | CDN |
| 10 | MySQL | **1,338** | Databases |
| 11 | WordPress | **1,332** | Blogs, CMS |
| 12 | jQuery Migrate | **1,286** | JavaScript libraries |
| 13 | Windows Server | **1,086** | Operating systems |
| 14 | IIS | **1,078** | Web servers |
| 15 | jsDelivr | **1,014** | CDN |
| 16 | Microsoft ASP.NET | **838** | Web frameworks |
| 17 | Amazon Web Services | **825** | PaaS |
| 18 | Varnish | **798** | Caching |
| 19 | jQuery UI | **774** | JavaScript libraries |
| 20 | Slick | **705** | JavaScript libraries |
| 21 | Drupal | **664** | CMS |
| 22 | Modernizr | **649** | JavaScript libraries |
| 23 | YouTube | **482** | Video players |
| 24 | Yoast SEO | **432** | SEO |
| 25 | Amazon Cloudfront | **420** | CDN |
| 26 | Lightbox | **363** | JavaScript libraries |
| 27 | MariaDB | **358** | Databases |
| 28 | Pantheon | **358** | PaaS |
| 29 | animate.css | **327** | UI frameworks |
| 30 | Amazon EC2 | **327** | Web servers |

### Top Technology Categories

| # | Category | Pages |
|--:|---------|------:|
| 1 | JavaScript libraries | **9,828** |
| 2 | Web servers | **6,173** |
| 3 | Font scripts | **5,893** |
| 4 | Programming languages | **3,300** |
| 5 | CDN | **3,218** |
| 6 | Tag managers | **3,125** |
| 7 | UI frameworks | **3,100** |
| 8 | Reverse proxies | **2,319** |
| 9 | CMS | **2,270** |
| 10 | Databases | **2,086** |
| 11 | PaaS | **1,785** |
| 12 | Operating systems | **1,571** |
| 13 | Blogs | **1,377** |
| 14 | Caching | **1,260** |
| 15 | Web frameworks | **1,075** |

📥 Machine-readable results: [Download machine-readable technology data (JSON)](technology-data.json) · [Download as CSV](technology-data.csv)

<!-- TECH_STATS_END -->

---

## License and Digital Public Goods status (Top Technologies)

To support policy tracking of open source and free software use, this page now
includes machine-readable license metadata for the current **Top Technologies**
list:

- [Download technology license data (JSON)](technology-license-data.json)

Current summary from `technology-license-data.json`:

- **DPGA Registry listed:** Drupal
- **OSI-approved license (yes):** jQuery, PHP, Apache, Bootstrap, MySQL,
  WordPress, Nginx, jQuery Migrate, jQuery UI, Drupal, Yoast SEO
- **Partial/mixed:** Font Awesome, Microsoft ASP.NET, jsDelivr
- **Not OSI-approved (no):** Google Font API, Windows Server, IIS,
  Google Tag Manager, Cloudflare, reCAPTCHA

> Notes:
> - This is a best-effort mapping of detected technology names to primary
>   upstream licenses.
> - Some detections are products/services (not single software packages), so
>   their licensing model can be mixed or proprietary.
> - DPGA status is based on a checked snapshot at generation time and may change.

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
