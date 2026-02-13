# Branch Protection & Git Hooks

This guide explains the **two-layer protection system** for the `main` branch.

---

## 🛡️ Two-Layer Protection System

This project uses **2 complementary protection mechanisms**:

### Layer 1: Pre-Push Hook (Local) 🎣

**File:** `devops/hooks/pre-push`
**Scope:** Runs on YOUR computer before `git push`
**Purpose:** Automatically redirect training data to proper branch

**How it works:**
```bash
git push origin main
  ↓
Hook checks: Did you change WMS/data/training/?
  ↓
┌─────────────────────┬────────────────────────┐
│ YES (training data) │ NO (code/docs/config)  │
├─────────────────────┼────────────────────────┤
│ 🚫 BLOCKS push      │ ✅ ALLOWS push         │
│ Creates branch      │ Goes to Layer 2 ➡️     │
│ data/TIMESTAMP      │                        │
│ Pushes there        │                        │
└─────────────────────┴────────────────────────┘
```

**Example - Training Data:**
```bash
git add WMS/data/training/images/*.jpg
git commit -m "data: new samples"
git push origin main

# Hook intercepts:
🔍 Checking for training data changes...
🚫 Direct push to main with training data blocked
📦 Creating branch: data/20260208-142530
🚀 Pushing to data/20260208-142530...
✅ Success! Your changes are now on branch: data/20260208-142530

Next steps:
  1. GitHub Actions will validate your data
  2. If valid, a Pull Request will be created automatically
  3. Training will run automatically
  4. If model improves, PR will be auto-approved
  5. You can then merge the PR

# ERROR: [remote rejected] - THIS IS NORMAL!
# Your data was successfully pushed to the data branch
```

**Example - Code/Docs/Workflows:**
```bash
git add .github/workflows/train.yml
git commit -m "fix: update workflow"
git push origin main

# Hook allows:
🔍 Checking for training data changes...
# No training data changes detected
# ✅ Push continues to Layer 2 (Branch Protection)
```

---

### Layer 2: Branch Protection (GitHub) 🔒

**Scope:** Enforced on GitHub servers
**Purpose:** Ensure code quality through PR process

**Rules:**
- ✅ All changes through Pull Requests (except owner)
- ✅ Required status checks must pass
- ✅ Owner can bypass (for code/docs/workflows)
- ✅ Others CANNOT bypass (forced to use PRs)

**Owner vs Others:**
| Who | Push to main | Result |
|-----|--------------|--------|
| **Owner (you)** | Code/docs/workflows | ✅ Allowed (bypass permission) |
| **Owner (you)** | Training data | 🚫 Blocked by hook → redirected to `data/*` |
| **Contributors** | Anything | 🚫 Blocked → must use PR |

---

## 🎯 Complete Flow Examples

### Scenario 1: Owner Adds Training Data

```bash
# 1. You modify training data
git add WMS/data/training/
git commit -m "data: add 10 new samples"
git push origin main

# 2. Pre-push hook intercepts (Layer 1)
→ Creates data/20260208-142530
→ Pushes there
→ Blocks push to main

# 3. GitHub Actions trigger automatically (training-data-pipeline.yaml)
→ merge-and-validate: downloads existing S3 data, merges, validates
→ start-infra: starts EC2
→ train: up to 3 attempts (different seeds), quality gate after each
→ stop-infra: stops EC2 (always runs)

# 4. If model improved:
→ create-pr: creates PR to main
→ auto-merge: enables auto-merge on PR

# 5. Done! Zero manual work after initial push
```

---

### Scenario 2: Owner Modifies Code/Docs

```bash
# 1. You fix a bug in training code
git add WMS/src/train.py
git commit -m "fix: correct loss calculation"
git push origin main

# 2. Pre-push hook checks (Layer 1)
→ No training data changes
→ ✅ Allows push

# 3. Branch protection checks (Layer 2)
→ You're owner with bypass permission
→ ✅ Allows push

# 4. Commit goes directly to main
remote: Bypassed rule violations for refs/heads/main
To github.com:Rafallost/Water-Meters-Segmentation-Autimatization.git
   abc1234..def5678  main -> main

# Note: No tests run BEFORE merge (you bypassed)
# But release-deploy.yaml may trigger if you changed serve code
```

