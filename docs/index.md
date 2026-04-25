---
title: USA Higher-Education Website Scans
layout: home
---

This project discovers and catalogs how United States higher-education institutions
using `.edu` domains publish accessibility statements, maintain reachable URLs,
and use modern web technologies and third-party JavaScript.

## Current Scan Progress

<!-- SCAN_PROGRESS_START -->

_Progress as of 2026-04-25 00:26 UTC_

| Scan Type | Pages Scanned | Coverage |
|-----------|--------------|----------|
| Social Media | 0 scanned (0 reachable) | <span role="img" aria-label="0.0% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:0px;height:100%;background:#b91c1c;"></span></span><span style="font-size:0.85em;color:#374151;">0.0%</span></span> |
| Technology | 38 scanned | <span role="img" aria-label="1.0% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:1px;height:100%;background:#b91c1c;"></span></span><span style="font-size:0.85em;color:#374151;">1.0%</span></span> |
| Lighthouse | 453 scanned | <span role="img" aria-label="12.0% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:14px;height:100%;background:#b91c1c;"></span></span><span style="font-size:0.85em;color:#374151;">12.0%</span></span> |

**1 countries** with scan data · **0** of **3,763** available pages confirmed reachable. See the [Scan Progress Report](scan-progress.md) for full details.

<!-- SCAN_PROGRESS_END -->

## Latest Scan Results

- **[Scan Progress Report](scan-progress.md)** — Overall coverage, scan status, and seed-level comparisons across the project.
- **[Social Media](social-media.md)** — Institutional use of social platforms, with evidence behind the published counts.
- **[Accessibility Statements](accessibility-statements.md)** — Evidence showing which pages do and do not publish accessibility statements.
- **[Technology Scanning](technology-scanning.md)** — Detected CMSs, frameworks, analytics tools, and other software found on institution websites.
- **[Third-Party JavaScript](third-party-tools.md)** — External scripts, services, and hosted dependencies loaded by scanned pages.
- **[Lighthouse Scanning](lighthouse-scanning.md)** — Google Lighthouse methodology, workflow details, and page-level quality scores as they are collected.
- **[Institution Domains](domains.md)** — The tracked source dataset: institution domains and page URLs used as scan inputs.

## What We Track

### Social Media Presence

We check institution pages for links to social platforms, then classify what was found at page and seed level.

See **[Social Media](social-media.md)** for platform coverage, tier definitions, and downloadable evidence.

### URL Validation

We validate tracked URLs, follow redirects, and monitor persistent failures so the source dataset stays current.

See **[Scan Progress Report](scan-progress.md)** for current validation coverage and seed-level results.

### Technology Detection

We detect the CMS, framework, analytics, hosting, and other technologies used by institution websites.

See **[Technology Scanning](technology-scanning.md)** for the detected technologies and seed-level tables.

### Third-Party JavaScript

We track externally hosted scripts and services such as analytics tags, consent tools, CDNs, shared JavaScript libraries, and support widgets.

See **[Third-Party JavaScript](third-party-tools.md)** for the current breakdown and evidence exports.

### Lighthouse Audits

We run Google Lighthouse on each scanned page and record five quality scores:
performance, accessibility, best practices, SEO, and PWA compliance (0–100 scale).

See **[Lighthouse Scanning](lighthouse-scanning.md)** for full details.

## Coverage Scope

The dataset currently targets **United States higher-education institutions**
that use `.edu` domains.

See **[Institution Domains](domains.md)** for the full source domain and page URL list.

## How the Scans Work

Scans run automatically on a schedule via **GitHub Actions**:

| Scan | Schedule | Priority |
|------|----------|----------|
| Social Media | Every 2 hours | **Highest** — confirms reachability and collects social-link data in one pass |
| Technology Detection | Every 4 hours | Medium |
| URL Validation | Every 12 hours | Lowest — lightweight redirect/404 checks; skipped for recently validated URLs |
| Lighthouse Audits | Daily | Medium — slower per URL, so scanned progressively |
| Scan Progress Report | After every scan | — |

After each scan run, this site is automatically updated with the latest results.

## Accessing Scan Artifacts

Each GitHub Actions scan run uploads its results as a downloadable artifact:

1. Go to [GitHub Actions](https://github.com/mgifford/edu-scans/actions)
2. Click the relevant workflow
3. Open a completed run and scroll to the **Artifacts** section
4. Download the artifact to inspect the database, annotated TOON files, and scan logs

> The [Scan Progress Report](scan-progress.md) is regenerated automatically, so most visitors should not need the raw artifacts unless they want to inspect the source outputs directly.

## Source Code & Data

- [GitHub Repository](https://github.com/mgifford/edu-scans)
- [GitHub Actions Workflows](https://github.com/mgifford/edu-scans/actions)
- [Accessibility Statement](https://github.com/mgifford/edu-scans/blob/main/ACCESSIBILITY.md)

---

*Scan data is collected by automated workflows and stored as GitHub Actions artifacts.
The progress report is regenerated after every scan and committed directly to this site.*
