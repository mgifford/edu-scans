---
title: Third-Party JavaScript
layout: page
---

<!-- THIRD_PARTY_JS_STATS_START -->

_Stats as of 2026-08-19 05:45 UTC — last scan: 2026-08-19_

**3** scan batches run

**2,964** of **19,984** available pages scanned (**14.8%** coverage)
**2,216** of **2,964** scanned pages were reachable (**74.8%**)
**1,405** reachable pages loaded at least one third-party script (**63.4%** of reachable)
**2,657** known third-party service loads identified
**24** unique known services across **17** categories

---

## Third-Party JavaScript by Country

| Country | Scanned | Available | Reachable | URLs with 3rd-Party JS | Known Service Loads | Last Scan |
|---------|---------|-----------|-----------|------------------------|--------------------|----------|
| Usa Edu Master | 2,964 | 3,763 | 2,216 | 1,405 | 2,657 | 2026-08-19 |

> Hover or focus any non-zero country-table count to preview matching pages. Activate the number to keep the preview open and download a CSV for that country and metric from [Download machine-readable third-party tools data (JSON)](third-party-tools-data.json).

---

### Top Third-Party Services

| # | Service | Loads |
|--:|---------|------:|
| 1 | cdnjs (Cloudflare CDN) | **468** |
| 2 | Google Analytics (GA4) | **465** |
| 3 | jsDelivr CDN | **381** |
| 4 | Google Tag Manager | **357** |
| 5 | jQuery | **231** |
| 6 | Font Awesome | **175** |
| 7 | Google Hosted Libraries | **149** |
| 8 | Google reCAPTCHA | **122** |
| 9 | unpkg CDN | **102** |
| 10 | Bootstrap | **53** |
| 11 | HubSpot | **30** |
| 12 | Sentry | **28** |
| 13 | OneTrust | **24** |
| 14 | Adobe Dynamic Tag Management / Launch | **21** |
| 15 | Facebook Pixel | **14** |
| 16 | Cookiebot | **12** |
| 17 | Cloudflare Turnstile / Challenge | **8** |
| 18 | Stripe | **5** |
| 19 | Zendesk | **4** |
| 20 | Usercentrics | **3** |

### Top Service Categories

| # | Category | Loads |
|--:|----------|------:|
| 1 | CDN | **1,100** |
| 2 | Analytics | **505** |
| 3 | JavaScript Library | **380** |
| 4 | Tag Manager | **378** |
| 5 | Icon Library | **175** |
| 6 | Security | **130** |
| 7 | CAPTCHA | **122** |
| 8 | UI Framework | **53** |
| 9 | Cookie Consent | **39** |
| 10 | CRM | **30** |
| 11 | Marketing | **30** |
| 12 | Error Tracking | **28** |
| 13 | Advertising | **15** |
| 14 | Payments | **5** |
| 15 | Customer Support | **4** |

📥 Machine-readable results: [Download machine-readable third-party tools data (JSON)](third-party-tools-data.json)

<!-- THIRD_PARTY_JS_STATS_END -->

---

## Overview

This scan identifies **third-party JavaScript** loaded by institution websites,
including analytics tags, tag managers, cookie-consent tools, CDNs, customer
support widgets, and other externally hosted scripts.

The goal is to make external dependencies across the current institution dataset easier to inspect. This helps answer questions like:

- Which analytics or advertising vendors appear most often?
- How common are third-party CDNs and consent managers?
- Which seed groups lean more heavily on externally hosted web tooling?

The scanner looks at every `<script src="...">` on a page, excludes
same-origin scripts, and then tries to match known services such as Google Tag
Manager, Google Analytics, Matomo Cloud, OneTrust, Cookiebot, Cloudflare,
Microsoft Clarity, HubSpot, and more.

---

## Why This Matters

Third-party JavaScript can affect:

- **Privacy**: analytics, advertising, and tracking integrations may send data
  to external services.
- **Security**: externally hosted libraries and widgets increase supply-chain
  risk.
- **Resilience**: a page may depend on third-party infrastructure outside the
  control of the institution.
- **Performance**: extra scripts often increase page weight and network cost.

This page gives a dataset-wide view of those dependencies.

---

## Usage

### Scan a single seed

```bash
python3 -m src.cli.scan_third_party_js --country USA_EDU_MASTER --rate-limit 1.0
```

### Scan all seed files

```bash
python3 -m src.cli.scan_third_party_js --all --rate-limit 1.0
```

### Scan all seed files with a runtime cap

```bash
python3 -m src.cli.scan_third_party_js --all --max-runtime 110 --rate-limit 1.0
```

### Command-line options

| Option | Default | Description |
|---|---|---|
| `--country CODE` | — | Seed code to scan (for example `USA_EDU_MASTER`) |
| `--all` | — | Scan all seed files in the TOON directory |
| `--toon-dir PATH` | `data/toon-seeds` | Directory with `.toon` seed files |
| `--rate-limit N` | `1.0` | Maximum HTTP requests per second |
| `--max-runtime N` | `0` (no limit) | Maximum runtime in minutes for graceful CI stops |

---

## GitHub Actions

The **Scan Third-Party JavaScript** workflow
(`.github/workflows/scan-third-party-js.yml`) runs automatically every 6 hours
and can also be triggered manually from the Actions tab.

Artifacts uploaded after each run:

| Artifact | Contents |
|---|---|
| `3pjs-scan-<run_number>` | `data/metadata.db`, scan output log, annotated `*_3pjs.toon` files |
| `validation-metadata` | `data/metadata.db` shared with the other scanners |

---

## Output

### Annotated TOON file

Each page entry in the output `*_3pjs.toon` file gains a `third_party_js`
field:

```json
{
  "url": "https://example.gov/",
  "third_party_js": [
    {
      "src": "https://www.googletagmanager.com/gtm.js?id=GTM-XXXX",
      "host": "www.googletagmanager.com",
      "service_name": "Google Tag Manager",
      "version": "GTM-XXXX",
      "categories": ["Tag Manager"]
    }
  ]
}
```

If scanning failed for a URL, a `third_party_js_error` field is added instead.

### Database table

Results are stored in the `url_third_party_js_results` table:

| Column | Type | Description |
|---|---|---|
| `url` | TEXT | Page URL |
| `country_code` | TEXT | Legacy field name for seed identifier |
| `scan_id` | TEXT | Unique scan run ID |
| `is_reachable` | INTEGER | 1 = page fetched successfully |
| `scripts` | TEXT | JSON array of third-party script records |
| `error_message` | TEXT | Error message if the page fetch failed |
| `scanned_at` | TEXT | ISO-8601 timestamp |

---

## Related Pages

- [Technology Scanning](technology-scanning.md)
- [Accessibility Statements](accessibility-statements.md)
- [Social Media](social-media.md)
- [Scan Progress Report](scan-progress.md)
