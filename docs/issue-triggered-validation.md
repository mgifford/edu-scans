# Issue-Triggered Validation

This document describes how to trigger URL validation scans using GitHub issues.

## Overview

The repository includes an automated system that monitors GitHub issues and triggers validation scans based on issue titles. This allows you to schedule validation runs using different patterns without manually running workflows.

## How It Works

1. **Issue Detection**: Every hour, a GitHub Actions workflow checks for open issues with specific title prefixes
2. **Schedule Check**: Before running, the system checks whether the issue is due based on its prefix schedule and when it last ran. Issues that are not yet due are skipped without error.
3. **Scan Execution**: When a trigger issue is found and is due, the system runs a URL validation scan across all seed files
4. **Time Budget**: Each run has a 50-minute budget. When approaching the limit, scanning stops early and a partial report is posted. The next hourly run will continue where it left off.
5. **Report Generation**: After validation completes, a detailed report is posted as a comment to the issue
6. **Issue Management**: 
   - One-time scans (`SCAN:` prefix) close the issue automatically after a full run
   - Periodic scans keep the issue open for future runs

## Concurrency

The issue-triggered workflow and the batch-validation workflow share a single
`validation-runs` concurrency group in GitHub Actions. This means:

- **Only one validation workflow runs at a time** — they queue rather than
  run simultaneously.
- If a batch-validation run is in progress when the hourly issue check fires,
  the issue check waits until the batch run finishes (or the batch run queues
  behind the issue check, depending on which started first).
- This prevents the two workflows from competing for the shared
  `validation-metadata` artifact.

## Supported Trigger Prefixes

### One-Time Scans

**`SCAN: <description>`**
- Runs validation once
- Posts results as a comment
- Automatically closes the issue when complete
- Example: `SCAN: Validate URL`

### Periodic Scans

These prefixes trigger validation on a schedule and keep the issue open:

| Prefix | Cooldown | Day restriction |
|--------|----------|-----------------|
| `QUARTERLY:` | 85 days | Any day |
| `MONTHLY:` | 28 days | Any day |
| `WEEKLY:` | 6 days | Any day |
| `MONDAYS:` | 23 hours | Mondays only |
| `TUESDAYS:` | 23 hours | Tuesdays only |
| `WEDNESDAYS:` | 23 hours | Wednesdays only |
| `THURSDAYS:` | 23 hours | Thursdays only |
| `FRIDAYS:` | 23 hours | Fridays only |
| `SATURDAYS:` | 23 hours | Saturdays only |
| `SUNDAYS:` | 23 hours | Sundays only |

The workflow checks issues every hour. When a trigger issue is found, the
system compares the current time against the issue's last completed run to
decide whether to proceed or skip. Day-of-week prefixes (e.g. `MONDAYS:`) will
only fire on the matching day of the week.

## Creating a Trigger Issue

### Step 1: Create a New Issue

1. Go to the **Issues** tab in the repository
2. Click **New Issue**
3. Enter a title with one of the supported prefixes
4. Add optional description explaining the validation request

### Example Titles

```
SCAN: Validate URL
SCAN: Emergency URL check after domain migration
QUARTERLY: Validate URL
MONTHLY: Regular maintenance scan
WEEKLY: Validate URL
MONDAYS: Start-of-week validation
```

### Step 2: Wait for Execution

- The workflow runs every hour on the hour
- Check the **Actions** tab to see the workflow run
- Results will be posted as a comment to your issue

### Step 3: Review Results

The system will post a detailed report including:
- Summary statistics (total URLs, valid, invalid, etc.)
- Per-seed breakdown
- Validation timestamp
- Links to download full results

## Validation Report Format

The automated report includes:

```markdown
## URL Validation Report

**Trigger:** SCAN: (one-time) or QUARTERLY: (quarterly)
**Completed:** 2026-02-27 15:30:00 UTC
**Countries Processed:** 40

### Summary

| Metric | Count |
|--------|-------|
| Total URLs | 80,423 |
| Validated | 78,650 |
| Valid | 76,230 (96.9%) |
| Invalid | 2,420 (3.1%) |
| Redirected | 1,850 |
| Removed (failed 2x) | 350 |

### Country Details

| Country | Total | Valid | Invalid | Redirected | Removed |
|---------|-------|-------|---------|------------|---------|
| AUSTRIA | 2,450 | 2,380 | 70 | 45 | 8 |
...
```

## Managing Trigger Issues

### Closing a Periodic Issue

If you want to stop a periodic validation:
1. Manually close the issue
2. The system will skip closed issues

### Reopening for Another Run

To trigger another one-time scan:
1. Create a new issue with `SCAN:` prefix
2. Or reopen a closed issue (it will run once more)

### Checking Status

- View the **Actions** tab to see workflow runs
- Check issue comments for validation reports
- Download artifacts from workflow runs for detailed data

## Workflow Details

**Workflow File:** `.github/workflows/issue-triggered-validation.yml`

**Schedule:** Runs every hour (`0 * * * *` cron)

**Permissions Required:**
- `contents: write` - Download/upload artifacts
- `issues: write` - Post comments and close issues

**Timeout:** 60 minutes (workflow). The CLI uses a 50-minute budget, leaving a
10-minute safety buffer. Each issue scan gets a share of that budget; if time
runs low the scan stops early and the remaining seed files are processed in the
next hourly run.

**Artifacts:**
- Validation metadata database is automatically saved
- 90-day retention period
- Shared across all validation workflows

## Best Practices

1. **Use Clear Descriptions**: Add context in the issue title after the prefix
   - Good: `SCAN: Validate URL after security updates`
   - Okay: `SCAN: Validate URL`

2. **One Active Scan per Type**: Avoid creating multiple open issues with the same prefix to prevent duplicate runs

3. **Monitor Progress**: Check the Actions tab during long validations

4. **Review Reports**: Check the validation report for errors and failures

5. **Close When Done**: For one-time scans, the issue closes automatically. For periodic scans, close manually when no longer needed.

## Troubleshooting

**Issue not triggering validation:**
- Ensure the title starts with an exact prefix (case-insensitive, but must match exactly)
- Check that the issue is open (closed issues are skipped)
- Wait for the next hourly workflow run
- Check the Actions tab for errors

**Validation timing out:**
- The system has the same 110-minute timeout as batch validation
- For very large validations, consider using the batch workflow instead
- Check workflow logs for timeout messages

**Report not posted:**
- Check workflow logs for errors
- Ensure GitHub token has issues:write permission
- Verify the issue is still open when validation completes

## Related Documentation

- [Batch Validation System](batched-validation.md) - For scheduled, chunked validation
- [URL Validation Scanner](url-validation-scanner.md) - For manual validation
- [GitHub Actions Validation](github-action-validation.md) - For UI-based validation

## Technical Details

**Implementation:**
- CLI: `src/cli/issue_triggered_validation.py`
- Handler: `src/services/issue_trigger_handler.py`
- Workflow: `.github/workflows/issue-triggered-validation.yml`

**Data Storage:**
- Uses same metadata database as other validation workflows
- Stored in GitHub Actions artifacts
- 90-day retention
- Not committed to repository
