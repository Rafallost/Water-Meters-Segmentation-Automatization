# Usage Guide - How to Use This System

Step-by-step guide for everyday operations.

---

## 🎯 Quick Start: Upload New Training Data

This is the **most common workflow** you'll use.

### Step 1: Prepare Your Data Locally

```bash
# Navigate to your project
cd Water-Meters-Segmentation-Automatization

# Add new images and masks
cp /path/to/new/*.jpg WMS/data/training/images/
cp /path/to/new/*.png WMS/data/training/masks/

# Verify data quality locally (optional but recommended)
python devops/scripts/data-qa.py WMS/data/training/ --output report.json
cat report.json
```

**Requirements:**

- Images: `.jpg` or `.png` format
- Masks: `.png` format (binary: 0 and 255 only)
- Naming: `image_name.jpg` must have corresponding `image_name.png` mask
- Resolution: Preferably 512×512 (or consistent across dataset)

---

### Step 2: Commit and Push Data (Pre-push Hook Handles Rest!)

```bash
# Install pre-push hook (one-time setup)
./devops/scripts/install-git-hooks.sh

# Add and commit data
git add WMS/data/training/
git commit -m "data: add 5 new water meter images"

# Try to push to main - hook will intercept!
git push origin main

# Hook automatically:
# 1. Creates data/YYYYMMDD-HHMMSS branch
# 2. Pushes your new files to that branch
# 3. Blocks push to main
# 4. GitHub Actions will merge with S3 data
# 5. PR will be created automatically

# ℹ️  No AWS credentials needed locally!
```

---

### Step 3: Wait for Training (~10-15 minutes)

The automated pipeline runs:

```
Data Merging → Data QA → GitHub artifact → EC2 starts → Train ONCE → Quality Gate → EC2 stops
                                                                              ↓ if improved:
                                                              dvc push → PR created → auto-merge
```

**Monitor progress:**

- Go to: https://github.com/YOUR_USERNAME/Water-Meters-Segmentation-Automatization/actions
- Check workflow: `training-data-pipeline`

**What happens:**

1. **Data Merging** (~1-3 min): Downloads S3 data, merges z nowymi, pakuje jako artifact
2. **Data QA** (~30 sec): Validates merged dataset
3. **EC2 start** (~3-5 min): Uruchamia instancję z MLflow
4. **Training** (~1-2h): Single run na t3.large CPU, 50 epok
5. **Quality Gate**: Compares against Production baseline (dynamic)
6. **Jeśli improved**: dvc push, PR created, auto-merge

---

### Step 4: Review Training Results

The workflow posts a comment on your PR with:

#### ✅ Success Example:

```
## ✅ Training Results

📈 MODEL IMPROVED

### Comparison vs Production Baseline
| Metric | New Model | Production | Change  | Status |
|--------|-----------|------------|---------|--------|
| Dice   | 0.9350    | 0.9275     | +0.81%  | ✅     |
| IoU    | 0.8920    | 0.8865     | +0.62%  | ✅     |

### Training Details
- Dataset: 49 images (merged: 25 existing + 24 new)
- Training time: ~12 minutes
- Baseline: Dynamically fetched from MLflow Production model

🚀 Model promoted to Production and PR auto-approved!
```

**If model improved:** PR is auto-approved and auto-merged.

#### ❌ Failure Example:

```
## ❌ Training Results

📊 No improvement

| Metric | New Model | Production | Improved |
|--------|-----------|------------|----------|
| Dice   | 0.9050    | 0.9275     | ❌       |
| IoU    | 0.8650    | 0.8865     | ❌       |

⚠️ No improvement - no PR created, data branch remains for review
```

**If no improvement:** PR NIE jest tworzony. Branch `data/TIMESTAMP` pozostaje — przejrzyj logi i spróbuj z lepszymi danymi.

---

### Step 5: PR i auto-merge

**Jeśli model improved:** PR jest tworzony automatycznie i auto-merge jest włączony. Możesz też scalić ręcznie:

```bash
gh pr merge <PR_NUMBER> --squash
```

**Jeśli model nie improved:** PR nie zostaje stworzony. Branch `data/TIMESTAMP` pozostaje. Wróć do kroku 1 z lepszymi/większą ilością danych.

