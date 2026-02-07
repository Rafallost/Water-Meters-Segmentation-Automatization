# Branch Protection Setup

This guide shows how to configure branch protection for `main` branch.

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
    - Select: `lint-and-test` (from CI Pipeline)
    - Select: `Train Model / Data Quality Assurance`
    - Select: `Train Model / aggregate-results`

**Don't select:**
- ❌ `Data Upload` - This is for data branches, not PRs

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
