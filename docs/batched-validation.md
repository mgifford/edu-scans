# Batched URL Validation System

This document explains the batched URL validation system designed to handle ~80k+ institution URLs across many seed files without exceeding GitHub Actions' 2-hour timeout limit.

## Problem

The original implementation attempted to validate all URLs in a single GitHub Actions run, which:
- Exceeded the 2-hour timeout limit
- Was not resumable if it failed partway through
- Couldn't track progress across multiple runs

## Solution

The batched validation system breaks the work into small chunks that can be:
- Executed within the 2-hour timeout
- Tracked across multiple workflow runs
- Monitored via GitHub Issues
- Automatically resumed every 2 hours via cron

## Architecture

### Components

1. **Batch Coordinator** (`src/services/batch_coordinator.py`)
   - Manages validation cycles and tracks progress
   - Assigns seed files to batches
   - Persists state in SQLite database

2. **GitHub Issue Manager** (`src/services/github_issue_manager.py`)
   - Creates and updates GitHub issues to track cycle progress
   - Closes issues when cycles complete
   - Uses GitHub CLI (`gh`)

3. **Batch CLI** (`src/cli/validate_urls_batch.py`)
   - Command-line interface for batch validation
   - Processes seed files in configurable batch sizes
   - Integrates with coordinator and issue manager

4. **Workflow Files**
   - `.github/workflows/validate-urls-batch.yml` - Runs every 2 hours
   - `.github/workflows/reopen-validation-cycle.yml` - Starts new cycles quarterly

### Database Schema

The `validation_batch_state` table tracks cycle progress:

```sql
CREATE TABLE validation_batch_state (
    cycle_id TEXT NOT NULL,           -- Format: YYYYMMDD-HHMMSS
    country_code TEXT NOT NULL,       -- Legacy field name for seed identifier (e.g., "USA_EDU_MASTER")
    status TEXT NOT NULL,             -- pending, processing, completed, failed
    started_at TEXT,                  -- ISO timestamp
    completed_at TEXT,                -- ISO timestamp
    github_issue_number INTEGER,      -- GitHub issue tracking this cycle
    error_message TEXT,               -- Error details if failed
    PRIMARY KEY (cycle_id, country_code)
);
```

## Usage

### Manual Batch Validation

Process the next 5 seed files and create a GitHub issue:

```bash
python3 -m src.cli.validate_urls_batch \
  --batch-mode \
  --batch-size 5 \
  --rate-limit 2.0 \
  --create-issue
```

Process specific batch size with existing issue:

```bash
python3 -m src.cli.validate_urls_batch \
  --batch-mode \
  --batch-size 10 \
  --github-issue 123
```

### Single Country Validation (Legacy)

Validate a specific seed file:

```bash
python3 -m src.cli.validate_urls_batch \
  --country USA_EDU_MASTER \
  --rate-limit 2.0
```

### Automatic Batch Processing

The system automatically:
1. **Every 2 hours**: Processes next batch via cron workflow
2. **Quarterly**: Starts new validation cycles (Jan 1, Apr 1, Jul 1, Oct 1)

## Workflow

### 1. Cycle Initiation

When a new cycle starts:
- All seed files are initialized with `status = 'pending'`
- A GitHub issue is created to track progress
- Cycle ID is generated (format: `YYYYMMDD-HHMMSS`)

### 2. Batch Processing

Every 2 hours:
- Workflow runs via cron trigger
- Downloads previous metadata DB from artifacts
- Gets next N seed files (default: 5) with `status = 'pending'`
- Marks them as `status = 'processing'`
- Validates URLs for each seed file
- Updates status to `completed` or `failed`
- Updates GitHub issue with progress
- Uploads metadata DB as artifact

### 3. Cycle Completion

When all seed files are complete:
- GitHub issue is automatically closed
- Final statistics are reported
- System waits for next quarterly cycle or manual restart

### 4. Progress Tracking

GitHub issue shows:
```
Status: 🟡 In Progress
████████████░░░░░░░░ 60.0%

✅ Completed: 36/60
🔄 Processing: 2
⏳ Pending: 20
❌ Failed: 2
```

## Configuration

### Batch Size

Adjust based on:
- Average URLs per seed file
- Rate limiting settings
- Desired completion time

**Default**: 5 seed files per batch (~1.5 hours with 2 req/sec)

### Rate Limiting

**Default**: 2.0 requests/second per seed file

Configurable via:
- CLI: `--rate-limit 5.0`
- Workflow: `rate_limit` input parameter

### Timeout

**Default**: 110 minutes (leaves 10-minute buffer)

Configured in workflow file: `timeout-minutes: 110`

## Monitoring

### Check Cycle Progress

```bash
python3 -c "
from src.services.batch_coordinator import BatchCoordinator
from pathlib import Path

coordinator = BatchCoordinator(Path('data/metadata.db'))
# Get latest cycle
progress = coordinator.get_cycle_progress('CYCLE_ID')
print(progress)
"
```

### View GitHub Issue

Issues are labeled with:
- `url-validation`
- `automated`

Find open issues: https://github.com/mgifford/edu-scans/issues?q=is%3Aissue+is%3Aopen+label%3Aurl-validation

## Resumability

The system is fully resumable:

- **State persists** in database artifact
- **Workflow restarts** automatically every 2 hours
- **Progress tracked** in GitHub issue
- **Failed seed files** can be retried in next cycle

## Cost Optimization

- **Artifact storage**: Only metadata DB (~1 MB) uploaded
- **Workflow minutes**: ~2 hours per batch, spread over days
- **Rate limiting**: Respects server limits, prevents blocks

## Example Timeline

For 60 seed files with batch size 5:

| Time | Batch | Countries | Status |
|------|-------|-----------|--------|
| T+0h | 1 | 5 | ✅ Completed |
| T+2h | 2 | 5 | ✅ Completed |
| T+4h | 3 | 5 | ✅ Completed |
| ... | ... | ... | ... |
| T+22h | 12 | 5 | ✅ Completed |
| T+24h | - | 60 | 🟢 Cycle Complete |

**Total time**: ~24 hours to validate all 60 seed files

## Troubleshooting

### Issue not created

- Ensure `gh` CLI is available in workflow
- Check `GH_TOKEN` permissions include `issues: write`
- Check repository settings allow workflow to create issues

### Batch doesn't resume

- Verify metadata DB artifact exists
- Check artifact retention (90 days)
- Ensure cycle isn't marked complete

### Countries skipped

- Check TOON files exist in `data/toon-seeds/`
- Verify seed code matches filename
- Check error messages in batch state table

## Future Improvements

1. **Adaptive batch sizing**: Adjust based on URL count per seed file
2. **Parallel processing**: Process multiple seed files concurrently
3. **Priority queuing**: Prioritize seed files by update frequency
4. **Webhook notifications**: Alert on cycle completion
5. **Web dashboard**: Real-time progress visualization
