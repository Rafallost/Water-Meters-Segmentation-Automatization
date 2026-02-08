# Quick script to update GitHub Secrets with AWS credentials
#
# Usage:
#   1. Get credentials from AWS Academy Lab
#   2. Run: .\scripts\update-github-secrets.ps1
#   3. Paste credentials when prompted

Write-Host "==========================================" -ForegroundColor Blue
Write-Host "Update GitHub Secrets - AWS Credentials" -ForegroundColor Blue
Write-Host "==========================================" -ForegroundColor Blue
Write-Host ""

# Check if gh CLI is installed
$ghVersion = gh --version 2>$null
if (-not $?) {
    Write-Host "❌ GitHub CLI (gh) not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Install:"
    Write-Host "  Windows: winget install --id GitHub.cli"
    Write-Host ""
    Write-Host "Then run: gh auth login"
    exit 1
}

# Check if authenticated
$authStatus = gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Not authenticated with GitHub CLI" -ForegroundColor Red
    Write-Host ""
    Write-Host "Run: gh auth login"
    exit 1
}

Write-Host "✅ GitHub CLI authenticated" -ForegroundColor Green
Write-Host ""

# Prompt for credentials
Write-Host "Paste AWS credentials from AWS Academy Lab:" -ForegroundColor Yellow
Write-Host "(AWS Details → Show AWS CLI credentials)" -ForegroundColor Yellow
Write-Host ""

$AWS_ACCESS_KEY_ID = Read-Host "AWS_ACCESS_KEY_ID"
$AWS_SECRET_ACCESS_KEY = Read-Host "AWS_SECRET_ACCESS_KEY"
$AWS_SESSION_TOKEN = Read-Host "AWS_SESSION_TOKEN"

Write-Host ""
Write-Host "Updating GitHub Secrets..." -ForegroundColor Yellow

# Update secrets
gh secret set AWS_ACCESS_KEY_ID --body $AWS_ACCESS_KEY_ID
gh secret set AWS_SECRET_ACCESS_KEY --body $AWS_SECRET_ACCESS_KEY
gh secret set AWS_SESSION_TOKEN --body $AWS_SESSION_TOKEN

Write-Host ""
Write-Host "✅ GitHub Secrets updated successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Go to GitHub Actions: https://github.com/Rafallost/Water-Meters-Segmentation-Autimatization/actions"
Write-Host "  2. Click failed workflow run"
Write-Host "  3. Click 'Re-run failed jobs'"
Write-Host ""
Write-Host "Or use CLI:" -ForegroundColor Yellow
Write-Host "  gh run list --workflow=`"Train Model`" --limit=1"
Write-Host "  gh run rerun <RUN_ID> --failed"