---

## 🤖 Using the Production Model Locally

The latest trained model lives in **MLflow Production stage**, not in Git.

**⚠️ IMPORTANT:** Models are NOT stored in Git repository. After cloning this repo, you MUST download the Production model manually (one-time setup). The model is then cached locally for offline use.

**When to download:**

- ✅ **Required:** After first `git clone` (no model in repo)
- ✅ **Optional:** After new model is trained (to get latest version)
- ❌ **NOT needed:** After `git pull` or `git push` (model cached locally)

### Download Production Model

**🚀 Automatic Method (Recommended):**

```bash
# One command - does everything automatically!
python WMS/scripts/sync_model.py

# What it does:
# 1. Starts EC2 via GitHub Actions
# 2. Waits for MLflow to be ready
# 3. Downloads Production model
# 4. Asks if you want to stop EC2
```

**Windows users:** Just double-click `sync_model.bat` in project root!

**📋 Manual Method (Alternative):**

```bash
# 1. Start EC2
gh workflow run ec2-manual-control.yaml -f action=start

# 2. Wait ~3 minutes, then check workflow output for IP:
gh run list --workflow=ec2-manual-control.yaml --limit=1
gh run view <RUN_ID>  # Look for "Public IP" in summary

# 3. Download model
python WMS/src/download_model.py --mlflow-uri http://<EC2_IP>:5000

# 4. Stop EC2 (optional)
gh workflow run ec2-manual-control.yaml -f action=stop
```

### Run Predictions

```bash
# After downloading, predictions work offline
python WMS/src/predicts.py

# Models are cached locally (gitignored)
# Re-download when new Production model available:
python WMS/src/download_model.py --force
```

### Alternative: Load Directly from MLflow

```python
import mlflow
import mlflow.pytorch

mlflow.set_tracking_uri("http://<EC2_IP>:5000")
model = mlflow.pytorch.load_model("models:/water-meter-segmentation/production")
```

### Browse Models in MLflow UI

```
Open in browser: http://<EC2_IP>:5000

1. Click "Models"
2. Click "water-meter-segmentation"
3. See all versions with metrics
4. "Production" stage = latest deployed model
```

---

## 🛠️ Model Management Scripts

Complete reference for all model management tools.

### sync_model_aws.py - Download Production Model

**Purpose:** Automatically download the latest Production model from MLflow.

**Usage:**

```bash
# Basic usage - download model
python WMS/scripts/sync_model_aws.py

# Re-download even if cached
python WMS/scripts/sync_model_aws.py --force

# Keep EC2 running (for multiple operations)
python WMS/scripts/sync_model_aws.py --no-stop

# Windows: just double-click
sync_model_aws.bat
```

**What it does:**

1. ✅ Checks AWS CLI and credentials
2. ✅ Finds EC2 instance (tag: wms-k3s)
3. ✅ Starts EC2 if stopped (~3 min)
4. ✅ Waits for MLflow to be ready (~2-5 min)
5. ✅ Downloads Production model to `WMS/models/production.pth`
6. ✅ Asks if you want to stop EC2

**When to use:**

- After first `git clone` (required)
- After merging PR with improved model
- When you see "No model found" error

**Time:** ~5-7 minutes (includes EC2 startup)
**Cost:** ~$0.01 per run (EC2 runs briefly then stops)

---

### show_metrics.py - Check Model Performance

**Purpose:** Quickly view Production model metrics and quality assessment.

**Usage:**

```bash
# Show Production model metrics
python WMS/scripts/show_metrics.py

# Show all model versions
python WMS/scripts/show_metrics.py --all
```

**Example output:**

```
============================================================
PRODUCTION MODEL - Version 14
============================================================

Run ID: d8f1681809f4467e8235b56a6f4d86dd
Created: 2026-02-08 02:36:55
Status: FINISHED

Metrics:
    test_dice: 0.3161
    test_iou: 0.1945
    test_loss: 0.5184
    val_dice: 0.3240
    val_iou: 0.1945

Key Parameters:
    learning_rate: 0.0001
    batch_size: 4
    epochs: 50

============================================================
❌ POOR MODEL (Dice < 50%) - Retraining recommended!
============================================================
```

