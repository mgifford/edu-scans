import { AxeBuilder } from "@axe-core/playwright";
import { chromium } from "playwright";
import { readdir } from "node:fs/promises";
import path from "node:path";

const siteDir = process.env.A11Y_SITE_DIR || "_site";
const siteBaseUrl = process.env.A11Y_BASE_URL || "http://127.0.0.1:4000";
const rootDir = path.resolve(siteDir);

async function collectHtmlFiles(dir) {
  const entries = await readdir(dir, { withFileTypes: true });
  const htmlFiles = await Promise.all(
    entries.map(async (entry) => {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name.startsWith(".")) {
          return [];
        }
        return collectHtmlFiles(fullPath);
      }
      if (!entry.isFile() || path.extname(entry.name) !== ".html") {
        return [];
      }
      return [fullPath];
    }),
  );

  return htmlFiles.flat().sort();
}

function toPageUrl(filePath) {
  const relativePath = path.relative(rootDir, filePath).split(path.sep).join("/");
  if (relativePath === "index.html") {
    return `${siteBaseUrl}/`;
  }
  if (relativePath.endsWith("/index.html")) {
    return `${siteBaseUrl}/${relativePath.slice(0, -"/index.html".length)}/`;
  }
  return `${siteBaseUrl}/${relativePath}`;
}

function formatViolation(violation) {
  const nodes = violation.nodes
    .map((node) => {
      const target = node.target.join(", ");
      const summary = node.failureSummary
        ? node.failureSummary.replace(/\s+/g, " ").trim()
        : "No failure summary provided.";
      return `    - ${target}: ${summary}`;
    })
    .join("\n");

  return [
    `  ${violation.id}: ${violation.help}`,
    `  Impact: ${violation.impact || "unknown"}`,
    `  Help: ${violation.helpUrl}`,
    nodes,
  ].join("\n");
}

async function run() {
  const htmlFiles = await collectHtmlFiles(rootDir);
  if (!htmlFiles.length) {
    throw new Error(`No HTML files found in ${rootDir}`);
  }

  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  const failures = [];

  try {
    for (const filePath of htmlFiles) {
      const url = toPageUrl(filePath);
      process.stdout.write(`Checking ${url}\n`);
      await page.goto(url, { waitUntil: "networkidle" });

      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"])
        .analyze();

      if (results.violations.length) {
        failures.push({
          url,
          violations: results.violations,
        });
      }
    }
  } finally {
    await context.close();
    await browser.close();
  }

  if (!failures.length) {
    process.stdout.write(`Axe checks passed for ${htmlFiles.length} page(s).\n`);
    return;
  }

  const details = failures
    .map((failure) => {
      const violations = failure.violations.map(formatViolation).join("\n");
      return [`Page: ${failure.url}`, violations].join("\n");
    })
    .join("\n\n");

  throw new Error(
    `Axe found accessibility violations on ${failures.length} page(s).\n\n${details}`,
  );
}

run().catch((error) => {
  console.error(error.message || error);
  process.exitCode = 1;
});
