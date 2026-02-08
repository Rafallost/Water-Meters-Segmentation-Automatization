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
  --gunicorn-opts "--timeout 300 --workers 2 --keep-alive 120"
```

**Configuration explained:**
- `--timeout 300`: 5 minutes worker timeout (matches MLFLOW_HTTP_REQUEST_TIMEOUT in workflow)
- `--workers 2`: Explicit worker count (prevents spawning too many)
- `--keep-alive 120`: 2 minute keep-alive for slow connections (helps with internet latency)

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

## End of known issues