**Quality thresholds:**

- ✅ **Excellent:** Dice ≥ 85%
- ⚠️ **Good:** Dice 70-85%
- ⚠️ **Mediocre:** Dice 50-70%
- ❌ **Poor:** Dice < 50%

**Requires:** EC2 running with MLflow accessible

---

### check_model.py - Manage Model Versions

**Purpose:** View all model versions and promote models to Production stage.

**Usage:**

```bash
python WMS/scripts/check_model.py
```

**What it does:**

1. Lists all model versions (1-14 in your case)
2. Shows current stage for each (Production, Staging, None)
3. If no Production model, offers to promote latest version
4. Interactive prompt for confirmation

**Example output:**

```
Found 14 version(s):

  Version 14:
    Stage: Production <<< PRODUCTION
    Run ID: d8f168180...

  Version 13:
    Stage: None
    Run ID: abc123...

  Version 12:
    Stage: None
    Run ID: def456...

[OK] 1 version(s) in Production stage

You can now download the model:
  python WMS/scripts/sync_model_aws.py
```

**When to use:**

- Check which model is currently Production
- Manually promote a specific version
- After training to verify new model was registered

---

### predicts.py - Run Predictions

**Purpose:** Generate segmentation masks for new water meter images.

**Usage:**

```bash
# 1. Place images in this folder:
WMS/data/predictions/photos_to_predict/

# 2. Run predictions
python WMS/src/predicts.py

# 3. Results saved to:
WMS/data/predictions/predicted_masks/
```

**Model loading priority:**

1. `WMS/models/production.pth` (downloaded from MLflow) ✅
2. `WMS/models/best.pth` (legacy, if exists)
3. Error if no model found (with download instructions)

**Supported formats:** `.jpg`, `.png`

**Output:** Binary masks (0/255) showing water meter regions

---

## 🔄 Complete Workflow Example

### Scenario: Train new model, download, and use for predictions

```bash
# 1. Add new training data
cp /path/to/images/*.jpg WMS/data/training/images/
cp /path/to/masks/*.png WMS/data/training/masks/

# 2. Commit and push (triggers training)
git add WMS/data/training/
git commit -m "data: add 10 new samples"
git push

# 3. Wait for GitHub Actions workflow (~10 min)
# Check PR for training results

# 4. Check metrics of new model
python WMS/scripts/show_metrics.py --all

# 5. If satisfied, merge PR (or auto-merged if improved)
gh pr merge <PR_NUMBER>

# 6. Download the new Production model
python WMS/scripts/sync_model_aws.py --force

# 7. Verify model was downloaded
ls -lh WMS/models/production.pth

# 8. Run predictions with new model
python WMS/src/predicts.py

# 9. View results
ls WMS/data/predictions/predicted_masks/
```

---

## 🔍 Check MLflow Experiment Tracking

View all training runs, metrics, and models:

### Access MLflow UI

```bash
# Find your EC2 public IP
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=wms-k3s" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text

# Open in browser (if EC2 is running)
# http://<EC2_IP>:5000
```

**Note:** EC2 only runs during training (ephemeral). Start it manually if you want to browse MLflow:

```bash
# Start EC2
aws ec2 start-instances --instance-ids $(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=wms-k3s" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text)

# Wait ~2 minutes for startup
# Then access MLflow UI

# Don't forget to stop it after!
aws ec2 stop-instances --instance-ids <instance-id>
```

---

## 🛠️ Manual Training Trigger

Sometimes you want to re-run training without changing data:

### Via GitHub UI

1. Go to: https://github.com/YOUR_USERNAME/Water-Meters-Segmentation-Automatization/actions/workflows/train.yml
2. Click "Run workflow"
3. Select branch: Choose data branch (e.g., `data/20260207-220516`)
4. Click green "Run workflow" button

### Via GitHub CLI

```bash
gh workflow run train.yml --ref data/20260207-220516
```

---

## 📊 Check Data Quality Locally

Before pushing data, validate it locally to catch errors early:

```bash
# Run data QA script
python devops/scripts/data-qa.py WMS/data/training/ --output report.json

# View report
cat report.json

# If errors found:
# Fix them before pushing!
```

**Common errors:**

- `Non-binary mask values` → Mask has values other than 0 and 255
- `Resolution mismatch` → Image and mask have different dimensions
- `Missing mask` → Image has no corresponding mask file

---

## 🔄 Update Infrastructure

If you modified Terraform configurations:

```bash
cd devops/terraform

# Plan changes (dry-run)
terraform plan

# Apply changes
terraform apply

# Confirm with: yes
```

**Common changes:**

- Change EC2 instance type in `terraform.tfvars`
- Update security group rules
- Adjust storage size

---

## 🗑️ Clean Up AWS Resources

**Important:** Run this when you're done testing to avoid costs!

```bash
# This will DESTROY all AWS resources
cd devops
bash scripts/cleanup-aws.sh

# Confirm with: yes
```

**What it does:**

1. Stops EC2 instance
2. Empties S3 buckets (DVC data, MLflow artifacts)
3. Runs `terraform destroy`
4. Deletes all AWS resources

**Warning:** This is irreversible! Back up any important data first.

---

## 🔐 Update AWS Credentials (AWS Academy)

AWS Academy credentials expire every ~4 hours. Update them:

### Step 1: Get New Credentials

1. Go to AWS Academy Learner Lab
2. Click "AWS Details"
3. Click "Show" next to "AWS CLI:"
4. Copy the credentials

### Step 2: Update Local Credentials

```bash
# Edit credentials file
nano ~/.aws/credentials

# Replace with new values:
[default]
aws_access_key_id=ASIAQZ5VG6SP...
aws_secret_access_key=Ghg6k4bgecCRoIQ...
aws_session_token=IQoJb3JpZ2luX2VjEJz...

# Save and exit (Ctrl+O, Enter, Ctrl+X)
```

### Step 3: Update GitHub Secrets

1. Go to: https://github.com/YOUR_USERNAME/Water-Meters-Segmentation-Automatization/settings/secrets/actions
2. Update:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_SESSION_TOKEN`

**Do this EVERY TIME you start a new AWS Academy session!**

---

## 🐛 Troubleshooting

### Data Validation Failed

**Error:** "Non-binary mask values"

**Solution:**

```bash
# Check mask values
python -c "
import cv2
import numpy as np
mask = cv2.imread('WMS/data/training/masks/your_mask.png', cv2.IMREAD_GRAYSCALE)
print(np.unique(mask))
"

# If not [0, 255], fix the mask:
python -c "
import cv2
mask = cv2.imread('WMS/data/training/masks/your_mask.png', cv2.IMREAD_GRAYSCALE)
_, binary_mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
cv2.imwrite('WMS/data/training/masks/your_mask.png', binary_mask)
"
```

---

### Training Failed: "No runs found"

**Problem:** MLflow connection issue

**Solution:**

1. Check if EC2 is running:
   ```bash
   aws ec2 describe-instances --filters "Name=tag:Name,Values=wms-k3s"
   ```
2. Check MLflow health:
   ```bash
   curl http://<EC2_IP>:5000/health
   ```
3. Check security group allows port 5000 from 0.0.0.0/0

---

### PR Not Auto-Approved

**Problem:** Training succeeded but PR not approved

**Reason:** This is intentional! Workflow only auto-approves, doesn't auto-merge.

**Solution:** Manually merge the PR (you have final control).

---

### EC2 Costs Too High

**Problem:** Forgot to implement ephemeral infrastructure or EC2 left running

**Solution:**

```bash
# Check if EC2 is running
aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=wms-k3s" \
  --query 'Reservations[0].Instances[0].State.Name'

