---
title: Data API
layout: page
---

This project publishes machine-readable JSON/CSV files via GitHub Pages and
GitHub Actions artifacts so other tools can query scan results programmatically.

---

## Base URL

```
https://mgifford.github.io/edu-scans/
```

---

## Endpoint index

| Endpoint | Availability | Description |
|---|---|---|
| [`technology-index.json`](#technology-indexjson) | committed | Compact cross-reference (`technology -> pages/categories/by_country`). |
| [`technology-license-data.json`](#technology-license-datajson) | committed | License, OSI, and DPGA metadata for top detected technologies. |
| [`third-party-tools-data.json`](#third-party-tools-datajson) | committed | Third-party JavaScript summary + drilldowns. |
| [`technology-data.csv`](#technology-datacsv) | committed | Flat technology summary export. |
| `technology-data.json` | artifact-only | Full technology scan data with per-country drilldowns. |
| `social-media-data.json` | artifact-only | Full social-media scan data with per-URL evidence. |
| `accessibility-data.json` | artifact-only | Full accessibility scan data with per-page/domain evidence. |
| `lighthouse-data.json` | artifact-only | Full Lighthouse per-URL data. |
| `lighthouse-data.csv` | artifact-only | Flat Lighthouse per-URL export. |
| `scan-progress-data.json` | artifact-only | Full scan-progress machine-readable payload. |

---

## technology-index.json

**URL:** `https://mgifford.github.io/edu-scans/technology-index.json`

Compact index for quick queries without loading full drilldown files.

### Schema

```jsonc
{
  "generated_at": "2026-05-21 22:00 UTC",
  "base_url": "https://mgifford.github.io/edu-scans/",
  "note": "...",
  "by_technology": {
    "WordPress": {
      "pages": 1541,
      "categories": ["Blogs", "CMS"],
      "by_country": {
        "USA_EDU_MASTER": 1000
      }
    }
  },
  "by_category": {
    "CMS": {
      "pages": 2490,
      "technologies": ["Drupal", "WordPress"]
    }
  }
}
```

### Example

```bash
curl -s https://mgifford.github.io/edu-scans/technology-index.json \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['by_technology'].get('Drupal',{}))"
```

---

## technology-license-data.json

**URL:** `https://mgifford.github.io/edu-scans/technology-license-data.json`

Policy metadata for top technologies: licensing class, OSI approval, and DPGA
Registry status.

### Schema

```jsonc
{
  "generated_at": "2026-05-21 22:00 UTC",
  "scope_note": "...",
  "dpga_registry_source": "...",
  "records": [
    {
      "technology": "Drupal",
      "license": "GPL-2.0-or-later",
      "osi_approved": "yes",
      "dpga_registry": "listed"
    }
  ]
}
```

---

## third-party-tools-data.json

**URL:** `https://mgifford.github.io/edu-scans/third-party-tools-data.json`

Committed summary dataset for third-party JS dependencies.

---

## technology-data.csv

**URL:** `https://mgifford.github.io/edu-scans/technology-data.csv`

Committed flat CSV export from technology scans (`rank,technology,pages,categories`).

---

## Artifact-only files

Artifact-only files are uploaded by
[Generate Scan Progress Report](https://github.com/mgifford/edu-scans/actions/workflows/generate-scan-progress.yml)
and are not committed due to size and churn.

How to retrieve:

1. Open latest completed run of the workflow above.
2. Download artifact `scan-progress-report-*`.
3. Extract desired `docs/*.json` or `docs/*.csv` files.

---

## Committed vs artifact-only policy

- **Committed:** compact, stable API files that are small and high-value for
  direct GitHub Pages use.
- **Artifact-only:** large, high-churn, per-URL/per-page drilldown datasets.

