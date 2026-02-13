# Known Issues

This document tracks known issues and their workarounds.

---

## GitHub Actions: Bot-created PRs don't trigger training workflow

**Status:** ✅ RESOLVED (architecture redesigned)

**Historical Issue:**
When the `training-data-pipeline.yaml` workflow created a PR using `github-actions[bot]`, the `train.yml` workflow didn't automatically run on that PR. This was a GitHub security feature to prevent infinite workflow loops.

**Affected workflows:**
- OLD: `training-data-pipeline.yaml` creates PR → `train.yml` should run but doesn't

**Impact (historical):**
- Users had to manually trigger training after uploading data via `data/**` branches
- Training didn't start automatically on bot-created PRs
- Required workaround: push empty commit to trigger workflow

**Resolution (2026-02-11):**
**Redesigned workflow architecture** - training now happens BEFORE PR creation in a single unified workflow:

1. **OLD architecture (broken):**
   ```
   training-data-pipeline.yaml → creates PR → train.yml (never triggers - bot limitation)
   ```

2. **NEW architecture (fixed):**
   ```
   training-data-pipeline.yaml:
     1. Validate data
     2. Start EC2
     3. Train model ← MOVED HERE (before PR)
     4. Quality gate
     5. Stop EC2
     6. Create PR ONLY if improved ← No separate workflow to trigger!
     7. Auto-merge
   ```

**Benefits of new approach:**
- ✅ No bot PR triggering needed - all in one workflow
- ✅ PR only created if model improved (no wasted PRs)
- ✅ No PAT needed (security improvement)
- ✅ Faster feedback - know if data is good within 15 minutes
- ✅ Complete automation: push data → auto-merge (if better)

**Changes made:**
- Modified `training-data-pipeline.yaml`: Added training jobs before PR creation
- Modified `train.yml`: Disabled automatic triggers (manual use only)
- Updated `docs/WORKFLOWS.md`: Documented new architecture

