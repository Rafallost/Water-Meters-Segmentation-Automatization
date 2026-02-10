# Workflows & Pipelines Explained

This document explains **all GitHub Actions workflows** in this project and when they run.

**Last updated:** 2026-02-10 (Simplified Pipeline Implementation)

---

## 🎯 Overview: The Complete Flow

```
┌─────────────────────────────────────────────────────────────┐
│  USER ADDS NEW TRAINING DATA (locally)                      │
│  WMS/data/training/images/new_image.jpg                     │
│  WMS/data/training/masks/new_mask.jpg                       │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼ (git commit + git push origin main)
┌─────────────────────────────────────────────────────────────┐
│  PRE-PUSH HOOK (local git hook - NO AWS CREDENTIALS!)      │
│     • Detects new training data                             │
│     • Creates branch: data/YYYYMMDD-HHMMSS                  │
│     • Pushes NEW files to branch                            │
│     • Blocks push to main                                   │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  1. DATA MERGING & VALIDATION (training-data-pipeline.yaml) │
│     • Downloads existing dataset from S3 (GitHub Actions)   │
│     • Merges: existing S3 data + new data                   │
│     • Validates merged dataset (pairs, resolutions, masks)  │
│     • Updates DVC tracking with merged dataset              │
│     • Creates Pull Request to main                          │
│     → PASS: PR created   → FAIL: Comment on commit          │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼ (PR triggers training)
┌─────────────────────────────────────────────────────────────┐
│  2. TRAINING (train.yml) - SINGLE RUN                       │
│     • Data QA validation                                    │
│     • Starts EC2 infrastructure (ephemeral)                 │
│     • Trains model ONCE on full merged dataset              │
│     • Logs to MLflow                                        │
│     • Quality Gate: Compare vs Production baseline          │
│       - Fetches baseline from MLflow dynamically            │
│       - IMPROVED: Both Dice AND IoU > baseline              │
│     → IMPROVED: Promote + Auto-approve + Auto-merge         │
│     → NOT IMPROVED: Fail workflow, reject PR                │
│     • Stops EC2 infrastructure (always)                     │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼ (if model improved and PR merged)
┌─────────────────────────────────────────────────────────────┐
│  3. MAIN BRANCH UPDATED                                     │
│     • New model promoted to Production in MLflow            │
│     • model-metadata.json updated                           │
│     • Training data (.dvc files) in main                    │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼ (manual deployment when needed)
┌─────────────────────────────────────────────────────────────┐
│  4. DEPLOYMENT (manual via scripts)                         │
│     • ./devops/scripts/deploy-to-cloud.sh                   │
│     • Starts EC2, deploys app with Helm                     │
│     • Access MLflow UI and model API                        │
│     • ./devops/scripts/stop-cloud.sh when done              │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 All Workflows Explained

### 1. **Pre-Push Hook** (`.git/hooks/pre-push`)

**Type:** Local Git hook (not a GitHub Action)
**Triggers:** When you run `git push origin main` with training data changes
**Duration:** ~5-10 seconds (fast - no S3 download!)

**What it does:**
1. Detects raw image/mask files in `WMS/data/training/`
2. Creates timestamped branch: `data/YYYYMMDD-HHMMSS`
3. Commits **new files only** to branch
4. Pushes branch to GitHub
5. **Blocks** push to main (exits with error)

**Note:** Data merging happens in GitHub Actions (no local AWS credentials needed!)

**Example output:**
```
🔍 Checking for training data changes...
╔════════════════════════════════════════════════════════════╗
║  🔍 Raw training data detected                             ║
╚════════════════════════════════════════════════════════════╝

📦 New files detected:
   • Images: 2
   • Masks: 2

Detected files:
  • WMS/data/training/images/id_49_image.jpg
  • WMS/data/training/masks/id_49_mask.png

🌿 Creating data branch: data/20260210-123456
💾 Committing new training data...
🚀 Pushing to remote: data/20260210-123456

╔════════════════════════════════════════════════════════════╗
║  ✅ SUCCESS - New data pushed to branch                    ║
╚════════════════════════════════════════════════════════════╝

What happens next:
  1. GitHub Actions will download existing data from S3
  2. Merge: existing S3 data + your new data = complete dataset
  3. Validate merged dataset (resolution, pairs, masks)
  4. Create Pull Request with merged dataset
  5. Training pipeline will run automatically

Branch: data/20260210-123456
Track: https://github.com/Rafallost/.../actions

