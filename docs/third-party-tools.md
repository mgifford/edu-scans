---
title: Third-Party JavaScript
layout: page
---

<!-- THIRD_PARTY_JS_STATS_START -->

_Stats as of 2026-09-24 10:00 UTC — last scan: 2026-09-24_

**144** scan batches run

**3,211** of **19,936** available pages scanned (**16.1%** coverage)
**2,421** of **3,211** scanned pages were reachable (**75.4%**)
**1,745** reachable pages loaded at least one third-party script (**72.1%** of reachable)
**3,221** known third-party service loads identified
**25** unique known services across **17** categories

---

## Third-Party JavaScript by Country

| Country | Scanned | Available | Reachable | URLs with 3rd-Party JS | Known Service Loads | Last Scan |
|---------|---------|-----------|-----------|------------------------|--------------------|----------|
| Usa Edu Master | 3,211 | 3,763 | 2,421 | 1,745 | 3,221 | 2026-09-24 |

> Hover or focus any non-zero country-table count to preview matching pages. Activate the number to keep the preview open and download a CSV for that country and metric from [Download machine-readable third-party tools data (JSON)](third-party-tools-data.json).

---

### Top Third-Party Services

| # | Service | Loads |
|--:|---------|------:|
| 1 | cdnjs (Cloudflare CDN) | **570** |
| 2 | Google Analytics (GA4) | **565** |
| 3 | jsDelivr CDN | **450** |
| 4 | Google Tag Manager | **434** |
| 5 | jQuery | **271** |
| 6 | Font Awesome | **239** |
| 7 | Google Hosted Libraries | **170** |
| 8 | Google reCAPTCHA | **161** |
| 9 | unpkg CDN | **110** |
| 10 | Bootstrap | **61** |
| 11 | HubSpot | **43** |
| 12 | Sentry | **28** |
| 13 | OneTrust | **26** |
| 14 | Adobe Dynamic Tag Management / Launch | **23** |
| 15 | Facebook Pixel | **18** |
| 16 | Cookiebot | **13** |
| 17 | Cloudflare Turnstile / Challenge | **12** |
| 18 | Stripe | **10** |
| 19 | Google Analytics (Universal) | **4** |
| 20 | Zendesk | **4** |

### Top Service Categories

| # | Category | Loads |
|--:|----------|------:|
| 1 | CDN | **1,300** |
| 2 | Analytics | **617** |
| 3 | Tag Manager | **457** |
| 4 | JavaScript Library | **441** |
| 5 | Icon Library | **239** |
| 6 | Security | **173** |
| 7 | CAPTCHA | **161** |
| 8 | UI Framework | **61** |
| 9 | CRM | **43** |
| 10 | Marketing | **43** |
| 11 | Cookie Consent | **41** |
| 12 | Error Tracking | **28** |
| 13 | Advertising | **19** |
| 14 | Payments | **10** |
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
