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
├── Storage: 100GB
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
- **Where:** Self-hosted runner na EC2
- **Duration:** ~1-2 godziny (50 epok, t3.large CPU)
- **Attempts:** Jedna próba (single training run)

#### Training Process
```
1. prepareDataset.py
   ↓ Splits data into train/val/test (80/10/10)
2. train.py  (single run, seed = github.run_number)
   ↓ Trains U-Net model (50 epok, early stopping patience=5)
   ↓ Logs to MLflow (metrics, artifacts)
3. Quality gate (inline, po treningu)
   ↓ Fetches dynamic baseline from MLflow Production
   ↓ Promotes to Production if improved
   ↓ dvc push (tylko jeśli improved) → S3 DVC bucket
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
  git add WMS/data/training/images/new.jpg
  git commit -m "data: new sample"
  git push origin main
    ↓
  Pre-push hook intercepts
    ↓ Creates data/20260213-HHMMSS branch, pushes there
  training-data-pipeline.yaml (triggered on data/* push)
    ↓
  merge-and-validate → start-infra → train → stop-infra
    ↓ if improved:
  deploy → stop-after-deploy → create-pr → auto-merge
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

#### Model Quality Gate (inline in `training-data-pipeline.yaml`)
- Runs after single training run
- Baseline: dynamically fetched from MLflow Production model
  - If no Production model exists: baseline = 0.0 (first training always passes)
- Condition: `new_dice > baseline_dice AND new_iou > baseline_iou`
- **Promotes to Production if improved, dvc push do S3, PR created**
- **No PR created if model did not improve**

---

## 🔄 Data Flow

### Training Data Flow
```
Local Machine
  ↓ git push origin main (with new images)
Pre-Push Hook
  ↓ Creates data/TIMESTAMP branch, pushes new files there
GitHub Actions — merge-and-validate job
  ↓ Downloads existing data from S3 (via DVC, main branch hashes)
  ↓ Merges existing + new data on runner
  ↓ Validates merged dataset (data-qa.py)
  ↓ upload-artifact → GitHub artifact storage (NIE S3 przed treningiem)
GitHub Actions — train job (EC2 runner)
  ↓ download-artifact (scalony dataset)
  ↓ Train model (single run, 50 epochs)
  ↓ [if improved] dvc add + dvc push → S3 DVC Bucket
MLflow on EC2
  ↓ Store metrics + model artifacts
S3 MLflow Bucket
```

### Model Deployment Flow
```
MLflow Model Registry (Production stage)
  ↓ download-model.sh (on EC2)
Docker Image Build
  ↓ build-and-push.sh → push to ECR
ECR
  ↓ deploy-to-k3s.sh → pull image
k3s on EC2
  ↓ Serve via HTTP API (NodePort)
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

## 📊 Monitoring (opcjonalne)

Prometheus + Grafana dostępne opcjonalnie — włączone przez `install_monitoring = true` w `terraform.tfvars`. Dostęp przez SSH tunnel (port 3000). Wyłączone domyślnie (~750MB RAM).

---

## 🚀 Deployment Architecture

```
                ┌──────────────────────┐
                │   Model API (k3s)    │
                │   FastAPI :8000      │
                │   /predict endpoint  │
                └──────────┬───────────┘
                           │
                    ┌──────▼──────┐
                    │   MLflow    │
                    │   :5000     │
                    └─────────────┘
```

Model serwowany przez FastAPI w Docker (ECR → k3s NodePort). Jeden pod na single-node k3s. Deploy przez Helm chart (`devops/helm/ml-model`).

---

## 📚 Related Documentation

- **WORKFLOWS.md** - All workflows explained
- **SETUP.md** - How to set up infrastructure
- **USAGE.md** - How to use the system
- **devops/PLAN.md** - Implementation phases
- **devops/CLAUDE.md** - AI assistant context
