# 🚀 Quick Start Guide

**Just cloned this repository? Start here!**

## Step 1: Download the Production Model (Required!)

**⚠️ IMPORTANT:** Models are NOT stored in Git. You must download the Production model from MLflow before running predictions.

### Automatic Method (Recommended)

**Option 1: Using AWS CLI (Simpler - No GitHub CLI needed!)**

```bash
# One command - uses AWS CLI directly!
python WMS/scripts/sync_model_aws.py

# Windows users: just double-click sync_model_aws.bat
```

**Prerequisites:**
- AWS CLI installed (already have it!)
- AWS credentials configured (`~/.aws/credentials` or environment variables)

**Option 2: Using GitHub CLI (If you have it configured)**

```bash
# Uses GitHub Actions workflows
python WMS/scripts/sync_model.py

# Windows users: double-click sync_model.bat
```

**Prerequisites:**
- GitHub CLI installed and authenticated: `gh auth login`
- See [WMS/scripts/README.md](WMS/scripts/README.md) for installation

Both scripts will:
1. ✅ Start EC2 instance
2. ✅ Wait for MLflow to be ready
3. ✅ Download Production model to `WMS/models/production.pth`
4. ✅ Ask if you want to stop EC2

### Manual Method (Alternative)

```bash
# 1. Start EC2
gh workflow run ec2-manual-control.yaml -f action=start

# 2. Wait 3-5 minutes, get IP from workflow output
gh run list --workflow=ec2-manual-control.yaml --limit=1
gh run view <RUN_ID>

# 3. Download model
python WMS/src/download_model.py --mlflow-uri http://<EC2_IP>:5000

# 4. Stop EC2
gh workflow run ec2-manual-control.yaml -f action=stop
```

---

## Step 2: Run Predictions

```bash
# Now you can run predictions!
python WMS/src/predicts.py

# The script will:
# - Load model from WMS/models/production.pth
# - Process images in WMS/data/predictions/photos_to_predict/
# - Save masks to WMS/data/predictions/predicted_masks/
```

---

## Step 3: Explore the System

### Upload New Training Data

```bash
# 1. Install pre-push hook (one-time setup)
./devops/scripts/install-git-hooks.sh

# 2. Add your images and masks
cp /path/to/new/*.jpg WMS/data/training/images/
cp /path/to/new/*.png WMS/data/training/masks/

# 3. Commit and push (hook auto-creates branch!)
git add WMS/data/training/
git commit -m "data: add new training samples"
git push origin main  # Pre-push hook redirects to data/TIMESTAMP

# 4. Wait ~10-15 minutes for automated pipeline:
#    - GitHub Actions merges with S3 data (no local AWS needed!)
#    - Validates merged dataset
#    - Creates Pull Request
#    - Trains model on full dataset
#    - Auto-merges if model improved!

# ℹ️  No AWS credentials required locally - all merging happens in CI!
```

### Browse MLflow Experiments

```bash
# Start EC2 (if not running)
gh workflow run ec2-manual-control.yaml -f action=start

# Get IP from workflow output, then open in browser:
# http://<EC2_IP>:5000

# View:
# - All training runs with metrics
# - Model versions in registry
# - Production model details
```

---

## 🛠️ Additional Commands

### Check Model Performance

```bash
# View Production model metrics
python WMS/scripts/show_metrics.py

# Output:
# - Dice score, IoU, Loss
# - Training parameters
# - Quality assessment (Excellent/Good/Poor)
```

### Manage Model Versions

```bash
# See all model versions and promote
python WMS/scripts/check_model.py

# Lists all 14 versions
# Shows which is Production
# Offers to promote if needed
```

### View All Versions with Metrics

```bash
# Compare all trained models
python WMS/scripts/show_metrics.py --all

# Shows:
# Version 14: 🏆 PRODUCTION - Dice: 0.32
# Version 13: None - Dice: 0.13
# Version 12: None - Dice: 0.53
# ...
```

---

## 📖 Full Documentation

- **[README.md](README.md)** - Project overview and features
- **[docs/USAGE.md](docs/USAGE.md)** - Complete usage guide (start here!)
- **[docs/WORKFLOWS.md](docs/WORKFLOWS.md)** - All pipelines explained
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** - System design
- **[WMS/scripts/README.md](WMS/scripts/README.md)** - Helper scripts documentation

---

## ❓ FAQ

### Why is there no model in the repository?

**A:** MLOps best practice - models are stored in MLflow, not Git:
- ✅ Keeps repository lightweight (fast clone/pull)
- ✅ No large binary files in Git history
- ✅ MLflow tracks model versions with metrics
- ✅ Industry standard approach

### Do I need to download the model after every `git pull`?

**A:** NO! Model is cached locally (gitignored).

- ❌ NOT needed after `git pull` or `git push`
- ✅ ONLY needed after first `git clone`
- ✅ ONLY needed to get latest trained model

### What if I get "❌ No model found!" error?

**A:** You haven't downloaded the Production model yet. Run:

```bash
python WMS/scripts/sync_model.py
```

### How much does `sync_model.py` cost?

**A:** ~$0.002 per run (EC2 runs for ~5 minutes, then auto-stops)

---

## 🆘 Need Help?

- **GitHub Issues:** Report bugs or ask questions
- **Workflow Logs:** Check Actions tab for detailed error messages
- **MLflow UI:** Browse experiments and models
- **Documentation:** See [docs/](docs/) folder

---

**Ready to start?** Run `python WMS/scripts/sync_model.py` now! 🚀
