---
title: Scan Progress Report
layout: page
---

_Generated: 2026-04-28 06:15 UTC_

This report tracks how far along each scan type is across all countries. It is regenerated automatically after every scan run.

## Overall Coverage

Coverage is measured as pages scanned out of **3,863** pages available in the seed files.

| Scan Type | Pages Scanned | Available | Coverage |
|-----------|--------------|-----------|----------|
| Social Media | 0 scanned (0 reachable) | 3,863 | <span role="img" aria-label="0.0% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:0px;height:100%;background:#b91c1c;"></span></span><span style="font-size:0.85em;color:#374151;">0.0%</span></span> |
| Technology | 0 scanned | 3,863 | <span role="img" aria-label="0.0% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:0px;height:100%;background:#b91c1c;"></span></span><span style="font-size:0.85em;color:#374151;">0.0%</span></span> |
| Lighthouse | 265 scanned | 3,863 | <span role="img" aria-label="6.9% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:8px;height:100%;background:#b91c1c;"></span></span><span style="font-size:0.85em;color:#374151;">6.9%</span></span> |
| Accessibility Statements | 0 domains | 3,863 | <span role="img" aria-label="0.0% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:0px;height:100%;background:#b91c1c;"></span></span><span style="font-size:0.85em;color:#374151;">0.0%</span></span> |
| Third-Party JS | 0 scanned | 3,863 | <span role="img" aria-label="0.0% complete" style="display:inline-flex;align-items:center;gap:4px;vertical-align:middle;"><span style="display:inline-block;width:120px;height:12px;background:#e2e8f0;border-radius:2px;overflow:hidden;"><span style="display:block;width:0px;height:100%;background:#b91c1c;"></span></span><span style="font-size:0.85em;color:#374151;">0.0%</span></span> |

> **Combined Reachability** counts each URL once if it was confirmed reachable by any scan type.

## Coverage Trend (Last 14 Days)

Coverage percentage for each scan type, updated daily. When a scan type is far behind the others it will be automatically prioritised for an extra run.

| Date | Accessibility | Social Media | Technology | Third-Party JS | Lighthouse |
|------|--------------|--------------|------------|----------------|------------|
| 2026-04-28 | 0.0% | 0.0% | 0.0% | 0.0% | 6.9% |
| 2026-04-27 | 100.3% | 99.6% | 99.6% | 80.6% | 10.9% |

> Percentages are calculated as *pages scanned* ÷ *total pages available* × 100. Lighthouse scans take longer per URL and may lag other scan types; the auto-prioritisation step compensates by triggering extra runs for the most-lagging scan each day.

## Technology Scan

_No technology scans have been run yet. Trigger the **Scan Technology Stack** workflow manually._

## Lighthouse Scan by Country

| Country | URLs | Perf | A11y | Best Practices | SEO | Last Scan |
|---------|------|------|------|----------------|-----|----------|
| Usa Edu Master | 175 | 86 | 88 | 66 | 89 | 2026-04-28 |
| Usa Edu Top100 | 90 | 88 | 95 | 66 | 93 | 2026-04-28 |

> Scores are averages across all successfully audited URLs, displayed as 0–100 (multiply source values × 100).

## Accessibility Statement Scan

_No accessibility statement scans have been run yet. Trigger the **Scan Accessibility Statements** workflow manually or wait for the next scheduled run._

## Third-Party JavaScript Scan

_No third-party JavaScript scans have been run yet. Trigger the **Scan Third-Party JavaScript** workflow or wait for the next scheduled run._

## Scan Priority Guide

Scans are ordered from **highest** to **lowest** priority:

1. **Social Media Scan** — runs every 2 hours; downloads and parses full pages, confirming reachability *and* detecting social links in one pass.
2. **Accessibility Statement Scan** — runs every 4 hours; checks whether each page links to an accessibility statement as required by the EU Web Accessibility Directive (Directive 2016/2102).
3. **Technology Scan** — runs every 4 hours; detects CMS, framework, and analytics platforms.
4. **Third-Party JavaScript Scan** — runs every 6 hours; identifies externally hosted scripts, CDNs, and third-party services.
5. **Lighthouse Scan** — runs once per day; measures performance, accessibility (WCAG), best practices, and SEO for each URL. Each URL takes ~20–30 s so coverage builds gradually.
6. **URL Validation** — runs every 2 hours in the background; a lightweight redirect/404 check that is **automatically skipped** for URLs already confirmed reachable by a higher-priority scan within the last 30 days.

> **Auto-prioritisation:** when any scan type is more than 10 percentage points behind the leader, the daily report-generation step automatically dispatches an extra run of that workflow to help close the gap.

### Why are Social Media and URL Validation counts different?

The Social Media scanner runs more frequently than URL Validation and therefore covers more URLs over time.  Because the Social Media scanner already confirms whether each URL is reachable, the URL Validation job automatically *skips* any page already confirmed reachable within the last 30 days.  As a result the two individual scan counts do **not** simply add up — each scan covers a different subset of pages.

**What URL Validation adds beyond Social Media:**

- **Failure tracking** — records how many consecutive times each URL has failed; URLs that fail twice are removed from future scans to keep the seed file accurate.
- **Redirect-chain capture** — follows and stores the full redirect chain so the seed file can be updated with the final canonical URL.
- **Lightweight fallback** — a fast HTTP-only check for URLs that the Social Media scanner has not yet reached, without the overhead of downloading and parsing the full page.

The **Combined Reachability** row at the top of the coverage table counts each URL once if it was confirmed reachable by *either* scan, giving the most accurate picture of overall URL health.
