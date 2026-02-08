# Known Issues

This document tracks known issues and their workarounds.

---

## GitHub Actions: Bot-created PRs don't trigger training workflow

**Status:** Known limitation, workaround available

**Issue:**
When the `data-upload.yaml` workflow creates a PR using `github-actions[bot]`, the `train.yml` workflow doesn't automatically run on that PR. This is a GitHub security feature to prevent infinite workflow loops.

**Affected workflows:**
- `data-upload.yaml` creates PR → `train.yml` should run but doesn't

**Impact:**
- Users must manually trigger training after uploading data via `data/**` branches
- Training doesn't start automatically on bot-created PRs

**Current workaround:**
1. After PR is created, checkout the PR branch locally
2. Push an empty commit as yourself (not bot):
   ```bash
   git checkout <pr-branch>
   git commit --allow-empty -m "ci: trigger training workflow"
   git push
   ```
3. This triggers `train.yml` because the commit is from a user, not a bot

**Proper fix (TODO):**
Modify `data-upload.yaml` to use a Personal Access Token (PAT) instead of `GITHUB_TOKEN` when creating PRs:

1. Create PAT in GitHub Settings → Developer settings → Personal access tokens
   - Permissions: `Contents: Read/Write`, `Pull requests: Read/Write`, `Workflows: Read/Write`
   - Expiration: 90 days minimum (or longer for production)

2. Add to GitHub Secrets: `GH_PAT`

3. Update `.github/workflows/data-upload.yaml` line ~101:
   ```yaml
   - name: Create or Update Pull Request
     uses: actions/github-script@v7
     with:
       github-token: ${{ secrets.GH_PAT }}  # ← Add this line
       script: |
         # ... rest unchanged
   ```

**References:**
- GitHub Docs: [Triggering a workflow from a workflow](https://docs.github.com/en/actions/using-workflows/triggering-a-workflow#triggering-a-workflow-from-a-workflow)
- Related: PR #7, PR #4 (training didn't auto-start)

**Date discovered:** 2026-02-08

---

## MLflow 503 errors during parallel training attempts

**Status:** Fixed with workaround

**Issue:**
When running multiple training attempts in parallel or sequentially without delays, MLflow server returns `503 Service Unavailable` errors. This happens because:

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

**Status:** Fixed

**Issue:**
Training workflow fails on the final git push step when the remote branch has new commits that were pushed during training. This happens because:

1. Workflow checks out branch at start (e.g., commit A)
2. Training runs for 45+ minutes
3. Developer pushes new commits during training (e.g., commit B)
4. Workflow tries to push metrics update from commit A → rejected (remote is now at commit B)

**Symptoms:**
```
[detached HEAD 61c0a95] chore: update Production model metrics (v3)
 2 files changed, 32 insertions(+), 8 deletions(-)
To https://github.com/Rafallost/Water-Meters-Segmentation-Autimatization
 ! [rejected]        HEAD -> data/training-20260208 (fetch first)
error: failed to push some refs
hint: Updates were rejected because the remote contains work that you do not
hint: have locally.
Error: Process completed with exit code 1.
```

**Root cause:**
- Long-running training job (40-50 minutes)
- No synchronization between workflow start and end
- Direct `git push` without checking for remote updates
- Metrics commit is created from stale branch HEAD

**Impact:**
- Training succeeds, but metrics update fails
- Production model tracking files not updated
- Workflow marked as failed even though training worked
- Manual intervention required to push metrics

**Fix:**
Modified `.github/workflows/train.yml` to fetch and sync with remote before pushing:

```yaml
- name: Commit Production metrics to repo
  if: steps.aggregate.outputs.any_improved == 'true'
  run: |
    BRANCH="${{ github.head_ref || github.ref_name }}"

    git config user.name "github-actions[bot]"
    git config user.email "github-actions[bot]@users.noreply.github.com"

    # Fetch latest changes from remote
    git fetch origin "$BRANCH"

    # Stash our metrics changes
    git add WMS/models/production_current.json WMS/models/production_history.jsonl
    git diff --cached --quiet && echo "No changes to commit" && exit 0
    git stash push -m "metrics update"

    # Switch to latest version of branch
    git checkout "$BRANCH"
    git pull origin "$BRANCH"

    # Re-apply our metrics changes
    git stash pop

    # Commit and push
    git add WMS/models/production_current.json WMS/models/production_history.jsonl
    git commit -m "chore: update Production model metrics (v${{ steps.aggregate.outputs.best_attempt }})"
    git push origin "$BRANCH"
```

**How it works:**
1. **Fetch** latest remote changes
2. **Stash** our metrics file updates
3. **Checkout** and pull the latest branch version
4. **Pop** stash to re-apply metrics updates on top of latest code
5. **Commit** and push (now in sync with remote)

**Why stash instead of rebase:**
- Metrics files (`production_current.json`, `production_history.jsonl`) are independent
- No code conflicts possible - only data files updated
- Stash + pop is simpler than rebase conflict resolution
- Idempotent operation - can safely re-apply on any commit

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

