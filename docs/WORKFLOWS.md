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
│  UNIFIED TRAINING DATA PIPELINE (training-data-pipeline.yaml)│
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 1. DATA MERGING & VALIDATION                            ││
│  │    • Downloads existing dataset from S3 (via DVC)       ││
│  │    • Merges: existing S3 data + new data                ││
│  │    • Validates merged dataset (pairs, resolutions)      ││
│  │    • Pakuje dataset jako GitHub Actions artifact        ││
│  │    → PASS: Continue   → FAIL: Comment on commit         ││
│  └───────────────────────┬─────────────────────────────────┘│
│                          │                                   │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 2. TRAINING (if data valid)                             ││
│  │    • Starts EC2 infrastructure (ephemeral)              ││
│  │    • Trains model ONCE on merged dataset                ││
│  │    • Logs to MLflow                                     ││
│  │    • Quality Gate: Compare vs Production baseline       ││
│  │      - IMPROVED: Both Dice AND IoU > baseline           ││
│  │      - NOT IMPROVED: Both metrics ≤ baseline            ││
│  │    • Promotes model to Production if improved           ││
│  │    • Stops EC2 infrastructure (always)                  ││
│  └───────────────────────┬─────────────────────────────────┘│
│                          │                                   │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 3. CREATE PR (ONLY if model improved)                   ││
│  │    • Creates Pull Request to main                       ││
│  │    • Includes training metrics in PR description        ││
│  │    • Auto-merge enabled                                 ││
│  │    → PR auto-merges into main                           ││
│  └─────────────────────────────────────────────────────────┘│
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼ (if model improved - PR auto-merged)
┌─────────────────────────────────────────────────────────────┐
│  MAIN BRANCH UPDATED                                        │
│     • New model promoted to Production in MLflow            │
│     • Training data (.dvc files) in main                    │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼ (manual deployment when needed)
┌─────────────────────────────────────────────────────────────┐
│  DEPLOYMENT (manual via scripts)                            │
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
  1. GitHub Actions downloads existing data from S3, merges z nowymi
  2. Validate merged dataset (resolution, pairs, masks)
  3. Training runs on EC2 (~1-2h)
  4. Quality gate: compare vs Production baseline
  5. If improved: DVC push to S3, PR created and auto-merged

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

### 2. **Unified Training Data Pipeline** (`training-data-pipeline.yaml`) ⭐ **MAIN WORKFLOW**

**Purpose:** Complete end-to-end pipeline - validate, train, create PR (only if improved)
**Triggers:** When you push to `data/*` branches (created by pre-push hook)
**Duration:** ~15-20 minutes (depends on training performance)

**What it does (6 jobs):**

#### Job 1: Data Merging & Validation (`merge-and-validate`)
- Downloads existing dataset from S3 (przez DVC + main branch hashes)
- Merges existing S3 data + new data = complete dataset
- Runs data QA validation:
  - Checks image/mask pairs match
  - Validates resolutions (512x512)
  - Ensures binary masks (0/255)
- Pakuje scalony dataset jako GitHub Actions artifact (NIE wrzuca do S3 — to dopiero po treningu)
- **Duration:** ~1-3 minutes
- **Outcomes:**
  - ✅ PASS → Continue to training
  - ❌ FAIL → Post commit comment with errors, stop workflow

#### Job 2: Start EC2 Infrastructure (`start-infra`)
- Only runs if data validation passed
- Finds/starts EC2 instance via reusable workflow
- Waits for MLflow to be healthy
- Returns MLflow URL for training
- **Duration:** ~3-5 minutes (cold start) or ~30s (warm)

#### Job 3: Training (`train`)
- **Single training run** (not 3 attempts - faster!)
- Runs na self-hosted runner (EC2)
- Pobiera dataset z GitHub Actions artifact (brak S3 download — zero kosztów przed quality gate)
- Connects to MLflow on EC2
- Trains U-Net model (50 epok, t3.large CPU, ~1-2h)
- Logs metrics to MLflow
- **Duration:** ~1-2 godziny (CPU, t3.large)

#### Job 4: Quality Gate (within `train` job)
- Fetches **dynamic baseline** from MLflow Production model
  - If no Production model: baseline = 0 (first training always passes)
  - If Production model exists: baseline = its Dice & IoU metrics