**⚠️ Best Practice:** For large code changes, use PR even as owner:
```bash
git checkout -b feature/major-refactor
git push origin feature/major-refactor
# Create PR → Tests run → Review → Merge
```

---

### Scenario 3: Contributor Adds Training Data

```bash
# 1. Contributor has hook installed
git add WMS/data/training/
git commit -m "data: new samples"
git push origin main

# 2. Pre-push hook intercepts (Layer 1)
→ Creates data/20260208-150000
→ Pushes there
→ Same flow as Scenario 1

# 3. Auto-PR created, training runs, auto-merge if improved
```

---

### Scenario 4: Contributor Tries to Push Code (BLOCKED)

```bash
# 1. Contributor tries to push code
git add WMS/src/train.py
git commit -m "fix: bug"
git push origin main

# 2. Pre-push hook checks (Layer 1)
→ No training data changes
→ ✅ Allows (hook doesn't block code)

# 3. Branch protection checks (Layer 2)
→ Contributor is NOT owner
→ 🚫 BLOCKS push

# Error:
remote: error: GH006: Protected branch update failed
remote: Changes must be made through a pull request

# Solution: Use PR
git checkout -b fix/bug
git push origin fix/bug
# Create PR on GitHub
```

---

## 📋 Summary Table

| Change Type | Owner | Contributor |
|-------------|-------|-------------|
| **Training data** | Hook → `data/*` branch → PR → Auto-merge | Hook → `data/*` branch → PR → Auto-merge |
| **Code (small fix)** | Direct push to main ✅ | ❌ Blocked → Must use PR |
| **Code (large change)** | PR recommended (optional) | ❌ Must use PR |
| **Docs/Workflows** | Direct push to main ✅ | ❌ Blocked → Must use PR |

---

## 🔧 Installing the Pre-Push Hook

The hook is already installed if you cloned with submodules. To install manually:

```bash
# Option 1: Use install script (recommended)
bash devops/scripts/install-git-hooks.sh

# Option 2: Manual copy
cp devops/hooks/pre-push .git/hooks/pre-push
chmod +x .git/hooks/pre-push

# Option 3: Set hooks path (all hooks from devops/hooks/)
git config core.hooksPath devops/hooks
```

**Verify installation:**
```bash
ls -la .git/hooks/pre-push
# Should show file with execute permissions
```

**Test the hook:**
```bash
# This should trigger hook:
touch WMS/data/training/images/test.jpg
git add WMS/data/training/images/test.jpg
git commit -m "test: hook"
git push origin main
# Should create data/TIMESTAMP branch

# Cleanup
git reset HEAD~1
rm WMS/data/training/images/test.jpg
git push origin --delete data/$(date +%Y%m%d)*  # Delete test branch
```

---

## Why Branch Protection?

**Without protection:**
- Anyone can push directly to `main`
- No code review required
- Risky for production code

**With protection:**
- ✅ Only PRs can update `main`
- ✅ Required checks must pass
- ✅ Only repository owner can bypass (emergency)
- ✅ Auto-merge works correctly

---

## Setup Instructions

### Step 1: Go to Branch Protection Settings

1. Go to your repository: https://github.com/Rafallost/Water-Meters-Segmentation-Autimatization
2. Click **Settings** tab
3. In left sidebar, click **Branches**
4. Under "Branch protection rules", click **Add branch protection rule**

---

### Step 2: Configure Rule

**Branch name pattern:**
```
main
```

**Enable these settings:**

#### ✅ Require a pull request before merging
- ☑ **Require a pull request before merging**
  - ☐ Require approvals: **0** (auto-merge will approve)
  - ☑ **Dismiss stale pull request approvals when new commits are pushed**
  - ☑ **Require review from Code Owners** (optional)
  - ☑ **Allow specified actors to bypass required pull requests**
    - Add: **Rafallost** (your username) - allows you to force-push in emergencies

