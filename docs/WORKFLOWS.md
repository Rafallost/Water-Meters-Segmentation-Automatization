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
│  PRE-PUSH HOOK (local git hook)                             │
│     • Downloads existing data from S3 via DVC               │
│     • Merges: existing + new = complete dataset             │
│     • Creates branch: data/YYYYMMDD-HHMMSS                  │
│     • Pushes merged dataset to branch                       │
│     • Blocks push to main                                   │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  1. DATA VALIDATION (training-data-pipeline.yaml)           │
│     • Validates image/mask pairs                            │
│     • Checks resolutions and binary masks                   │
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
**Duration:** ~2-5 minutes (depends on S3 download size)

**What it does:**
1. Detects raw image/mask files in `WMS/data/training/`
2. Verifies AWS credentials are configured
3. Downloads existing dataset from S3 using DVC (if `.dvc` files exist)
4. Merges existing data + new data = complete dataset
5. Creates timestamped branch: `data/YYYYMMDD-HHMMSS`
6. Commits merged dataset to branch
7. Pushes branch to GitHub
8. **Blocks** push to main (exits with error)

**Example output:**
```
🔍 Checking for training data changes...
📦 Raw training data detected - Starting merge process

Detected 2 new file(s):
  WMS/data/training/images/id_49_image.jpg
  WMS/data/training/masks/id_49_mask.png

🔐 Verifying AWS credentials...
✅ AWS credentials valid

📥 Downloading existing dataset from S3...
✅ Downloaded 48 existing images

📦 Merging datasets...
  • Existing images: 48
  • New images: 2
  • Total: 50 images

🌿 Creating data branch: data/20260210-123456
✅ Merged dataset ready: 50 images
🚀 Pushing to remote branch: data/20260210-123456

╔════════════════════════════════════════════════════════════╗
║  ✅ SUCCESS - Data merged and pushed to branch             ║
╚════════════════════════════════════════════════════════════╝

What happened:
  ✓ Downloaded 48 existing images from S3
  ✓ Merged with 2 new images
  ✓ Total dataset: 50 images
  ✓ Pushed to branch: data/20260210-123456

Next steps:
  1. GitHub Actions will validate the merged dataset
  2. Pull Request will be created automatically
  3. Training pipeline will run on the full dataset
  4. Quality gate compares new model vs baseline
  5. If improved, PR auto-approved and merged
```

**Why this approach:**
- ✅ Every training run uses **complete historical data** (not just new samples)
- ✅ Automatic merging - user doesn't manually manage DVC
- ✅ S3 is single source of truth for training data
- ✅ Raw files never reach main branch

**Prerequisites:**
- DVC installed locally
- AWS credentials configured (`~/.aws/credentials` or env vars)
- Pre-push hook installed (run `./devops/scripts/install-git-hooks.sh`)

---

### 2. **Training Data Pipeline** (`training-data-pipeline.yaml`)

**Purpose:** Validate data and create PR
**Triggers:** When you push to `data/*` branches (created by pre-push hook)
**Duration:** ~30-45 seconds

**What it does:**
1. Runs data QA validation
   - Checks image/mask pairs match
   - Validates resolutions
   - Ensures binary masks (0/255)
2. Counts training data (images/masks)
3. **If PASS:** Creates Pull Request to main with validation report
4. **If FAIL:** Posts commit comment with errors

**PR Description includes:**
- Validation report (image count, resolution, coverage)
- Dataset details (existing + new = total)
- Quality gate rules
- Next steps (training will run automatically)

**Outcomes:**
- ✅ PASS → PR created, training workflow triggered
- ❌ FAIL → Commit comment with errors, no PR

**Why you need it:** Prevents wasting compute on invalid data.

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

**Cause:** Data wasn't properly merged/pushed by pre-push hook

**Fix:**
1. Check that pre-push hook is installed: `ls -la .git/hooks/pre-push`
2. Check AWS credentials: `aws sts get-caller-identity`
3. Re-run: `git push origin main`

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
