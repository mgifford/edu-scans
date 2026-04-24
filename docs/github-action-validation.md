# URL Validation GitHub Action

This repository includes a GitHub Action workflow for validating government website URLs from TOON files.

## How to Trigger the Workflow

1. Navigate to the **Actions** tab in the GitHub repository
2. Select **"Validate Government URLs"** from the workflows list
3. Click **"Run workflow"**
4. Configure the run:
   - **Country**: (Optional) Enter a specific country code to validate (e.g., `ICELAND`, `FRANCE`, `BELGIUM`)
     - Leave empty to validate all countries
   - **Rate limit**: (Optional) Maximum requests per second (default: 2.0)
5. Click **"Run workflow"** to start the validation

## What the Workflow Does

The workflow will:

1. **Install dependencies** - Sets up Python 3.12 and installs required packages
2. **Run URL validation** - Validates URLs from TOON files
   - Checks if URLs are accessible
   - Tracks HTTP status codes
   - Records redirects
   - Marks URLs that fail twice for removal
3. **Generate report** - Creates a comprehensive markdown report with:
   - Summary statistics by country
   - Success rates
   - Detailed error information
   - List of URLs with issues
4. **Upload artifacts** - Makes the following available for download:
   - `validation-report.md` - Comprehensive validation report
   - `validation-output.txt` - Raw console output
   - `metadata.db` - SQLite database with detailed results
5. **Display summary** - Shows key results directly in the workflow summary

## Viewing Results

### In the Workflow Summary

After the workflow completes, you can view a summary directly in the GitHub Actions interface:

1. Go to the **Actions** tab
2. Click on the completed workflow run
3. The validation report summary will be displayed at the top of the page

### Downloading Detailed Results

To download the full report and data:

1. Scroll to the bottom of the workflow run page
2. Find the **Artifacts** section
3. Click on **"validation-report"** to download a ZIP file containing:
   - Full validation report (markdown)
   - Raw validation output (text)
   - SQLite database with all validation results

## Understanding the Report

The validation report includes:

### Summary Table

Shows for each country:
- **Total URLs**: Number of URLs checked
- **Valid**: URLs that responded successfully (HTTP 2xx)
- **Invalid**: URLs that returned errors or non-2xx status
- **Redirected**: URLs that redirected to another location
- **Removed**: URLs that failed validation twice (removed from TOON file)
- **Success Rate**: Percentage of valid URLs

### Error Details

Lists all invalid URLs grouped by:
- Country
- HTTP status code
- Error message

URLs marked with ⚠️ **REMOVED** have failed validation twice and have been removed from the TOON file.

## Validation Rules

1. **First failure**: URL is marked as invalid but kept in the TOON file
2. **Second failure**: URL is marked as invalid and **removed** from the TOON file
3. **Redirects**: URLs that redirect are updated in the TOON file to point to the final destination
4. **Rate limiting**: Requests are rate-limited to avoid overwhelming servers (default: 2 requests/second)

## Manual Validation

You can also run validations locally using the CLI:

```bash
# Install dependencies
pip install -r requirements.txt

# Validate a specific country
python3 -m src.cli.validate_urls --country ICELAND --rate-limit 2

# Validate all countries
python3 -m src.cli.validate_urls --all --rate-limit 2

# Generate a report from the database
python3 -m src.cli.generate_validation_report --output validation-report.md
```

## Scheduling Regular Validations

To set up automatic quarterly validations, you can add a schedule trigger to the workflow:

```yaml
on:
  workflow_dispatch:
    # ... existing inputs ...
  schedule:
    # Run quarterly: January 1, April 1, July 1, October 1 at 00:00 UTC
    - cron: '0 0 1 1,4,7,10 *'
```

## Troubleshooting

### Workflow Times Out

If validating all countries takes too long:
- Increase the `timeout-minutes` value in the workflow
- Run validations for individual countries instead of all at once
- Increase the `rate_limit` parameter (but be mindful of server load)

### High Failure Rate

If many URLs are failing:
- Check the error messages in the detailed report
- Common issues:
  - DNS resolution failures
  - SSL/TLS certificate errors
  - Connection timeouts
  - HTTP errors (404, 500, etc.)

### Database Locked Errors

If you see database locked errors:
- Ensure only one validation is running at a time
- Don't run multiple workflow instances simultaneously

## Data Retention

- Workflow artifacts are retained for **90 days**
- After 90 days, you'll need to re-run the validation to regenerate reports
- The SQLite database can be queried for custom analysis
