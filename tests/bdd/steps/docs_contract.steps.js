const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const { Given, Then } = require("@cucumber/cucumber");

Given("the documentation file {string}", function (relativePath) {
  const absolutePath = path.resolve(process.cwd(), relativePath);
  assert.ok(fs.existsSync(absolutePath), `Expected file to exist: ${absolutePath}`);
  this.currentFilePath = absolutePath;
  this.currentFileContents = fs.readFileSync(absolutePath, "utf-8");
});

Then("it should include {string}", function (expectedText) {
  assert.ok(this.currentFileContents, "No file content is loaded in this scenario.");
  assert.ok(
    this.currentFileContents.includes(expectedText),
    `Expected file ${this.currentFilePath} to include: ${expectedText}`,
  );
});

Then("it should include each of:", function (dataTable) {
  assert.ok(this.currentFileContents, "No file content is loaded in this scenario.");
  const values = dataTable.raw().flat().map((value) => value.trim()).filter(Boolean);
  for (const value of values) {
    assert.ok(
      this.currentFileContents.includes(value),
      `Expected file ${this.currentFilePath} to include: ${value}`,
    );
  }
});

Then("the repository file {string} should exist", function (relativePath) {
  const absolutePath = path.resolve(process.cwd(), relativePath);
  assert.ok(fs.existsSync(absolutePath), `Expected file to exist: ${absolutePath}`);
});
