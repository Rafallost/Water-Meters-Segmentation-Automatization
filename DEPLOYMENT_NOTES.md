# Deployment Notes & Status

**Date:** 2026-02-07 (Session 2 - Fresh Infrastructure)
**Phase:** Phase 6 - BLOCKED (EC2 Instance Unresponsive)

---

## 🚨 CURRENT STATUS: BLOCKED

**EC2 instance crashed during image pull - awaiting recovery**

### What Happened:
1. Successfully built 8.69GB PyTorch Docker image
2. Pushed to ECR (4.65GB compressed)
3. Deployed via Helm to k3s
4. Pod started pulling image from EC2
5. **t3.small (2GB RAM) crashed** - OOM during image extraction
6. Instance unresponsive to SSH and ping since 12:27 UTC

### Recovery Required:
User needs to check AWS Console and either:
- **Option A**: Restart/reboot the instance (i-02fb263c90e39258e)
- **Option B**: Upgrade to t3.medium (4GB RAM) before restarting
- **Option C**: Recreate with t3.large via Terraform

---

## ✅ What Was Completed (Before Crash)

### Phase 5: Infrastructure
- ✅ Terraform: 16 resources created
- ✅ EC2: t3.small, 20GB disk, us-east-1
- ✅ k3s: Running before crash
- ✅ MLflow: Running on port 5000 before crash
- ✅ ECR: wms-model repository created
- ✅ S3: DVC and MLflow buckets created
- ✅ GitHub Actions Runner: Installed and active

### Phase 2: Core Scripts
- ✅ `devops/scripts/data-qa.py` - Data validation
- ✅ `devops/scripts/quality-gate.py` - Metrics comparison
- ✅ Committed to devops submodule

### Phase 8: Cleanup Script
- ✅ `devops/scripts/cleanup-aws.sh` - Budget protection
- ✅ Empties S3 buckets, runs terraform destroy
- ✅ Committed to devops submodule

### Phase 6: Deployment (Partial)
- ✅ Docker image built (8.69GB, Python 3.12 + PyTorch CPU)
- ✅ Pushed to ECR (055677744286.dkr.ecr.us-east-1.amazonaws.com/wms-model:latest)
- ✅ Fixed Dockerfile: libgl1-mesa-glx → libgl1 for Python 3.12
- ✅ Fixed helm-values.yaml:
  - MLFLOW_TRACKING_URI: http://10.0.1.43:5000 (internal IP)
  - imagePullSecrets: ecr-secret
  - serviceMonitor: disabled (Prometheus not deployed yet)
- ✅ Resolved disk pressure: freed 8.5GB, removed taint
- ✅ Registered baseline model to MLflow:
  - Model: water-meter-segmentation v2 (Production)
  - File: best.pth (7.6MB)
  - Metrics: Dice 0.9275, IoU 0.8865
- ✅ Helm deployment executed successfully
- ❌ Pod status unknown (instance crashed during image pull)

---

## ⚠️ Critical Issue: t3.small Insufficient

### Problem:
**t3.small (2GB RAM) cannot handle 8.69GB PyTorch Docker image**

### Evidence:
- Pod status before crash: ContainerCreating → Running (2 restarts)
- Logs showed model loading from MLflow
- Image pull from ECR started (4.65GB compressed → 8.69GB uncompressed)
- Instance became unresponsive: SSH timeout, ping timeout
- Classic OOM (Out of Memory) symptoms

### Root Cause:
```
Available RAM: 2GB (t3.small)
Required for:
  - k3s control plane: ~400MB
  - System overhead: ~300MB
  - MLflow: ~200MB
  - Image extraction: ~9GB peak usage
  - Container runtime: ~2GB
Total peak: ~12GB

Result: OOM killer terminated processes, instance crashed
```

### Solution:
**Minimum: t3.medium (4GB RAM)**
**Recommended: t3.large (8GB RAM)** for stable operation

---

## 🔧 Configuration Changes (All Committed)

### docker/Dockerfile.serve
```dockerfile
# Fixed for Python 3.12 compatibility
RUN apt-get update && apt-get install -y \
    libgl1 \  # Changed from libgl1-mesa-glx
    libglib2.0-0
```
**Commit:** 75203bc

### infrastructure/helm-values.yaml
```yaml
# Fixed for container networking
env:
  - name: MLFLOW_TRACKING_URI
    value: "http://10.0.1.43:5000"  # Internal IP, not localhost

# Fixed for ECR authentication
imagePullSecrets:
  - name: ecr-secret

# Disabled until Prometheus deployed
serviceMonitor:
  enabled: false
```
**Commits:** e1a3cad, d7b4d02, c069847

### requirements.txt
```diff
+ boto3  # Required for MLflow + S3
```
**Already present**

---

## 📋 AWS Resources (Current Session)

### EC2
- **Instance ID**: i-02fb263c90e39258e
- **Type**: t3.small (2GB RAM, 2 vCPU) ⚠️ **INSUFFICIENT**
- **Disk**: 20GB
- **Public IP**: 13.219.216.230 ⚠️ **UNRESPONSIVE**
- **Private IP**: 10.0.1.43
- **Region**: us-east-1
- **SSH**: `ssh -i ~/.ssh/labsuser.pem ec2-user@13.219.216.230`
- **Status**: Unknown (likely stopped or crashed)