#### ✅ Require status checks to pass before merging
- ☑ **Require status checks to pass before merging**
  - ☑ **Require branches to be up to date before merging**
  - **Status checks that are required:**
    - Select: `merge-and-validate` (from training-data-pipeline.yaml)
    - Select: `Train Model` (from training-data-pipeline.yaml)

**Don't select:**
- ❌ `start-infra` / `stop-infra` - infrastructure jobs, not quality gates

#### ✅ Require conversation resolution before merging
- ☑ **Require conversation resolution before merging** (optional)

#### ✅ Do not allow bypassing the above settings
- ☐ **Do not allow bypassing the above settings** (keep UNCHECKED)
  - This allows you (owner) to bypass in emergencies

#### Other settings (optional):
- ☐ Require signed commits
- ☐ Require linear history
- ☐ Require merge queue
- ☑ **Require deployments to succeed** (if you set up deployments)
- ☑ **Lock branch** (prevents all changes - only for archived branches)
- ☐ Do not allow force pushes
- ☑ **Allow deletions** (allows branch deletion after merge)

---

### Step 3: Save

Click **Create** button at the bottom.

---

## What This Means

### ✅ You CAN:
- Create PRs and merge them (if checks pass)
- Use auto-merge (workflow will merge automatically)
- **Bypass protection as repo owner** (emergency only!)

### ❌ You CANNOT (without PR):
- `git push origin main` directly
- Force push to main
- Delete main branch

### ⚠️ To Bypass (Emergency):
```bash
# If you REALLY need to push directly (not recommended!)
git push origin main --force

# GitHub will show warning but allow it (you're the owner)
```

**But you should NEVER need this!** Use PRs instead.

---

## Auto-Merge Workflow

With branch protection + auto-merge:

```
1. Push data → data/YYYYMMDD-HHMMSS branch
2. Workflow creates PR automatically
3. Checks run:
   ✅ CI Pipeline (lint + tests)
   ✅ Train Model → Data QA → Training → Quality Gate
4. If model improves:
   - Auto-approve PR
   - Enable auto-merge
   - GitHub waits for all checks ✅
   - GitHub auto-merges (squash)
   - Branch auto-deleted
5. Done! Zero manual work.
```

---

## Testing Branch Protection

After setup, try:

```bash
# This should FAIL:
git checkout main
git commit --allow-empty -m "test: direct push"
git push origin main

# Error: "protected branch hook declined"
# ✅ Good! Protection is working.
```

```bash
# This should WORK:
git checkout -b test-branch
git commit --allow-empty -m "test: via PR"
git push origin test-branch
# Create PR on GitHub
# Merge PR
# ✅ Success!
```

---

## Troubleshooting

### "Auto-merge failed"

**Possible reasons:**
1. Required checks didn't pass
2. Branch protection not configured
3. Missing "Allow auto-merge" in repo settings

**Fix:**
1. Go to Settings → General
2. Scroll to "Pull Requests"
3. Check ☑ **Allow auto-merge**
4. Save

### "You can't merge this PR"

**Reason:** Not all required checks passed

**Fix:**
- Wait for checks to complete
- Fix any failing checks
- Push fixes to the PR branch

### "Workflow can't enable auto-merge"

**Reason:** GITHUB_TOKEN lacks permissions

**Fix:** Already done - we have `contents: write` permission

---

## Updating Protection Rules

To modify rules:
1. Go to Settings → Branches
2. Find "main" rule
3. Click **Edit**
4. Make changes
5. Click **Save changes**

---

## Summary

**Current setup:**
- ✅ Main branch protected
- ✅ PRs required
- ✅ Checks required (CI + Training)
- ✅ Auto-merge enabled
- ✅ Owner can bypass (emergency)

**Workflow:**
- Push data → PR auto-created → Checks run → Auto-merge if improved
- **Zero manual steps!**

**Security:**
- No accidental pushes to main
- All changes reviewed by CI
- Quality gate ensures good models only
- You keep admin override
