#!/bin/bash
# One-time setup: Configure git to use version-controlled hooks
# Usage: ./setup-hooks.sh

set -e

echo "=== Setting up Git Hooks ==="
echo ""

# Configure git to use hooks from devops/hooks directory
git config core.hooksPath devops/hooks

# Make hooks executable (for Linux/Mac)
chmod +x devops/hooks/pre-push 2>/dev/null || true

echo "[OK] Git hooks configured!"
echo ""
echo "Git will now use hooks from: devops/hooks/"
echo ""
echo "Benefits:"
echo "  - Hooks are version controlled"
echo "  - Everyone gets the same hooks"
echo "  - Updates are automatic (git pull)"
echo ""
echo "What this hook does:"
echo "  - When you push training data to main"
echo "  - Automatically creates data/YYYYMMDD-HHMMSS branch"
echo "  - Pushes there instead"
echo "  - GitHub Actions handles the rest"
echo ""
echo "Test it:"
echo "  1. Add a training image"
echo "  2. git commit -m 'test: new data'"
echo "  3. git push origin main"
echo "  4. Watch the hook redirect to data branch!"
echo ""
