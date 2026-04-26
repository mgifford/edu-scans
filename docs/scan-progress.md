---
title: Scan Progress Report
layout: page
---

_Generated: 2026-04-26 05:58 UTC_

This report tracks how far along each scan type is across all countries. It is regenerated automatically after every scan run.

## Overall Coverage

Coverage is measured as pages scanned out of **3,763** pages available in the seed files.

| Scan Type | Pages Scanned | Available | Coverage |
|-----------|--------------|-----------|----------|
| Social Media | 0 scanned (0 reachable) | 3,763 | <span role="img" aria-label="0.0% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:0px;height:100%;background:#b91c1c;"></span></span><span style="font-size:0.85em;color:#374151;">0.0%</span></span> |
| Technology | 0 scanned | 3,763 | (manual scan) |
| Lighthouse | 412 scanned | 3,763 | <span role="img" aria-label="10.9% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:13px;height:100%;background:#b91c1c;"></span></span><span style="font-size:0.85em;color:#374151;">10.9%</span></span> |
| Accessibility Statements | 3,002 scanned | 3,763 | <span role="img" aria-label="79.8% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:96px;height:100%;background:#15803d;"></span></span><span style="font-size:0.85em;color:#374151;">79.8%</span></span> |

> **Combined Reachability** counts each URL once if it was confirmed reachable by any scan type.

## Technology Scan

_No technology scans have been run yet. Trigger the **Scan Technology Stack** workflow manually._

## Lighthouse Scan by Country

| Country | URLs | Perf | A11y | Best Practices | SEO | Last Scan |
|---------|------|------|------|----------------|-----|----------|
| Usa Edu Master | 412 | 85 | 89 | 66 | 90 | 2026-04-26 |

> Scores are averages across all successfully audited URLs, displayed as 0–100 (multiply source values × 100).

## Accessibility Statement Scan by Country

Checks whether each government page links to an accessibility statement as required by the EU Web Accessibility Directive (Directive 2016/2102).

| Country | Scanned | Reachable | Has Statement | In Footer | Statement % | Scan Period |
|---------|---------|-----------|--------------|-----------|------------|-------------|
| Usa Edu Master | 3,002 | 2,225 | 801 | 718 | 36% | Apr 2026 |

> **Statement %** is the percentage of *reachable* pages that contain at least one link to an accessibility statement.

## Scan Priority Guide

Scans are ordered from **highest** to **lowest** priority:

1. **Social Media Scan** — runs every 3 hours; downloads and parses full pages, confirming reachability *and* detecting social links in one pass.
2. **Accessibility Statement Scan** — runs every 4 hours; checks whether each page links to an accessibility statement as required by the EU Web Accessibility Directive (Directive 2016/2102).
3. **Technology Scan** — run on demand; detects CMS, framework, and analytics platforms.
4. **Lighthouse Scan** — run on demand; measures performance, accessibility (WCAG), best practices, and SEO for each URL.
5. **URL Validation** — runs every 6 hours in the background; a lightweight redirect/404 check that is **automatically skipped** for URLs already confirmed reachable by a higher-priority scan within the last 30 days.

> **Tip:** Run a social media scan first for a new country — this simultaneously validates all URLs *and* collects social media data, avoiding a separate URL-only pass.

### Why are Social Media and URL Validation counts different?

The Social Media scanner runs more frequently than URL Validation and therefore covers more URLs over time.  Because the Social Media scanner already confirms whether each URL is reachable, the URL Validation job automatically *skips* any page already confirmed reachable within the last 30 days.  As a result the two individual scan counts do **not** simply add up — each scan covers a different subset of pages.

**What URL Validation adds beyond Social Media:**

- **Failure tracking** — records how many consecutive times each URL has failed; URLs that fail twice are removed from future scans to keep the seed file accurate.
- **Redirect-chain capture** — follows and stores the full redirect chain so the seed file can be updated with the final canonical URL.
- **Lightweight fallback** — a fast HTTP-only check for URLs that the Social Media scanner has not yet reached, without the overhead of downloading and parsing the full page.

The **Combined Reachability** row at the top of the coverage table counts each URL once if it was confirmed reachable by *either* scan, giving the most accurate picture of overall URL health.