- Compares new model vs baseline:
  - **IMPROVED:** `new_dice > baseline_dice` **AND** `new_iou > baseline_iou`
  - **NOT IMPROVED:** Either metric is worse or equal
- If improved: Promotes model to Production stage
- **Duration:** ~10 seconds

#### Job 5: Stop EC2 Infrastructure (`stop-infra`)
- Stops EC2 instance to save costs
- **Always runs** (even if training failed) - critical for cost control
- **Duration:** ~10 seconds

#### Job 5b: Deploy (`deploy`) — opcjonalnie
- Uruchamia się tylko jeśli model improved
- Build Docker image → push do ECR → Helm deploy na k3s
- Wywoływany przez `deploy-model.yaml` (reusable workflow)

#### Job 6: Create PR (`create-pr`)
- **Only runs if model improved** (new behavior!)
- Creates Pull Request to main with training metrics
- PR includes:
  - Dataset summary (existing + new = total)
  - Training results table (Dice, IoU vs baseline)
  - Model promotion confirmation
- Enables auto-merge on PR
- **Duration:** ~5 seconds
- **Outcomes:**
  - 📈 **IMPROVED:** PR created and auto-merged
  - 📊 **NO IMPROVEMENT:** No PR created, data branch remains for review

**Key differences from old architecture:**
- ❌ OLD: Data pipeline creates PR → train.yml triggered by PR (often didn't work due to bot limitation)
- ✅ NEW: Single workflow - training happens BEFORE PR creation
- ❌ OLD: PR created even if model worse (required manual rejection)
- ✅ NEW: PR only created if model improved (automatic quality gate)
- ❌ OLD: Training triggered by bot PR (GitHub security prevented this)
- ✅ NEW: No bot PR triggering needed - all in one workflow
- ✅ NEW: Faster feedback - know if data is good within 15 minutes

**Why you need it:**
- Prevents useless PRs for data that doesn't improve model
- No PAT (Personal Access Token) needed
- Complete automation: push data → auto-merge (if better)
- Early failure: bad data stops before wasting EC2 time

---

### 3. **Train Model** (`train.yml`) - **DEPRECATED**

**Status:** ⚠️ Disabled for automatic triggers - manual use only

**Purpose:** Legacy training workflow (kept for manual debugging/testing)
**Triggers:** `workflow_dispatch` only (manual trigger from GitHub UI)
**Duration:** ~10-15 minutes

**Why disabled:**
Training now happens automatically in `training-data-pipeline.yaml` (before PR creation). This workflow is kept for:
- Manual model retraining (e.g., hyperparameter tuning)
- Debugging training issues
- Emergency model updates

**To manually trigger:**
```bash
gh workflow run train.yml
```

**Note:** For normal data uploads, use the unified `training-data-pipeline.yaml` workflow instead

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
# ↓ Hook creates data/YYYYMMDD-HHMMSS branch

# 3. Check GitHub Actions for progress (single workflow!)
# - training-data-pipeline.yaml:
#   → Validates data (1-3 min)
#   → Starts EC2 (3-5 min)
#   → Trains model (10-12 min)
#   → Quality gate checks improvement
#   → Stops EC2 (always)
#   → If improved: Creates PR and auto-merges ✅
#   → If not improved: No PR, workflow shows why ❌

# 4. If improved: PR auto-merged, model in Production
# 5. If not improved: Review metrics in workflow logs, improve data

# 6. (Optional) Deploy to test the new model
./devops/scripts/deploy-to-cloud.sh
# ... test the application ...
./devops/scripts/stop-cloud.sh
```

**Time:** ~15-20 minutes from push to merged (if model improves)

**Key benefits:**
- ✅ Training happens BEFORE PR creation (no wasted PRs)
- ✅ Single workflow (no bot triggering issues)
- ✅ Clear feedback in workflow logs (why model didn't improve)
- ✅ Data branch remains if model doesn't improve (review and retry)

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
- **[KNOWN_ISSUES.md](KNOWN_ISSUES.md)** - Known issues and workarounds

---

**Last updated:** 2026-02-15
**Pipeline version:** Unified (GitHub artifact transport, DVC push after quality gate)