ℹ️  No AWS credentials needed - merging happens in GitHub Actions!
```

**Why this approach:**
- ✅ Every training run uses **complete historical data** (not just new samples)
- ✅ Automatic merging in GitHub Actions (no local AWS setup!)
- ✅ S3 is single source of truth for training data
- ✅ Raw files never reach main branch
- ✅ Fast hook execution (<10 seconds)

**Prerequisites:**
- Pre-push hook installed (run `./devops/scripts/install-git-hooks.sh`)
- **No AWS credentials needed locally!** (merging happens in CI)

---

### 2. **Training Data Pipeline** (`training-data-pipeline.yaml`)

**Purpose:** Merge data from S3, validate, and create PR
**Triggers:** When you push to `data/*` branches (created by pre-push hook)
**Duration:** ~1-3 minutes (depends on S3 dataset size)

**What it does:**
1. **Downloads existing dataset from S3** (using GitHub secrets for AWS credentials)
2. **Merges** existing S3 data + new data = complete dataset
3. **Runs data QA validation**
   - Checks image/mask pairs match
   - Validates resolutions (512x512)
   - Ensures binary masks (0/255)
4. **Updates DVC tracking** with merged dataset
5. **Commits merged data** back to data branch
6. **If PASS:** Creates Pull Request to main with validation report
7. **If FAIL:** Posts commit comment with errors

**PR Description includes:**
- Validation report (image count, resolution, coverage)
- **Dataset summary:** Existing + New = Total images
- Quality gate rules
- Next steps (training will run automatically)

**Outcomes:**
- ✅ PASS → PR created with **merged dataset**, training workflow triggered
- ❌ FAIL → Commit comment with errors, no PR

**Why you need it:**
- Prevents wasting compute on invalid data
- **Data merging happens in CI** (no local AWS credentials needed)
- Every training uses complete historical dataset

---

### 3. **Train Model** (`train.yml`) ⭐ **MAIN WORKFLOW**

**Purpose:** Train model with ephemeral infrastructure and quality gate
**Triggers:** On pull request to main (when training data changes detected)
**Duration:** ~10-15 minutes (single run, time-optimized)

**What it does:**

#### Job 1: Data QA (`data-qa`)
- Re-validates data on PR
- Posts validation report as PR comment
- **Duration:** ~20 seconds

#### Job 2: Start EC2 Infrastructure (`start-infra`)
- Finds/starts EC2 instance via Terraform
- Waits for MLflow to be healthy
- Returns MLflow URL for training
- **Duration:** ~30-60 seconds (if already running) or ~3-5 min (cold start)

#### Job 3: Training (`train`)
- **Single training run** (not 3 attempts - faster!)
- Runs on GitHub-hosted runners (free!)
- Downloads training data from branch (already merged)
- Connects to MLflow on EC2
- Trains U-Net model
- Logs metrics to MLflow
- **Duration:** ~10-12 minutes

#### Job 4: Quality Gate (`train` job, `quality_gate` step)
- Fetches **dynamic baseline** from MLflow Production model
  - If no Production model: baseline = 0 (first training always passes)
  - If Production model exists: baseline = its Dice & IoU metrics
- Compares new model vs baseline:
  - **IMPROVED:** `new_dice > baseline_dice` **AND** `new_iou > baseline_iou`
  - **NOT IMPROVED:** Either metric is worse or equal
- **Duration:** ~5 seconds

#### Job 5: Model Promotion (if improved)
- Creates new model version in MLflow Model Registry
- Transitions to Production stage
- Archives old Production models
- Updates `model-metadata.json` in Git
- **Duration:** ~10 seconds

#### Job 6: Auto-Approve & Comment
- Posts PR comment with training results (table with metrics)
- If improved: Auto-approves PR
- If not improved: PR remains unapproved, workflow fails
- **Duration:** ~5 seconds

#### Job 7: Stop EC2 Infrastructure (`stop-infra`)
- Stops EC2 instance to save costs
- **Always runs** (even if training failed)
- **Duration:** ~10 seconds

#### Job 8: Auto-Merge (if improved)
- Enables auto-merge on PR (squash merge)
- Deletes branch after merge
- **Duration:** ~5 seconds

**Outcomes:**
- 📈 **IMPROVED:** Model promoted to Production, PR auto-approved and auto-merged
- 📊 **NO IMPROVEMENT:** Workflow fails, PR blocked, detailed comment explains why

**Key differences from old pipeline:**
- ❌ OLD: 3 training attempts (30-45 minutes)
- ✅ NEW: 1 training attempt (10-15 minutes) → **66% faster**
- ❌ OLD: Hardcoded baseline (Dice 0.9275)
- ✅ NEW: Dynamic baseline from MLflow Production model
- ❌ OLD: Complex aggregation logic
- ✅ NEW: Simple comparison: new > baseline

**Cost savings:** EC2 runs ~10-15 min/training instead of 30-45 min

---

### 4. **EC2 Control** (`ec2-control.yaml`)

**Purpose:** Reusable workflow for starting/stopping EC2
**Triggers:** Called by other workflows (not directly)
**Duration:** ~30 seconds (start) or ~10 seconds (stop)

**What it does:**
- `action: start` → Terraform apply, wait for MLflow health
- `action: stop` → Terraform destroy

**Used by:**
- `train.yml` (start before training, stop after)
- Manual deployment scripts

---

### 5. **Manual EC2 Control** (`ec2-manual-control.yaml`)

**Purpose:** Manual EC2 start/stop for debugging
**Triggers:** Manual dispatch from GitHub Actions UI
**Duration:** ~3-5 minutes

**Usage:**
```bash
# Start EC2
gh workflow run ec2-manual-control.yaml -f action=start

# Stop EC2
gh workflow run ec2-manual-control.yaml -f action=stop
```

**Why you need it:** For debugging, manual model downloads, or testing deployment without training.

---

### 6. **CI Pipeline** (`ci.yaml`)

**Purpose:** Run tests on code changes
**Triggers:** On push to main or pull requests (code changes only)
**Duration:** ~1-2 minutes

**What it does:**
- Linting (flake8, ruff)
- Unit tests (pytest)
- Code quality checks

**Why you need it:** Ensures code quality before merge.

---

### 7. **Release & Deploy** (`release-deploy.yaml`)

**Purpose:** (Optional) Automated deployment on release
**Triggers:** On release publish or manual dispatch
**Duration:** ~5-10 minutes

**What it does:**
- Build Docker image
- Push to ECR
- Deploy to k3s with Helm
- Run smoke tests

**Note:** This is optional. The primary deployment method is the manual scripts (`deploy-to-cloud.sh`).

---

## 🚀 Manual Deployment Scripts

### `devops/scripts/deploy-to-cloud.sh`

**Purpose:** Deploy application to AWS EC2 for demos/testing
**Usage:**
```bash
./devops/scripts/deploy-to-cloud.sh
```

**What it does:**
1. Checks Terraform and AWS credentials
2. Runs `terraform apply` to start EC2
3. Waits for MLflow server to be ready
4. (Optional) Deploys app with Helm to k3s
5. Provides access URLs

**Access after deployment:**
- MLflow UI: `http://<EC2_IP>:5000`
- Model API: `http://<EC2_IP>:8000` (if Helm deployed)
- API Docs: `http://<EC2_IP>:8000/docs`

**Duration:** ~3-5 minutes

### `devops/scripts/stop-cloud.sh`

**Purpose:** Stop infrastructure to save costs
**Usage:**
```bash
./devops/scripts/stop-cloud.sh
```

**What it does:**
1. Runs `terraform destroy`
2. Stops billing

**⚠️ IMPORTANT:** Always run this when done testing! Costs ~$0.10/hour when running.

---

## 📊 Typical User Workflow

### Scenario: Add new training data

```bash
# 1. Add new images locally
cp /path/to/new/*.jpg WMS/data/training/images/
cp /path/to/new/*.png WMS/data/training/masks/

# 2. Commit and push (pre-push hook intercepts)
git add WMS/data/training/
git commit -m "data: add 5 new water meter images"
git push origin main
# ↓ Hook merges with S3 data, creates data/YYYYMMDD-HHMMSS branch

# 3. Check GitHub Actions for progress
# - training-data-pipeline.yaml validates → creates PR
# - train.yml runs training → quality gate → auto-approve if improved

# 4. If improved: PR auto-merges, model promoted to Production

# 5. (Optional) Deploy to test the new model
./devops/scripts/deploy-to-cloud.sh
# ... test the application ...
./devops/scripts/stop-cloud.sh
```

**Time:** ~10-15 minutes from push to merged (if model improves)

---

## 🔧 Troubleshooting Workflows

### Training fails with "No training data found"

**Cause:** Data wasn't properly merged in GitHub Actions

**Fix:**
1. Check that pre-push hook is installed: `ls -la .git/hooks/pre-push`
2. Check GitHub Actions logs for `training-data-pipeline.yaml` workflow
3. Verify AWS secrets are configured in GitHub (repository settings → Secrets)
4. Re-push to trigger workflow: `git commit --allow-empty -m "retry" && git push`

### Quality gate fails: "Model did not improve"

**Cause:** New model metrics ≤ Production baseline

**Fix:**
1. Check PR comment for exact metrics comparison
2. Options:
   - Add more/better training data
   - Adjust hyperparameters in `WMS/configs/train.yaml`
   - Close PR and try again with different data

### EC2 doesn't stop after training

**Cause:** Workflow failed before `stop-infra` job

**Fix:**
1. Manually stop: `gh workflow run ec2-manual-control.yaml -f action=stop`
2. Or run: `./devops/scripts/stop-cloud.sh`

---

## 📖 Related Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - System design and diagrams
- **[USAGE.md](USAGE.md)** - Complete usage guide
- **[KNOWN_ISSUES.md](../KNOWN_ISSUES.md)** - Known issues and workarounds
- **[IMPLEMENTATION_SUMMARY.md](../IMPLEMENTATION_SUMMARY.md)** - Simplified pipeline details

---

**Last updated:** 2026-02-10
**Pipeline version:** Simplified (single run, data merging, dynamic baseline)
