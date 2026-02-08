#!/bin/bash
# Quick script to update GitHub Secrets with AWS credentials
#
# Usage:
#   1. Get credentials from AWS Academy Lab
#   2. Run this script and paste when prompted
#   3. Or edit this file with your credentials and run

set -e

echo "=========================================="
echo "Update GitHub Secrets - AWS Credentials"
echo "=========================================="
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) not found!"
    echo ""
    echo "Install:"
    echo "  macOS:   brew install gh"
    echo "  Linux:   See https://github.com/cli/cli#installation"
    echo "  Windows: winget install --id GitHub.cli"
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo "❌ Not authenticated with GitHub CLI"
    echo ""
    echo "Run: gh auth login"
    exit 1
fi

echo "✅ GitHub CLI authenticated"
echo ""

# Prompt for credentials
echo "Paste AWS credentials from AWS Academy Lab:"
echo "(AWS Details → Show AWS CLI credentials)"
echo ""

read -p "AWS_ACCESS_KEY_ID: " AWS_ACCESS_KEY_ID
read -p "AWS_SECRET_ACCESS_KEY: " AWS_SECRET_ACCESS_KEY
read -p "AWS_SESSION_TOKEN: " AWS_SESSION_TOKEN

echo ""
echo "Updating GitHub Secrets..."

# Update secrets
gh secret set AWS_ACCESS_KEY_ID --body "$AWS_ACCESS_KEY_ID"
gh secret set AWS_SECRET_ACCESS_KEY --body "$AWS_SECRET_ACCESS_KEY"
gh secret set AWS_SESSION_TOKEN --body "$AWS_SESSION_TOKEN"

echo ""
echo "✅ GitHub Secrets updated successfully!"
echo ""
echo "Next steps:"
echo "  1. Go to GitHub Actions: https://github.com/Rafallost/Water-Meters-Segmentation-Autimatization/actions"
echo "  2. Click failed workflow run"
echo "  3. Click 'Re-run failed jobs'"
echo ""
echo "Or use CLI:"
echo "  gh run list --workflow=\"Train Model\" --limit=1"
echo "  gh run rerun <RUN_ID> --failed"