# If "running", stop it:
aws ec2 stop-instances --instance-ids <instance-id>
```

---

## ❓ FAQ: Model Management

### Q: Where is the model stored?

**A:** Models are stored in **MLflow**, NOT in Git.

- **Source of truth:** MLflow Production stage (on EC2)
- **Local cache:** `WMS/models/production.pth` (gitignored)
- **NOT in Git:** Models are binary files (7+ MB), excluded from version control

### Q: Do I need to download the model after every `git pull`?

**A:** NO! Model is cached locally and gitignored.

- ❌ NOT needed after `git pull` (code changes don't affect model)
- ❌ NOT needed after `git push` (model not in Git)
- ✅ ONLY needed after first `git clone`
- ✅ ONLY needed when you want the latest trained model

### Q: How do I know if my local model is outdated?

**A:** Check MLflow UI or run sync script with `--force`:

```bash
# Option 1: Check MLflow UI
# Open http://<EC2_IP>:5000 → Models → water-meter-segmentation
# Compare Production version timestamp with your local file timestamp

# Option 2: Just re-download (safe, overwrites local cache)
python WMS/scripts/sync_model.py --force
```

### Q: What happens if I try to run predictions without a model?

**A:** You'll get a helpful error message:

```
❌ No model found!

Download the Production model from MLflow:
  python WMS/src/download_model.py --mlflow-uri http://<EC2_IP>:5000

Or train a new model:
  python WMS/src/train.py
```

Just run `sync_model.py` to fix it!

### Q: Can I commit my downloaded model to Git?

**A:** NO, and it's blocked by `.gitignore`.

- `.gitignore` excludes `WMS/models/*.pth`
- Git will refuse to track model files
- This is intentional - models belong in MLflow, not Git

### Q: Why not store models in Git like normal files?

**A:** Because of MLOps best practices:

| Problem with Git          | Solution with MLflow           |
| ------------------------- | ------------------------------ |
| Large files (7+ MB)       | Only metadata stored           |
| Slow clone/pull           | Fast Git operations            |
| Binary merge conflicts    | No conflicts, versions tracked |
| Git bloat (history grows) | Clean Git history              |
| No model metadata         | Metrics, params, lineage       |

This is **industry standard** for ML projects. See: [MLflow Model Registry](https://mlflow.org/docs/latest/model-registry.html)

### Q: Does `sync_model.py` cost money?

**A:** Yes, but very little (~$0.003 per run):

- EC2 t3.large: ~$0.04/hour
- Sync takes ~5 minutes (including startup)
- Cost per sync: ~$0.003
- Script automatically stops EC2 after download

**Cost optimization:**

- Use `--keep-running` if doing multiple operations
- Model is cached locally (work offline after download)
- Only re-download when new model is trained

### Q: What if EC2 is already running?

**A:** `sync_model.py` detects this and skips the start step:

```bash
# If EC2 is already running (from previous operation):
python WMS/scripts/sync_model.py --mlflow-url http://<EC2_IP>:5000

# This skips EC2 start/stop, just downloads model
```

### Q: Can I automate model download after `git clone`?

**A:** Technically yes (post-checkout Git hook), but **not recommended**:

- ❌ Hook triggers on EVERY branch switch (unnecessary)
- ❌ May start EC2 unexpectedly (costs)
- ❌ User may not have GitHub CLI installed
- ✅ Better: Explicit manual step (clear, predictable)

**Current approach:**

1. Clone repo → Try to run predictions → Get error
2. Error message tells you exactly what to do
3. One command fixes it: `sync_model.py`

This is better UX than silent automatic downloads that may fail.

---

## 📚 Next Steps

- **Read WORKFLOWS.md** to understand all pipelines
- **Read ARCHITECTURE.md** for system design
- **Read SETUP.md** for infrastructure setup
- **Check devops/PLAN.md** for implementation phases

---

## 💡 Pro Tips

1. **Always run data-qa locally before pushing** - saves time
2. **Use magic branch `data/staging`** - automatic PR creation
3. **Don't merge PRs without training results** - wait for the comment
4. **Stop EC2 after browsing MLflow** - save costs
5. **Update AWS credentials at start of each session** - AWS Academy expires every 4h
6. **Use `cleanup-aws.sh` when done** - protect your budget

---

## 🆘 Need Help?

- **GitHub Issues:** https://github.com/YOUR_USERNAME/Water-Meters-Segmentation-Automatization/issues
- **Workflow logs:** Check Actions tab for detailed error messages
- **MLflow UI:** Browse experiments and models
- **This documentation:** Everything you need is here!