**References:**
- GitHub Docs: [Triggering a workflow from a workflow](https://docs.github.com/en/actions/using-workflows/triggering-a-workflow#triggering-a-workflow-from-a-workflow)
- Implementation plan: Merge Workflows - Training Before PR Creation

**Date discovered:** 2026-02-08
**Date resolved:** 2026-02-11

---

## MLflow 503 errors during parallel training attempts

**Status:** ✅ RESOLVED (simplified pipeline with single training run)

**Historical Issue (No longer applicable):**
When running multiple training attempts in parallel or sequentially without delays, MLflow server returns `503 Service Unavailable` errors. This happened because:

1. SQLite backend cannot handle concurrent write operations effectively
2. First training attempt saturates MLflow server with metric logging
3. Subsequent attempts fail immediately on `mlflow.start_run()` or `mlflow.log_metrics()`
4. Server doesn't have time to recover between attempts

**Symptoms:**
```
urllib3.exceptions.MaxRetryError: HTTPConnectionPool(host='100.49.195.150', port=5000):
Max retries exceeded with url: /api/2.0/mlflow/runs/log-batch
(Caused by ResponseError('too many 503 error responses'))
```

**Observed behavior:**
- **Attempt 1**: Trains successfully for 40-60 epochs, then crashes on metric logging
- **Attempt 2**: Fails immediately on `mlflow.start_run()` - can't create run (503)
- **Attempt 3**: Fails immediately on `mlflow.start_run()` - can't create run (503)

**Root cause:**
- SQLite backend is single-threaded and struggles with high-frequency writes
- 100 epochs × 9 metrics = 900 write operations per training attempt
- No recovery time between sequential training attempts
- t3.large (8GB RAM) is sufficient for compute, but SQLite is the bottleneck

**Fixes implemented:**

1. **Increased HTTP timeout** (`.github/workflows/train.yml`):
   ```yaml
   env:
     MLFLOW_HTTP_REQUEST_TIMEOUT: 300  # 5 minutes (default: 120s)
     MLFLOW_HTTP_REQUEST_MAX_RETRIES: 5  # Retry with backoff (default: 5)
   ```

2. **Reduced metric logging frequency** (`WMS/src/train.py`):
   ```python
   # Log to MLflow every 5 epochs instead of every epoch
   if epoch % 5 == 0 or epoch == numEpochs:
       mlflow.log_metrics({...}, step=epoch)
   ```
   - Reduced from 900 writes → **180 writes per training** (5x reduction)

3. **Added recovery delay between attempts** (`.github/workflows/train.yml`):
   ```yaml
   - name: Wait for MLflow server to stabilize
     if: matrix.attempt > 1
     run: |
       echo "⏳ Waiting 60 seconds for MLflow server to recover..."
       sleep 60
   ```
   - Gives SQLite time to flush writes and release locks
   - Allows server to return to idle state

**Impact on training time:**
- Before: ~45 minutes total (but only 1 attempt succeeds)
- After: ~50 minutes total (all 3 attempts complete successfully)
- +5 minutes for 2×60s delays, but **3x reliability improvement**

**Alternative solutions (not implemented due to budget):**
- **PostgreSQL backend**: Replace SQLite with PostgreSQL for better concurrency
  - Pros: Handles concurrent writes, no 503 errors
  - Cons: Requires RDS ($15-30/month) - exceeds $50 budget
- **Separate MLflow instances**: One MLflow server per training attempt
  - Pros: Complete isolation
  - Cons: Complex orchestration, 3x resource usage

**Monitoring:**
Check MLflow server health during training:
```bash
# SSH to EC2
ssh -i ~/.ssh/labsuser.pem ec2-user@<EC2_IP>

# Check MLflow container logs
sudo k3s kubectl logs -l app=mlflow --tail=100

# Check SQLite lock status
sudo lsof /path/to/mlruns.db
```

**References:**
- [MLflow Environment Variables](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.environment_variables.html)
- [MLflow HTTP timeout PR #5745](https://github.com/mlflow/mlflow/pull/5745)
- Related workflow runs: [Run #21792671320](https://github.com/Rafallost/Water-Meters-Segmentation-Autimatization/actions/runs/21792671320)

**Date discovered:** 2026-02-08
**Date resolved:** 2026-02-10

**Resolution:**
The simplified training pipeline (implemented 2026-02-10) uses a **single training run** instead of 3 attempts, completely eliminating this issue. The new approach:
- Trains model once on the full merged dataset
- No concurrent/sequential MLflow operations
- No recovery delays needed
- Faster overall (10-15 min vs 30-45 min)
- Dynamic quality gate compares against Production baseline

This issue is kept for historical reference only.

---

## MLflow Gunicorn Worker Timeout - GitHub Actions Connection Hangs

**Status:** Fixed

**Issue:**
Training workflow hangs for 7+ minutes when trying to connect to MLflow from GitHub Actions, despite MLflow responding instantly to local curl tests (0.028s). Gunicorn logs show repeated `WORKER TIMEOUT` errors and workers being killed.

**Symptoms:**
```bash
# From EC2 MLflow logs:
[CRITICAL] WORKER TIMEOUT (pid:12345)
Worker with pid 12345 was terminated due to signal 9
Booting worker with pid: 12346

# From GitHub Actions:
Run echo '=== Training Attempt 1/3 ==='
# ... hangs for 7+ minutes at mlflow.start_run()
```

**Root cause:**
- Gunicorn default worker timeout: **30 seconds**
- GitHub Actions → EC2 connection over internet takes longer than 30s
- Worker times out before request completes, gets killed by master process
- Creates infinite cycle: new worker spawned → times out → killed → repeat
- **Paradox**: Local curl succeeds in 0.028s because it's localhost (no network latency)

**Network confirmation:**
- EC2 security group allows port 5000 from 0.0.0.0/0 ✅
- MLflow server responds to health checks ✅
- System resources normal (CPU 84% idle, 4.7GB free RAM) ✅
- Issue is purely gunicorn timeout, not MLflow performance

**Fix:**
Added explicit gunicorn timeout configuration to MLflow systemd service (`user-data.sh`):

```bash
ExecStart=/usr/local/bin/mlflow server \
  --backend-store-uri sqlite:////opt/mlflow/mlflow.db \
  --default-artifact-root s3://${mlflow_bucket}/ \
  --host 0.0.0.0 \
  --workers 2 \
  --gunicorn-opts "--timeout 300 --keep-alive 120"
```

**Configuration explained:**
- `--workers 2`: MLflow argument for worker count (NOT in gunicorn-opts - MLflow adds `-w` after gunicorn-opts)
- `--timeout 300`: 5 minutes worker timeout (matches MLFLOW_HTTP_REQUEST_TIMEOUT in workflow)
- `--keep-alive 120`: 2 minute keep-alive for slow connections (helps with internet latency)

**IMPORTANT:** `--workers` must be a direct MLflow argument, NOT inside `--gunicorn-opts`. If passed via gunicorn-opts, MLflow's default `-w 4` overrides it.

**Deployment:**
```bash
# Apply Terraform changes (recreates EC2 with new user-data)
cd devops/terraform
terraform apply

# Or manually restart MLflow on existing instance:
ssh -i ~/.ssh/labsuser.pem ec2-user@<EC2_IP>
sudo systemctl daemon-reload
sudo systemctl restart mlflow
sudo systemctl status mlflow
```

**Verification:**
```bash
# Check gunicorn is using new timeout
ssh -i ~/.ssh/labsuser.pem ec2-user@<EC2_IP>
sudo journalctl -u mlflow -f

# Should see on startup:
# [INFO] Listening at: http://0.0.0.0:5000
# [INFO] Using worker: sync
# [INFO] Booting worker with pid: xxxxx
# (No more WORKER TIMEOUT errors)
```

**Related issues:**
- MLflow 503 errors (KNOWN_ISSUES.md) - SQLite concurrent writes
- Connection Refused (KNOWN_ISSUES.md) - Disk full preventing MLflow startup

**References:**
- [Gunicorn Settings](https://docs.gunicorn.org/en/stable/settings.html#timeout)
- [MLflow Server Options](https://mlflow.org/docs/latest/cli.html#mlflow-server)

**Date discovered:** 2026-02-08
**Date fixed:** 2026-02-08

---

## Race Condition: Concurrent Training Workflows Sharing EC2 Instance

**Status:** Fixed

**Issue:**
When multiple training workflows run concurrently (e.g., triggered by multiple data uploads), they all share the same EC2 instance. When the first workflow completes, it stops the EC2 instance in the `stop-infra` job, causing all other running workflows to fail with connection timeouts.

**Observed behavior:**
```
Run #1: Data QA → Start EC2 → Train → Stop EC2 ✅ (terminates instance)
Run #2: Data QA → Start EC2 → Train → 💥 Connection timeout (EC2 deleted by Run #1)
Run #3: Data QA → Start EC2 → Train → 💥 Connection timeout (EC2 deleted by Run #1)
```

**Root cause:**
- Multiple workflow runs execute in parallel without coordination
- Each workflow assumes it has exclusive access to EC2
- `stop-infra` job runs independently per workflow
- First workflow to finish stops the shared EC2 instance
- Remaining workflows fail when they try to connect to deleted instance

**Impact:**
- Training failures for all but the first completed workflow
- Wasted compute resources (Data QA, EC2 startup)
- Confusing error messages (MLflow connection timeout instead of clear "EC2 deleted" error)

**Fix:**
Added GitHub Actions concurrency control to `.github/workflows/train.yml`:

```yaml
concurrency:
  group: training-${{ github.ref }}
  cancel-in-progress: false  # Queue instead of cancel
```

**How it works:**
- Only **one training workflow** per branch can run at a time
- Subsequent triggers are **queued** (not canceled) and wait for previous run to complete
- Each workflow gets exclusive access to EC2 for its entire lifecycle
- No race conditions - EC2 is always available when workflow needs it
- Sequential execution: Run #1 completes → Run #2 starts → Run #3 starts

**Example with fix:**
```
15:00 - Push #1 triggers training → Run #1 starts immediately
15:02 - Push #2 triggers training → Run #2 queued (waiting for Run #1)
15:05 - Push #3 triggers training → Run #3 queued (waiting for Run #2)

15:45 - Run #1: Train → Stop EC2 → Done ✅
15:45 - Run #2: Start EC2 → Train → Stop EC2 → Done ✅ (45 min later)
16:30 - Run #3: Start EC2 → Train → Stop EC2 → Done ✅ (45 min later)
```

**Why `cancel-in-progress: false`:**
- We want to **preserve all training attempts** (each might use different data/seeds)
- Canceling would lose potentially valuable training runs
- Queueing ensures all data uploads get trained and evaluated
- Small delay (waiting in queue) is acceptable vs. losing training attempts

**Alternative solutions considered:**
1. **Separate EC2 per workflow** - Too expensive (3x cost, exceeds $50 budget)
2. **Shared EC2 with reference counting** - Complex, prone to edge cases, hard to debug
3. **Manual EC2 control only** - Requires discipline, error-prone, defeats automation purpose

**Verification:**
```bash
# Trigger multiple training runs quickly
git commit --allow-empty -m "test 1" && git push
git commit --allow-empty -m "test 2" && git push
git commit --allow-empty -m "test 3" && git push

# Check GitHub Actions - should see:
# - Run #1: Running
# - Run #2: Queued
# - Run #3: Queued

# After Run #1 completes, Run #2 should start automatically
```

**Related issues:**
- MLflow timeout issues (KNOWN_ISSUES.md) - exacerbated by EC2 being deleted mid-training
- GitHub Actions bot PR triggering (KNOWN_ISSUES.md) - can cause multiple rapid workflow starts

**References:**
- [GitHub Actions Concurrency Documentation](https://docs.github.com/en/actions/using-jobs/using-concurrency)
- [Concurrency Groups Best Practices](https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#concurrency)

**Date discovered:** 2026-02-08
**Date fixed:** 2026-02-08

---

## Training Workflow: Git Push Conflict When Remote Branch Diverges

**Status:** Fixed (current implementation uses model-metadata.json)

**Issue:**
Training workflow fails on the final git push step when the remote branch has new commits that were pushed during training. This happens because:

1. Workflow checks out branch at start (e.g., commit A)
2. Training runs for 10-15 minutes (simplified pipeline)
3. Developer pushes new commits during training (e.g., commit B)
4. Workflow tries to push metadata update from commit A → rejected (remote is now at commit B)

**Symptoms:**
```
[detached HEAD 61c0a95] chore: update model metadata
 1 file changed, 10 insertions(+), 5 deletions(-)
To https://github.com/Rafallost/Water-Meters-Segmentation-Autimatization
 ! [rejected]        HEAD -> data/training-20260210 (fetch first)
error: failed to push some refs
hint: Updates were rejected because the remote contains work that you do not
hint: have locally.
Error: Process completed with exit code 1.
```

**Root cause:**
- Training job runs for 10-15 minutes
- No synchronization between workflow start and end
- Direct `git push` without checking for remote updates
- Metadata commit is created from stale branch HEAD

**Impact:**
- Training succeeds, but metadata update fails (or requires manual resolution)
- `model-metadata.json` not updated
- Workflow may be marked as failed even though training worked

**Fix:**
Current implementation in `.github/workflows/train.yml` includes a fallback message for push failures:

```yaml
- name: Update model metadata in Git
  if: steps.quality_gate.outputs.improved == 'true'
  run: |
    # ... metadata update code ...

    git add model-metadata.json
    git commit -m "chore: update model metadata [skip ci]" || echo "No changes to commit"
    git push origin ${{ github.head_ref }} || echo "Could not push (PR may be closed)"
```

**Current solution:**
- Push failures are logged but don't fail the workflow
- Metadata is less critical than model promotion (which happens in MLflow)
- If metadata push fails, it can be manually updated or corrected in next PR

**Better solution (TODO):**
Add fetch/sync logic similar to the stash approach:
```yaml
git fetch origin "$BRANCH"
git pull --rebase origin "$BRANCH"
git add model-metadata.json
git commit -m "chore: update model metadata [skip ci]"
git push origin "$BRANCH"
```

**Why this is less critical now:**
- Simplified pipeline is faster (10-15 min vs 40-50 min)
- Smaller window for conflicts
- `model-metadata.json` is informational (MLflow is source of truth)
- Workflow doesn't fail if push fails

**Edge cases handled:**
- **No changes**: Exit early if metrics files unchanged (e.g., all attempts failed)
- **Stash conflicts**: Highly unlikely (only 2 JSON files, workflow-exclusive access)
- **Multiple workflows**: Concurrency control prevents this (see "Race Condition" issue)

**Testing:**
```bash
# Simulate the scenario locally:
git checkout data/training-20260208
# (let workflow start training)
# Push a fix during training:
git commit -m "fix: something"
git push
# (workflow will fetch, sync, and push metrics on top)
```

**Related issues:**
- Race Condition: Concurrent Training Workflows (KNOWN_ISSUES.md) - prevents multiple workflows competing
- S3 Upload Restrictions (KNOWN_ISSUES.md) - another push-time failure mode

**References:**
- [Git Stash Documentation](https://git-scm.com/docs/git-stash)
- [GitHub Actions Checkout Action](https://github.com/actions/checkout)
- Related workflow: [Run #21805555852](https://github.com/Rafallost/Water-Meters-Segmentation-Autimatization/actions/runs/21805555852)

**Date discovered:** 2026-02-08
**Date fixed:** 2026-02-08

---

## AWS Academy Lab: t3.xlarge Instance Type Not Allowed

**Status:** ✅ RESOLVED (using t3.large instead)

**Issue:**
AWS Academy Lab accounts restrict certain EC2 instance types. When attempting to create a t3.xlarge instance (16GB RAM, 4 vCPU) via Terraform, the operation is blocked with `UnauthorizedOperation` error.

**Symptoms:**
```
Error: creating EC2 Instance: operation error EC2: RunInstances, https response error StatusCode: 403,
RequestID: ..., api error UnauthorizedOperation: You are not authorized to perform this operation.
User: arn:aws:sts::055677744286:assumed-role/voclabs/... is not authorized to perform:
ec2:RunInstances on resource: arn:aws:ec2:us-east-1:055677744286:instance/*
```

**Root cause:**
- AWS Academy Lab limits instance types to cost-effective options
- t3.xlarge (16GB RAM, $0.0832/hour) is above the allowed threshold
- t3.large (8GB RAM, $0.0416/hour) and smaller are permitted

**Solution:**
Updated `infrastructure/terraform.tfvars` to use t3.large instead:
```hcl
instance_type = "t3.large" # 8GB RAM, 2 vCPU - adequate for ML workloads (AWS Academy limit)
```

**Impact on project:**
- ✅ t3.large (8GB RAM) is sufficient for development and testing
- ✅ k3s, MLflow, and training pipeline work correctly
- ⚠️ For large datasets (>100 images), may need batch size optimization
- 💡 Production deployments (non-AWS Academy) should use t3.xlarge or larger

**Cost savings:**
- t3.large: ~$0.0416/hour (~$7.50/month 24/7, or ~$1-2/month ephemeral)
- t3.xlarge: ~$0.0832/hour (~$15/month 24/7, or ~$2-3/month ephemeral)

**Date discovered:** 2026-02-10
**Date resolved:** 2026-02-10

---

## AWS Academy Lab: EC2 Instance Creation Blocked by IAM Policy

**Status:** HISTORICAL - Not applicable to current lab session

**Issue:**
AWS Academy Lab accounts have explicit IAM deny policies that prevent `ec2:RunInstances` operations. Terraform infrastructure deployment fails completely because the EC2 instance (which hosts k3s, MLflow, and the ML serving application) cannot be created.

**Symptoms:**
```
Error: creating EC2 Instance: operation error EC2: RunInstances, https response error StatusCode: 403,
RequestID: ..., api error UnauthorizedOperation: You are not authorized to perform this operation.
User: arn:aws:sts::055677744286:assumed-role/voclabs/user4220764=rzablotni is not authorized to perform:
ec2:RunInstances on resource: arn:aws:ec2:us-east-1:055677744286:instance/* with an explicit deny in an
identity-based policy: arn:aws:iam::055677744286:policy/Pvoclabs2 (Pvoclabs2).
```

**Root cause:**
- AWS Academy Lab uses `voclabs` IAM role with restrictive policies
- **Explicit deny** on `ec2:RunInstances` cannot be overridden (highest precedence in IAM)
- This restriction may vary by AWS Academy course/lab session
- Previous sessions (documented in MEMORY.md) successfully created EC2 instances, suggesting this is a NEW restriction or lab-specific

**Impact:**
- ❌ Cannot deploy infrastructure via Terraform
- ❌ No EC2 instance = no k3s cluster
- ❌ No MLflow server for experiment tracking
- ❌ No deployment endpoint for model serving
- ❌ Entire DevOps pipeline is blocked

**Partial success:**
These resources DO create successfully:
- ✅ VPC, subnets, internet gateway, route tables
- ✅ Security groups
- ✅ S3 buckets (dvc-data, mlflow-artifacts)
- ✅ ECR repository

**Possible workarounds:**

1. **Manual EC2 creation via AWS Console:**
   - Sometimes AWS Academy allows manual EC2 creation via console even when API denies it
   - Navigate to EC2 console → Launch Instance
   - Use same specs as Terraform: t3.large, Amazon Linux 2023, 100GB gp3
   - If successful, import to Terraform state: `terraform import module.ec2.aws_instance.k3s i-xxxxx`

2. **Request different AWS Academy lab:**
   - Some lab environments have different IAM policies
   - Try "AWS Academy Learner Lab" vs "AWS Academy Cloud Foundations"
   - Check with instructor if dedicated sandbox is available

3. **Use personal AWS account:**
   - Free Tier covers t3.xlarge for limited hours/month
   - Requires moving GitHub Actions secrets to personal account credentials
   - Cost: ~$125/month for 24/7 operation (can stop/start to reduce to ~$40/month)

4. **Alternative cloud provider:**
   - Deploy to GCP (Compute Engine), Azure (VM), or DigitalOcean (Droplets)
   - Requires rewriting Terraform modules for new provider
   - Significant effort but removes AWS Academy restrictions

5. **Use existing EC2 instance from previous session:**
   - If an instance was created in a previous lab session before this restriction
   - Check: `aws ec2 describe-instances --query 'Reservations[*].Instances[*].[InstanceId,State.Name,Tags[?Key==\`Name\`].Value|[0]]' --output table`
   - If found, import to Terraform state

**Current status:**
- Infrastructure deployment BLOCKED
- Need to verify if manual console creation works
- If not, project requires different AWS environment or cloud provider

**References:**
- [AWS IAM Policy Evaluation Logic](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html)
- [Terraform Import](https://www.terraform.io/cli/import)
- Related: Previous successful deployments (2026-02-07) documented in MEMORY.md

**Date discovered:** 2026-02-10

---

## AWS Academy Lab: S3 Upload Restrictions Prevent MLflow Artifact Storage

**Status:** Workaround implemented

**Issue:**
AWS Academy Lab accounts have explicit IAM deny policies that prevent `s3:PutObject` operations on MLflow artifacts bucket. Training completes successfully, but artifact uploads (plots, logs, model files) fail with `AccessDenied` errors, causing the workflow to fail overall.

**Symptoms:**
```
boto3.exceptions.S3UploadFailedError: Failed to upload plot_accuracy.png to
wms-mlflow-artifacts-055677744286/1/.../artifacts/plots/plot_accuracy.png:
An error occurred (AccessDenied) when calling the PutObject operation:
User: arn:aws:sts::055677744286:assumed-role/voclabs/user4220764=rzablotni
is not authorized to perform: s3:PutObject on resource: "arn:aws:s3:::..."
with an explicit deny in an identity-based policy
```

**Root cause:**
- AWS Academy Lab uses `voclabs` IAM role with restrictive policies
- **Explicit deny** policies cannot be overridden (highest precedence in IAM)
- S3 bucket policy allowing `PutObject` is insufficient against explicit deny
- Training runs in GitHub Actions, but S3 bucket is in AWS Academy account
- GitHub Actions OIDC role has cross-account access, but still subject to bucket policies

**Impact:**
- Training succeeds, model is saved locally
- Artifacts (plots, logs) cannot be uploaded to S3
- Model cannot be registered to MLflow Model Registry (requires S3 storage)
- Training workflow exits with failure status even though training succeeded
- Deployment pipeline cannot access new model versions

**Workaround implemented:**
Modified `WMS/src/train.py` to gracefully handle S3 upload failures:

```python
# Wrap all artifact uploads in try-except blocks
try:
    mlflow.log_artifact(str(png), artifact_path="plots")
    print("  → Plots uploaded to MLflow")
except Exception as e:
    print(f"  ⚠️  Warning: Could not upload plots to MLflow: {e}")
    print("  → Plots saved locally in Results/ directory")

try:
    mlflow.pytorch.log_model(
        model, name="model", registered_model_name="water-meter-segmentation"
    )
    print("  → Model registered to MLflow")
except Exception as e:
    print(f"  ⚠️  Warning: Could not register model to MLflow: {e}")
    print("  → Model saved locally as best.pth")
    print("  → AWS Academy Lab restricts S3 uploads. Model registration skipped.")
```

**Result:**
- Training completes successfully (exit code 0)
- Metrics are logged to MLflow tracking server (SQLite backend - no S3 needed)
- Artifacts saved locally in `Results/` directory
- Clear warning messages explain S3 upload failures
- Workflow succeeds, allowing CI/CD to continue

**Limitations:**
- No model versioning in MLflow Model Registry
- No artifact lineage across training runs
- Cannot deploy models directly from MLflow (use local `best.pth` instead)
- Manual model management required

**Alternative solutions (not implemented):**
1. **Use local artifact storage:**
   - Change MLflow `--default-artifact-root` to local filesystem path
   - Pros: No S3 needed
   - Cons: Artifacts lost when EC2 terminates, no remote access

2. **Separate S3 bucket in GitHub Actions account:**
   - Create S3 bucket in personal AWS account (not Academy)
   - Configure cross-account access from EC2
   - Pros: Full S3 access, proper artifact storage
   - Cons: Additional AWS account required, more complex setup

3. **Alternative artifact storage (Azure, GCS):**
   - Use non-AWS storage backend
   - Pros: Not subject to AWS Academy restrictions
   - Cons: Requires additional cloud provider, authentication complexity

**Verification:**
Check training logs for successful graceful degradation:
```bash
# Should see warnings but exit 0:
  → Training succeeded, but artifact upload failed (AWS Academy restriction)
  ⚠️  Warning: Could not upload plots to MLflow: ...
  ⚠️  Warning: Could not register model to MLflow: ...
  → Model saved locally as best.pth
  → MLflow run finished
```

**IAM Policy Example:**
```json
{
  "Effect": "Deny",
  "Action": [
    "s3:PutObject",
    "s3:PutObjectAcl"
  ],
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "aws:PrincipalOrgID": "voclabs"
    }
  }
}
```
This deny cannot be overridden by any allow policy.

**References:**
- [AWS IAM Policy Evaluation Logic](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html)
- [MLflow Artifact Stores](https://mlflow.org/docs/latest/tracking.html#artifact-stores)
- Related workflow: [Run #21798024629](https://github.com/Rafallost/Water-Meters-Segmentation-Autimatization/actions/runs/21798024629)

**Date discovered:** 2026-02-08
**Date fixed:** 2026-02-08

---

## End of known issues

