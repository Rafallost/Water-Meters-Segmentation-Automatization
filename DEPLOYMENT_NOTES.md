# Deployment Notes & Issues to Fix

**Date:** 2026-02-07
**Phase:** Phase 6 - Deployment Completed

## ✅ What Works Now

1. **Infrastructure (Phase 5):**
   - EC2 instance: t3.large, 40GB disk (upgraded from t3.small/20GB due to OOM)
   - k3s Kubernetes cluster running
   - MLflow server on port 5000
   - ECR registry for Docker images

2. **Application Deployment:**
   - FastAPI serving app deployed via Helm
   - Pod running successfully (1/1 READY)
   - All endpoints working:
     - `/health` - returns healthy status
     - `/metrics` - Prometheus metrics exposed
     - `/predict` - image segmentation working (~1.6s latency on CPU)

3. **Model:**
   - MLflow Model Registry: `water-meter-segmentation` v2 in Production stage
   - Model: WaterMetersUNet (untrained - temporary workaround)
   - Artifacts stored in S3 via MLflow

## ⚠️ Known Issues & Temporary Workarounds

### 1. Untrained Model (CRITICAL - Task #16)
**Problem:** Currently using an **untrained** WaterMetersUNet model
**Impact:** Predictions will be random/poor quality
**Workaround:** Deployed untrained model to complete Phase 6 on time
**Proper Solution:**
- Implement training pipeline in GitHub Actions (Task #16)
- Train model with existing data (9 images + masks in `WMS/data/training/`)
- Automatically register trained model to MLflow
- See `WMS/src/train.py` - already has MLflow integration built-in

### 2. PyTorch Version Mismatch (LOW PRIORITY)
**Warning in logs:**
```
Stored model version '1.13.1+cu117' does not match installed PyTorch version '2.10.0+cpu'
```
**Impact:** Model loads successfully but there's a version mismatch
**Cause:** Model saved with Python 3.7/PyTorch 1.13.1 on EC2, loaded with Python 3.12/PyTorch 2.10.0 in container
**Solution:** When proper training is implemented, ensure training environment matches serving environment

### 3. Missing boto3 Dependency
**Problem:** MLflow needs `boto3` to download model artifacts from S3
**Fix Applied:** ✅ Added `boto3` to `requirements.txt`
**Commit:** Pending (current session)

### 4. MLflow Configuration
**Current Setup:**
- `MLFLOW_TRACKING_URI=http://10.0.1.213:5000` (EC2 internal IP)
- Set in `infrastructure/helm-values.yaml`
- Works for current deployment but hardcoded to specific EC2 IP

**Potential Issue:** If EC2 IP changes, need to update Helm values
**Better Solution (future):** Use internal DNS or service discovery

## 🔧 Configuration Files Modified

### requirements.txt
```diff
+ boto3  # Added for MLflow S3 artifact access
```

### infrastructure/helm-values.yaml
```yaml
env:
  - name: MLFLOW_TRACKING_URI
    value: http://10.0.1.213:5000  # EC2 internal IP
  - name: MODEL_VERSION
    value: production
```

### docker/Dockerfile.serve
- Uses CPU-only PyTorch: `--extra-index-url https://download.pytorch.org/whl/cpu`
- Python 3.12-slim base image
- Multi-stage build for optimized size

## 📋 Completed Tasks (Phase 6)

- [x] Task #2: Create FastAPI serving application
- [x] Task #3: Create Dockerfile for serving
- [x] Task #4: Create Helm chart for ML model
- [x] Task #5: Create Helm values override file
- [x] Task #6: Build and push Docker image to ECR
- [x] Task #7: Deploy to k3s using Helm
- [x] Task #8: Run smoke tests on deployed service
- [x] Task #17: Register model to MLflow (workaround)

## 🚀 Next Steps (Priority Order)

1. **Task #16: Training Pipeline (CRITICAL)**
   - Setup GitHub Actions workflow for training
   - Integrate with MLflow for automatic model registration
   - Quality gate: compare metrics to baseline (Dice ≥ 0.9075, IoU ≥ 0.8665)
   - Auto-deploy if metrics improve

2. **Task #9: Monitoring**
   - Setup Prometheus scraping
   - Create Grafana dashboards
   - Monitor: latency, predictions/sec, error rate

3. **Task #10-15: Documentation & Testing**
   - Unit tests for model and API
   - Manual deployment instructions
   - AWS cleanup script
   - Architecture documentation with Mermaid diagrams

## 💡 Lessons Learned

1. **Resource Planning:**
   - t3.small (2GB RAM) insufficient for ML Docker builds
   - Upgraded to t3.large (8GB RAM) - builds complete in ~3 minutes

2. **MLflow Dependencies:**
   - MLflow requires `boto3` for S3 artifact storage
   - This wasn't caught in local testing

3. **Model Compatibility:**
   - PyTorch models should be saved/loaded with same Python version
   - Version mismatch warnings but model still loads (degraded mode?)

4. **Kubernetes ImagePullSecrets:**
   - Private ECR requires authentication
   - Created secret: `ecr-registry-secret` with AWS credentials
   - Secret needs refresh every 12 hours (ECR token expiry)

5. **DVC on EC2:**
   - DVC installation problematic on Python 3.7
   - Workaround: Parse .dvc manifest files and download directly from S3

## 🗂️ Key Files Reference

### Application Code
- `WMS/src/serve/app.py` - FastAPI serving application
- `WMS/src/train.py` - Training script with MLflow integration
- `WMS/src/model.py` - WaterMetersUNet architecture

### Infrastructure
- `infrastructure/helm-values.yaml` - Helm configuration overrides
- `devops/helm/ml-model/` - Helm chart for deployment
- `devops/terraform/` - AWS infrastructure as code
- `docker/Dockerfile.serve` - Production Docker image

### Data
- `WMS/data/training/images/` - 9 training images (downloaded from S3)
- `WMS/data/training/masks/` - 9 training masks
- `WMS/data/training/images.dvc` - DVC manifest for images
- `WMS/data/training/masks.dvc` - DVC manifest for masks

## 🔐 AWS Credentials & Access

### ECR
- Registry: `055677744286.dkr.ecr.us-east-1.amazonaws.com`
- Repository: `wms-model`
- Authentication: AWS CLI (`aws ecr get-login-password`)

### EC2
- Instance: t3.large (8GB RAM, 40GB disk)
- IP: 52.2.198.107 (public), 10.0.1.213 (private)
- SSH: `ssh -i ~/.ssh/labsuser.pem ec2-user@52.2.198.107`
- Region: us-east-1

### Kubernetes Service
- Service: `wms-model-ml-model`
- Type: NodePort
- Port: 32223 (current - may change on redeploy)
- Access: `http://52.2.198.107:32223`

## 📊 Current Metrics

### Pod Status
```
NAME                                  READY   STATUS    RESTARTS   AGE
wms-model-ml-model-7797f44b86-65n76   1/1     Running   0          8m
```

### Endpoint Tests
- `/health`: ✅ 200 OK (model_loaded: true)
- `/metrics`: ✅ Prometheus metrics available
- `/predict`: ✅ 200 OK (1.6s latency on CPU)

### MLflow Registry
- Model: `water-meter-segmentation`
- Version: 2 (Production stage)
- Type: WaterMetersUNet (3 in, 1 out, 16 base filters)
- Status: Untrained (workaround)

---

**Last Updated:** 2026-02-07
**Next Review:** After Task #16 (Training Pipeline) completion
