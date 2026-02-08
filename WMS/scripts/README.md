# Helper Scripts

Utility scripts for model management and MLOps operations.

## Quick Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `sync_model_aws.py` | Download Production model | `python WMS/scripts/sync_model_aws.py` |
| `show_metrics.py` | View model performance | `python WMS/scripts/show_metrics.py` |
| `check_model.py` | Manage model versions | `python WMS/scripts/check_model.py` |
| `sync_model.py` | Download (GitHub CLI) | `python WMS/scripts/sync_model.py` |

---

## sync_model_aws.py - Automatic Model Synchronization (AWS CLI)

**Purpose:** Automatically download the latest Production model from MLflow using AWS CLI directly.

**✅ Recommended:** Simpler than sync_model.py - uses AWS CLI directly (no GitHub CLI needed!)

### Quick Start

```bash
# Automatic mode (AWS CLI)
python WMS/scripts/sync_model_aws.py

# Windows: just double-click sync_model_aws.bat in project root
```

### Prerequisites

1. **AWS CLI** (you already have it!)
   ```bash
   aws --version
   ```

2. **AWS Credentials configured:**
   - Option A: `~/.aws/credentials` file
   - Option B: Environment variables (AWS_ACCESS_KEY_ID, etc.)

3. **Terraform infrastructure deployed** (EC2 instance with tag `wms-k3s`)

### Usage Options

```bash
# Basic usage
python WMS/scripts/sync_model_aws.py

# Force re-download
python WMS/scripts/sync_model_aws.py --force

# Keep EC2 running after download
python WMS/scripts/sync_model_aws.py --no-stop
```

---

## sync_model.py - Automatic Model Synchronization (GitHub CLI)

**Purpose:** Automatically download the latest Production model from MLflow using GitHub Actions workflows.

**Note:** Requires GitHub CLI installed and configured. Use `sync_model_aws.py` if you don't have GitHub CLI.

### Quick Start

```bash
# Automatic mode (recommended)
python WMS/scripts/sync_model.py

# Windows: just double-click sync_model.bat in project root
```

### What It Does

1. ✅ Checks GitHub CLI is installed and authenticated
2. 🚀 Starts EC2 instance via GitHub Actions workflow
3. ⏳ Waits for workflow to complete (~3-5 minutes)
4. 📡 Extracts MLflow URL from workflow output
5. 📥 Downloads Production model to `WMS/models/production.pth`
6. 🛑 Asks if you want to stop EC2 (saves costs)

### Usage Options

```bash
# Basic usage - full automation
python WMS/scripts/sync_model.py

# Keep EC2 running after download (for multiple operations)
python WMS/scripts/sync_model.py --keep-running

# Force re-download even if model is cached
python WMS/scripts/sync_model.py --force

# Use existing EC2 instance (skip start/stop)
python WMS/scripts/sync_model.py --mlflow-url http://<EC2_IP>:5000
```

### Prerequisites

1. **GitHub CLI (gh):**
   ```bash
   # Windows
   winget install --id GitHub.cli

   # macOS
   brew install gh

   # Linux
   # See: https://github.com/cli/cli#installation
   ```

2. **Authentication:**
   ```bash
   gh auth login
   ```

3. **Repository Access:**
   - Must be run from project root or have access to `.github/workflows/`

### Troubleshooting

#### "GitHub CLI not found"
- Install GitHub CLI (see Prerequisites above)
- Make sure `gh` is in your PATH

#### "GitHub CLI not authenticated"
```bash
gh auth login
```

#### "Workflow did not complete in time"
- Check workflow manually: `gh run list --workflow=ec2-manual-control.yaml`
- View specific run: `gh run view <RUN_ID>`
- EC2 might be taking longer to start (first boot takes ~5 minutes)

#### "Could not extract MLflow URL"
- Workflow completed but URL not in output
- Manually check: `gh run view <RUN_ID>`
- Look for "Public IP" and use: `python WMS/src/download_model.py --mlflow-uri http://<IP>:5000`

#### AWS Session Expired (AWS Academy Lab)
- AWS Academy sessions expire after ~4 hours
- Credentials in GitHub Secrets need to be updated
- Go to AWS Academy → Start Lab → AWS Details → Update GitHub Secrets

### Manual Alternative

If the automatic script doesn't work, use manual method:

```bash
# 1. Start EC2
gh workflow run ec2-manual-control.yaml -f action=start

# 2. Wait 3-5 minutes, check status
gh run list --workflow=ec2-manual-control.yaml --limit=1

# 3. Get workflow output
gh run view <RUN_ID>  # Look for Public IP

# 4. Download model
python WMS/src/download_model.py --mlflow-uri http://<EC2_IP>:5000

# 5. Stop EC2
gh workflow run ec2-manual-control.yaml -f action=stop
```

### Cost Optimization

- Script automatically offers to stop EC2 after download
- EC2 costs ~$0.02/hour when running (t3.large)
- Model download takes ~30 seconds once EC2 is ready
- Total cost per sync: ~$0.002 (less than 1 cent)

### For Developers

The script uses:
- `gh workflow run` - Trigger GitHub Actions workflows
- `gh run list` - List workflow runs
- `gh run view` - Get workflow run details and logs
- `subprocess` - Execute shell commands
- `json` - Parse GitHub CLI JSON output

See source code for implementation details.

---

## show_metrics.py - View Model Performance

