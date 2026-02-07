# Usage Guide - How to Use This System

Step-by-step guide for everyday operations.

---

## 🎯 Quick Start: Upload New Training Data

This is the **most common workflow** you'll use.

### Step 1: Prepare Your Data Locally

```bash
# Navigate to your project
cd Water-Meters-Segmentation-Autimatization

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

### Step 2: Push Data (Magic Branch Method)

```bash
# Create a commit with your new data
git add WMS/data/training/
git commit -m "data: add 5 new water meter images"

# Push to magic branch - system auto-creates timestamped branch
git push origin HEAD:data/staging
```

**What happens automatically:**
1. `data-staging` workflow creates branch `data/YYYYMMDD-HHMMSS`
2. Your data is pushed to that branch
3. `data-upload` workflow runs validation
4. If validation passes: **Pull Request is created automatically**
5. If validation fails: **Commit comment shows errors**

---

### Step 2 Alternative: Manual Branch Method

```bash
# Create timestamped branch manually
git checkout -b data/$(date +%Y%m%d-%H%M%S)

# Add and commit data
git add WMS/data/training/
git commit -m "data: add 5 new water meter images"

# Push branch
git push origin HEAD

# Create PR manually on GitHub
# Or let data-upload workflow create it
```

---

### Step 3: Wait for Training (~10 minutes)

The training workflow runs automatically on your PR:

```
EC2 starts → Train (3 attempts) → Aggregate results → EC2 stops
```

**Monitor progress:**
- Go to: https://github.com/YOUR_USERNAME/Water-Meters-Segmentation-Autimatization/pull/1
- Check "Checks" tab
- Wait for "Train Model" workflow to complete

**Training runs in parallel:**
- Attempt 1: Seed = (run_number × 100) + 1
- Attempt 2: Seed = (run_number × 100) + 2
- Attempt 3: Seed = (run_number × 100) + 3

---

### Step 4: Review Training Results

The workflow posts a comment on your PR with:

#### ✅ Success Example:
```
## ✅ Training Results (3 attempts)

📈 MODEL IMPROVED

### All Attempts
| Attempt | Dice   | IoU    | Passed | Improved |
|---------|--------|--------|--------|----------|
| 1       | 0.9310 | 0.8890 | ✅     | 📈       |
| 2 🏆    | 0.9350 | 0.8920 | ✅     | 📈       |
| 3       | 0.9280 | 0.8870 | ✅     | -        |

### Best Result (Attempt 2)
| Metric | Value  | Baseline | Threshold | Status |
|--------|--------|----------|-----------|--------|
| Dice   | 0.9350 | 0.9275   | 0.9075    | ✅     |
| IoU    | 0.8920 | 0.8865   | 0.8665    | ✅     |

🚀 Best model has been promoted to Production
```

**If model improved:** PR is auto-approved, ready to merge.

#### ❌ Failure Example:
```
## ❌ Training Results (3 attempts)

📊 No improvement

### All Attempts
| Attempt | Dice   | IoU    | Passed | Improved |
|---------|--------|--------|--------|----------|
| 1       | 0.9050 | 0.8650 | ✅     | -        |
| 2       | 0.9070 | 0.8670 | ✅     | -        |
| 3       | 0.9060 | 0.8660 | ✅     | -        |

⚠️ No improvement - model will not be deployed

Options:
1. Review training logs for issues
2. Check if new training data is sufficient
3. Consider adjusting hyperparameters
4. Close this PR and try again with more/better data
```

**If no improvement:** PR is NOT approved, don't merge.

---

### Step 5: Merge or Close PR

**If training improved:**
```bash
# Merge the PR on GitHub UI
# Or via command line:
gh pr merge <PR_NUMBER> --squash
```

**If training failed:**
```bash
# Close PR and improve your data
gh pr close <PR_NUMBER>

# Go back to Step 1 with better data
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

1. Go to: https://github.com/YOUR_USERNAME/Water-Meters-Segmentation-Autimatization/actions/workflows/train.yml
2. Click "Run workflow"
3. Select branch: Choose PR branch (e.g., `data/20260207-220516`)
4. Number of attempts: Default is 3
5. Click green "Run workflow" button

### Via GitHub CLI

```bash
gh workflow run train.yml \
  --ref data/20260207-220516 \
  --field attempts=3
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
- Change EC2 instance type (t3.large → t3.medium)
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

1. Go to: https://github.com/YOUR_USERNAME/Water-Meters-Segmentation-Autimatization/settings/secrets/actions
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

- **GitHub Issues:** https://github.com/YOUR_USERNAME/Water-Meters-Segmentation-Autimatization/issues
- **Workflow logs:** Check Actions tab for detailed error messages
- **MLflow UI:** Browse experiments and models
- **This documentation:** Everything you need is here!
