# System Architecture

This document explains the overall system design and components.

---

## 🏗️ High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        GITHUB REPOSITORY                        │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ ML Code      │  │ Workflows    │  │ Training     │         │
│  │ (WMS/)       │  │ (.github/)   │  │ Data (DVC)   │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
└────────────┬────────────────┬────────────────┬─────────────────┘
             │                │                │
             ▼                ▼                ▼
┌────────────────────────────────────────────────────────────────┐
│              GITHUB ACTIONS (Orchestration)                    │
│  • Data validation                                             │
│  • Training coordination                                       │
│  • Quality gates                                               │
└────────────┬───────────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────────────┐
│                         AWS CLOUD                               │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  EC2 Instance (Ephemeral - starts/stops automatically)   │  │
│  │                                                           │  │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────┐          │  │
│  │  │ MLflow   │    │ k3s      │    │ Model    │          │  │
│  │  │ Server   │    │ (Future) │    │ Serving  │          │  │
│  │  │ :5000    │    │          │    │ (Future) │          │  │
│  │  └──────────┘    └──────────┘    └──────────┘          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌──────────────┐      │
│  │ S3 Bucket   │    │ S3 Bucket   │    │ ECR          │      │
│  │ (DVC Data)  │    │ (MLflow)    │    │ (Docker)     │      │
│  │             │    │ (Artifacts) │    │ (Future)     │      │
│  └─────────────┘    └─────────────┘    └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🧩 Components

### 1. **Version Control (GitHub)**

#### Repository Structure
```
Water-Meters-Segmentation-Autimatization/
├── WMS/                          # ML code
│   ├── src/                      # Training, inference scripts
│   ├── data/training/            # Training data (Git/DVC)
│   ├── configs/                  # Training configs
│   └── models/                   # Local model checkpoints (gitignored)
├── .github/workflows/            # CI/CD pipelines
├── docs/                         # Documentation
├── devops/                       # Submodule: infrastructure code
│   ├── terraform/                # Infrastructure as Code
│   ├── helm/                     # Kubernetes deployment
│   ├── scripts/                  # Automation scripts
│   └── hooks/                    # Git hooks
└── README.md
```