**Purpose:** Quickly check Production model metrics and quality assessment.

### Quick Start

```bash
# Show Production model metrics
python WMS/scripts/show_metrics.py

# Show all model versions
python WMS/scripts/show_metrics.py --all
```

### What It Does

1. ✅ Connects to MLflow at http://100.49.195.150:5000
2. ✅ Fetches Production model (or all versions)
3. ✅ Displays key metrics: Dice, IoU, Loss
4. ✅ Shows training parameters: LR, batch size, epochs
5. ✅ Provides quality assessment

### Example Output

#### Production Model View

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
    train_dice: 0.4927
    train_iou: 0.3637
    train_loss: 0.4796
    val_dice: 0.3240
    val_iou: 0.1945
    val_loss: 0.6178

Key Parameters:
    learning_rate: 0.0001
    batch_size: 4
    epochs: 100

============================================================
❌ POOR MODEL (Dice < 50%) - Retraining recommended!
============================================================
```

#### All Versions View

```
============================================================
ALL MODEL VERSIONS (14 total)
============================================================

Version 14: 🏆 PRODUCTION
  Dice: 0.3240 | IoU: 0.1945
  Created: 2026-02-08 02:36:55

Version 13: None
  Dice: 0.1331 | IoU: 0.0716
  Created: 2026-02-08 02:28:06

Version 12: None
  Dice: 0.5291 | IoU: 0.3597
  Created: 2026-02-08 02:11:57

...
```

### Quality Thresholds

| Rating | Dice Score | Recommendation |
|--------|-----------|----------------|
| ✅ Excellent | ≥ 85% | Production ready |
| ⚠️ Good | 70-85% | Acceptable, monitor |
| ⚠️ Mediocre | 50-70% | Consider retraining |
| ❌ Poor | < 50% | Retraining required |

### Prerequisites

- EC2 instance running with MLflow accessible
- Use `sync_model_aws.py --no-stop` to keep EC2 running

### Troubleshooting

#### "Failed to connect to MLflow"
```bash
# Start EC2 first
python WMS/scripts/sync_model_aws.py --no-stop

# Then try again
python WMS/scripts/show_metrics.py
```

#### "No Production model found"
```bash
# Check and promote a model
python WMS/scripts/check_model.py
```

---

## check_model.py - Manage Model Versions

**Purpose:** View all model versions and promote models to Production stage.

### Quick Start

```bash
python WMS/scripts/check_model.py
```

### What It Does

1. ✅ Lists all registered model versions
2. ✅ Shows current stage for each (Production/Staging/None)
3. ✅ Identifies which version is Production
4. ✅ Offers to promote latest version if no Production exists
5. ✅ Interactive confirmation before promotion

### Example Output

#### With Production Model

```
Connecting to MLflow: http://100.49.195.150:5000

Searching for model: water-meter-segmentation

Found 14 version(s):

  Version 14:
    Stage: Production <<< PRODUCTION
    Run ID: d8f1681809f4467e8235b56a6f4d86dd

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

#### Without Production Model

```
[WARNING] No versions in Production stage!

To promote the latest version to Production:

Latest version: 14 (stage: None)

Promote this version to Production? (y/n): y

Promoting version 14 to Production...
[OK] Version 14 is now in Production!

Now you can download the model:
  python WMS/scripts/sync_model_aws.py
```

### When to Use

- **After training:** Verify new model was registered
- **Check Production:** See which version is currently active
- **Manual promotion:** Override automatic promotion
- **Debugging:** Investigate model registry state

### Prerequisites

- EC2 running with MLflow accessible
- At least one model version registered

### Model Stage Lifecycle

```
Training → Registered (stage: None)
              ↓
         Promote to Production
              ↓
         Production (active model)
              ↓
         Archive when new Production promoted
```

### Troubleshooting

#### "No versions found"
- No models have been trained and registered
- Train a model first: add data → push → wait for PR training

#### EC2 not accessible
```bash
python WMS/scripts/sync_model_aws.py --no-stop
```

---

## Usage Examples

### Complete Workflow: Train → Check → Download → Predict

```bash
# 1. After training completes, check new model metrics
python WMS/scripts/show_metrics.py --all

# 2. Verify Production model
python WMS/scripts/check_model.py

# 3. Download Production model
python WMS/scripts/sync_model_aws.py

# 4. Run predictions
python WMS/src/predicts.py

# 5. Stop EC2 to save costs
# (Already done by sync_model_aws.py)
```

### Compare Models Before Promotion

```bash
# 1. See all versions with metrics
python WMS/scripts/show_metrics.py --all

# 2. Check which is Production
python WMS/scripts/check_model.py

# 3. If better version exists, promote manually
#    (script offers interactive promotion)
```

### Daily Monitoring

```bash
# Check model performance daily
python WMS/scripts/sync_model_aws.py --no-stop
python WMS/scripts/show_metrics.py

# If performance degrades, retrain with more data
```

---

## Summary

| Need | Script | Command |
|------|--------|---------|
| Download model | `sync_model_aws.py` | `python WMS/scripts/sync_model_aws.py` |
| Check metrics | `show_metrics.py` | `python WMS/scripts/show_metrics.py` |
| Manage versions | `check_model.py` | `python WMS/scripts/check_model.py` |
| Run predictions | `predicts.py` | `python WMS/src/predicts.py` |

**Remember:** All scripts require EC2 running (except predictions after download).