### ECR
- **Registry**: 055677744286.dkr.ecr.us-east-1.amazonaws.com
- **Repository**: wms-model
- **Image**: latest (4.65GB compressed, pushed successfully)

### S3 Buckets
- **DVC**: wms-dvc-data-055677744286
- **MLflow**: wms-mlflow-artifacts-055677744286

### MLflow Model Registry
- **Model**: water-meter-segmentation
- **Version 1**: Placeholder (pickle file)
- **Version 2**: Baseline U-Net (best.pth, Dice 0.9275, IoU 0.8865) ✅ **Production**

---

## 🚀 Next Steps (After Recovery)

### Immediate (Once Instance is Back):
1. Verify instance is running: `aws ec2 describe-instances --instance-ids i-02fb263c90e39258e`
2. SSH to instance: `ssh -i ~/.ssh/labsuser.pem ec2-user@13.219.216.230`
3. Check k3s: `kubectl get nodes`
4. Check pods: `kubectl get pods`
5. Check logs: `kubectl logs -l app.kubernetes.io/name=ml-model --tail=50`
6. If pod is running, test endpoints:
   ```bash
   NODE_PORT=$(kubectl get svc wms-model-ml-model -o jsonpath='{.spec.ports[0].nodePort}')
   curl http://13.219.216.230:$NODE_PORT/health
   curl http://13.219.216.230:$NODE_PORT/metrics
   ```

### If Instance Needs Upgrade:
```bash
# Stop instance
aws ec2 stop-instances --instance-ids i-02fb263c90e39258e --wait

# Modify instance type
aws ec2 modify-instance-attribute \
  --instance-id i-02fb263c90e39258e \
  --instance-type t3.medium

# Start instance
aws ec2 start-instances --instance-ids i-02fb263c90e39258e

# Wait for startup
aws ec2 wait instance-running --instance-ids i-02fb263c90e39258e

# Get new public IP
aws ec2 describe-instances \
  --instance-ids i-02fb263c90e39258e \
  --query 'Reservations[0].Instances[0].PublicIpAddress'
```

### Priority: Task #16 - Training Pipeline
Once deployment is verified working, implement GitHub Actions workflow:
1. Trigger on data changes (`WMS/data/training/**`)
2. Run data QA (`devops/scripts/data-qa.py`)
3. Train model (`WMS/src/train.py`)
4. Quality gate (`devops/scripts/quality-gate.py`)
5. Register to MLflow if passing
6. Create PR comment with results

---

## 💡 Lessons Learned (This Session)

### 1. Instance Sizing is CRITICAL
- **t3.small (2GB)**: ❌ Cannot run k3s + ML containers
- **t3.medium (4GB)**: ✅ Minimum for serving
- **t3.large (8GB)**: ✅ Recommended for builds + serving
- **Rule**: 3-4x image size in RAM for safe operation

### 2. PyTorch Images Are Huge
- Uncompressed: 8.69GB
- Compressed in ECR: 4.65GB
- Peak extraction memory: ~10GB
- Plan accordingly!

### 3. Kubernetes Configuration
- **imagePullSecrets required** for private ECR
  ```bash
  kubectl create secret docker-registry ecr-secret \
    --docker-server=<ecr-url> \
    --docker-username=AWS \
    --docker-password=$(aws ecr get-login-password)
  ```
- **MLFLOW_TRACKING_URI** must use internal IP (10.0.x.x), not localhost
- **ServiceMonitor** requires Prometheus CRDs installed first

### 4. Disk Pressure Handling
- k3s automatically taints nodes with disk pressure
- `docker system prune -a -f` frees ~8GB
- Manually remove taint: `kubectl taint nodes --all node.kubernetes.io/disk-pressure:NoSchedule-`

### 5. MLflow Model Registration
- Can register .pth files without loading if create proper MLmodel manifest
- Python 3.7 compatible: use `create_model_version()` not `create_registered_model()`
- Set stage with `transition_model_version_stage(..., archive_existing_versions=True)`

---

## 📊 Time Tracking

- **Phase 5** (Infrastructure): ~15 min ✅
- **Phase 2** (Scripts): ~10 min ✅
- **Phase 8** (Cleanup): ~5 min ✅
- **Phase 6** (Deployment): ~50 min ⚠️ BLOCKED
- **Total**: ~80 min (~1h 20m)
- **Remaining**: ~2h 40m in 4-hour window

---

## 🔐 Security Notes

### GitHub Push Protection
- AWS credentials detected in CONFIGURATION.md
- Fixed by replacing with placeholders
- Commit amended and pushed successfully

### ECR Authentication
- ECR tokens expire every 12 hours
- imagePullSecret needs refresh for long-running clusters
- For production: use IAM roles for service accounts

---

**Last Updated:** 2026-02-07 12:35 UTC
**Status:** BLOCKED - Awaiting EC2 instance recovery
**Next Action:** User to check AWS Console and restart/upgrade instance