#### Git Submodule
- **devops/** is a Git submodule pointing to `DevOps-AI-Model-Automatization` repo
- Contains infrastructure code shared across projects
- Update with: `git submodule update --remote devops`

---

### 2. **Data Management**

#### DVC (Data Version Control)
- **Purpose:** Track large files (images, masks) without bloating Git
- **Backend:** S3 bucket (`s3://wms-dvc-data-<account>/`)
- **Metadata:** `.dvc` files committed to Git

```
WMS/data/training/images.dvc   ← Git tracks this (tiny JSON)
WMS/data/training/images/       ← Actual data in S3 (large)
```

#### POC Mode (Current)
- Training data tracked directly in Git (small dataset, 11 images)
- Good for quick iterations
- Production: Move to DVC when dataset grows

---

### 3. **ML Experiment Tracking (MLflow)**

#### Deployment
- **Runs on:** EC2 instance
- **Port:** 5000
- **Backend Store:** SQLite (file-based)
- **Artifact Store:** S3 bucket (`s3://wms-mlflow-artifacts-<account>/`)

#### What MLflow Tracks
- Training runs with hyperparameters
- Metrics: Dice, IoU, accuracy, loss
- Model artifacts (.pth files)
- Model versions and stages (Staging, Production)

#### Model Versioning
```
Model Registry:
  water-meter-segmentation
  ├── v1 (Baseline) → Production
  │   └── Dice: 0.9275, IoU: 0.8865
  ├── v2 (Attempt 1) → Staging
  │   └── Dice: 0.9310, IoU: 0.8890
  └── v3 (Best) → Production  ✅
      └── Dice: 0.9350, IoU: 0.8920
```

**Source of truth:** MLflow, not Git. Git only stores code.

---

### 4. **Infrastructure (AWS)**

#### Terraform-Managed Resources
```
VPC (10.0.0.0/16)
├── Public Subnet (10.0.1.0/24)
├── Internet Gateway
└── Security Group
    ├── Port 22: SSH (your IP)
    ├── Port 5000: MLflow (GitHub Actions)
    └── Port 8000: HTTP (future model API)

EC2 Instance (t3.large)
├── OS: Amazon Linux 2023
├── Storage: 40GB
├── MLflow Server (systemd service)
└── k3s (lightweight Kubernetes, future)

S3 Buckets
├── wms-dvc-data-<account>
└── wms-mlflow-artifacts-<account>

ECR Repository (future)
└── wms-model (Docker images)

Elastic IP (optional, not currently used)
```

#### Ephemeral Infrastructure
- **Traditional:** EC2 runs 24/7 (~$18/month)
- **Ephemeral:** EC2 starts only during training (~$4/month)
- **How:** `ec2-control.yaml` workflow starts/stops instance
- **Cost savings:** 70-80% reduction

---

### 5. **Training Pipeline**

#### Training Runners
- **Where:** GitHub-hosted runners (free!)
- **Duration:** ~3 minutes per attempt
- **Parallelization:** 3 attempts run simultaneously

#### Training Process
```
1. prepareDataset.py
   ↓ Splits data into train/val/test
2. train.py
   ↓ Trains U-Net model
   ↓ Logs to MLflow (metrics, artifacts)
3. quality-gate.py
   ↓ Compares to baseline
   ↓ Promotes if improved
```

#### Model Architecture
- **Type:** U-Net for semantic segmentation
- **Input:** 512×512 RGB images (water meter photos)
- **Output:** 512×512 binary masks (meter region)
- **Framework:** PyTorch
- **Size:** ~7.6MB (.pth file)

---

### 6. **CI/CD Orchestration (GitHub Actions)**

#### Workflow Orchestration
```
User Action → Workflow Trigger → Jobs → Steps → Tools

Example:
  git push data/staging
    ↓
  data-staging.yaml
    ↓
  Creates timestamped branch
    ↓
  data-upload.yaml
    ↓
  Validates & creates PR
    ↓
  train.yml (PR trigger)
    ↓
  start-infra → train (×3) → aggregate → stop-infra
```

See **WORKFLOWS.md** for detailed workflow explanations.

---

### 7. **Quality Gates**

#### Data Quality Gate (`data-qa.py`)
- Runs before training
- Checks:
  - Image ↔ mask pairs match
  - Resolutions match (512×512)
  - Masks are binary (0, 255 only)
  - Sufficient coverage (>100 pixels)
- **Blocks training if fails**

#### Model Quality Gate (`quality-gate.py`)
- Runs after training
- Baseline metrics (from original model):
  - Dice: 0.9275
  - IoU: 0.8865
- Thresholds (2% tolerance):
  - Dice: ≥0.9075
  - IoU: ≥0.8665
- **Promotes to Production if improved**

---

## 🔄 Data Flow

### Training Data Flow
```
Local Machine
  ↓ git push
GitHub Repository
  ↓ DVC pull (in GitHub Actions)
S3 Bucket
  ↓ Download during training
GitHub-Hosted Runner
  ↓ Train model
MLflow on EC2
  ↓ Store model artifact
S3 MLflow Bucket
```

### Model Deployment Flow (Future)
```
MLflow Model Registry (Production stage)
  ↓ Download model
Docker Image Build
  ↓ Push to ECR
ECR
  ↓ Pull image
k3s on EC2
  ↓ Serve via HTTP API
Users/Applications
```

---

## 🔐 Security & Access

### AWS Credentials
- Stored in GitHub Secrets:
  - `AWS_ACCESS_KEY_ID`
  - `AWS_SECRET_ACCESS_KEY`
  - `AWS_SESSION_TOKEN` (for AWS Academy)
- **Expire every 4 hours** in AWS Academy
- **Manual update required** for each session

### EC2 Access
- SSH: Key pair (`labsuser.pem`)
- Allowed from: Your IP only (security group)

### GitHub Actions Permissions
- `contents: read` - Read repository code
- `issues: write` - Post comments on issues
- `pull-requests: write` - Create/update PRs, post comments

---

## 💰 Cost Optimization

### Current Costs (~$4/month)
- **EC2 (ephemeral):** ~$2-3/month (10 min/training × ~20 trainings/month)
- **S3 Storage:** ~$1/month (DVC data + MLflow artifacts)
- **ECR Storage:** $0 (future)
- **Data Transfer:** Negligible

### Traditional Costs (~$18/month)
- EC2 24/7: ~$15/month
- S3: ~$1/month
- GitHub Actions: Free (public repo)

### Budget Protection
- **Cleanup script:** `devops/scripts/cleanup-aws.sh`
- **Runs:** `terraform destroy`, empties S3 buckets
- **Use when:** Finished testing or reaching budget limit

---

## 📊 Monitoring (Future - Phase 9)

### Prometheus + Grafana
- Model inference metrics
- Request latency
- Prediction quality
- System health

**Status:** Not yet implemented (Phase 9)

---

## 🚀 Deployment Architecture (Future - Phase 6)

```
                ┌──────────────────────┐
                │   Model API (k3s)    │
                │   /predict endpoint  │
                └──────────┬───────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
     ┌────▼────┐      ┌────▼────┐     ┌────▼────┐
     │ Pod 1   │      │ Pod 2   │     │ Pod 3   │
     │ Model   │      │ Model   │     │ Model   │
     │ v3      │      │ v3      │     │ v3      │
     └─────────┘      └─────────┘     └─────────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                    ┌──────▼──────┐
                    │   MLflow    │
                    │   (Models)  │
                    └─────────────┘
```

**Status:** Partially implemented (Docker build works, deployment pending)

---

## 📚 Related Documentation

- **WORKFLOWS.md** - All workflows explained
- **SETUP.md** - How to set up infrastructure
- **USAGE.md** - How to use the system
- **devops/PLAN.md** - Implementation phases
- **devops/CLAUDE.md** - AI assistant context
