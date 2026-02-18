# System Diagrams

Visual representations of the Water Meters Segmentation ML pipeline.

---

## 1. End-to-End System Flow

Complete workflow from data upload to model deployment.

```mermaid
graph TB
    subgraph "User Actions"
        A[User: Add Training Data] --> B[Git Commit & Push]
    end

    subgraph "Git Hook"
        B --> C{Pre-push Hook}
        C -->|Detects NEW data| D[Create data/TIMESTAMP branch<br/>Push NEW files only]
        C -->|No data changes| E[Push to main]
    end

    subgraph "GitHub Actions - Data Merging & QA"
        D --> D1[Download existing data from S3]
        D1 --> D2[Merge: existing + new = complete]
        D2 --> D3[Update DVC tracking]
        D3 --> G[Data Quality Check]
        G -->|Failed| H[❌ Comment on commit<br/>Pipeline stops]
        G -->|Passed| I[✅ QA Passed]
    end

    subgraph "GitHub Actions - Infrastructure"
        I --> J[Start EC2 Instance<br/>AWS CLI start-instances]
        J --> K[Wait for self-hosted runner]
    end

    subgraph "GitHub Actions - Training"
        K --> L[Train Model ONCE<br/>Single run on full dataset]
        L --> M[Log to MLflow]
    end

    subgraph "Quality Gate"
        M --> N[Fetch Production Baseline]
        N --> O{Compare Metrics}
        O -->|Dice improved| P[✅ Promote to Production]
        O -->|No improvement| Q[❌ Keep existing]
    end

    subgraph "Deployment"
        P --> R[Create PR → Auto-merge to main]
        R --> S[Build Docker Image]
        S --> T[Push to ECR]
        T --> V[Deploy to k3s]
        V --> V1[Helm upgrade/install<br/>kube-prometheus-stack]
    end

    subgraph "Monitoring"
        V1 --> W[Prometheus Scrapes /metrics]
        W --> X[Grafana Dashboard]
    end

    subgraph "Cleanup (always runs)"
        M --> Y[Stop EC2]
        Q --> Y
        V1 --> Y
    end

    style P fill:#d4edda,stroke:#2e7d32,color:#000
    style Q fill:#f8d7da,stroke:#842029,color:#000
    style H fill:#f8d7da,stroke:#842029,color:#000
```

---

## 2. Training Pipeline Details

Single training run on the full merged dataset, with quality gate comparing against the current Production model.

```mermaid
graph LR
    subgraph "Start Infrastructure"
        A[EC2 Stopped] --> B[GitHub Actions Trigger]
        B --> C[AWS CLI: start-instances]
        C --> D[Wait for self-hosted runner]
    end

    subgraph "Training"
        D --> F[Train Model<br/>seed=run_number]
        F --> QG{Quality Gate}
    end

    subgraph "Quality Gate Logic"
        QG --> BL[Fetch Production Baseline<br/>from MLflow dynamically]
        BL --> CMP[new_dice > baseline AND<br/>new_iou > baseline]
    end

    subgraph "Result"
        QG -->|Improved| J[Model Improved ✅]
        QG -->|Not improved| K[Not Improved ❌]
    end

    subgraph "Promote Model"
        J --> L[Register to MLflow]
        L --> M[Transition to Production]
    end

    subgraph "PR & Deployment"
        M --> Q[Create PR → Auto-merge]
    end

    subgraph "No PR"
        K --> R[Data branch remains<br/>for review]
    end

    subgraph "Stop Infrastructure (always)"
        M --> S[EC2 Stop]
        K --> S
    end

    style M fill:#d4edda,stroke:#2e7d32,color:#000
    style R fill:#f8d7da,stroke:#842029,color:#000
```

**Seed strategy:** `run_number` is the GitHub Actions run number (auto-increments with each pipeline run). Using it as the seed ensures different weight initializations and data splits across pipeline runs, improving reproducibility while allowing natural variation.

---

## 2b. Workflow Job Sequence: training-data-pipeline.yaml

Job dependency graph as seen in GitHub Actions — 8 jobs, two conditional branches after training.

```mermaid
flowchart LR
    A["1: merge-and-validate<br/>Download S3 · merge<br/>Validate · update DVC"]
    A -->|validation passed| B["2: start-infra<br/>Start EC2<br/>Wait for runner"]
    A -->|validation failed| FAIL["❌ Pipeline stops"]

    B --> C["3: train<br/>Train U-Net · log to MLflow<br/>Run quality gate"]

    C -->|"not improved<br/>or failed"| D["4: stop-infra<br/>Stop EC2<br/>if: always()"]

    C -->|"improved = true"| E["5: deploy<br/>Build Docker · push ECR<br/>Helm upgrade · smoke test"]
    C -->|"improved = true"| G["7: create-pr<br/>Create PR<br/>with metrics"]

    E --> F["6: stop-after-deploy<br/>Stop EC2<br/>if: always()"]
    G --> H["8: auto-merge<br/>Enable<br/>auto-merge"]

    style FAIL fill:#f8d7da,stroke:#842029,color:#000
    style D fill:#fff3cd,stroke:#856404,color:#000
    style F fill:#fff3cd,stroke:#856404,color:#000
    style E fill:#d4edda,stroke:#2e7d32,color:#000
    style G fill:#d4edda,stroke:#2e7d32,color:#000
    style H fill:#d4edda,stroke:#2e7d32,color:#000
```

**EC2 stop logic:** Two separate stop jobs ensure EC2 is always shut down regardless of outcome:

- `stop-infra` (job 4): runs if train fails OR model not improved
- `stop-after-deploy` (job 6): runs after deployment (always)

---

## 3. Local Predictions Workflow

How users run predictions on their local machine.

```mermaid
graph TD
    subgraph "First Time Setup"
        A[Fresh git clone] --> B{Model exists locally?}
        B -->|No| C[Run sync_model_aws.py]
        C --> D[Start EC2]
        D --> E[Download from MLflow Production]
        E --> F[Save to WMS/models/production.pth]
    end

    subgraph "Predictions"
        B -->|Yes| G[Place images in photos_to_predict/]
        F --> G
        G --> H[Run predicts.py]
        H --> I[Load production.pth]
        I --> J[Process each image]
        J --> K[Generate masks]
        K --> L[Save to predicted_masks/]
    end

    subgraph "Model Update"
        M[New model trained & merged] --> N{Want latest model?}
        N -->|Yes| O[Run sync_model_aws.py --force]
        O --> P[Re-download Production model]
        P --> Q[Overwrite local cache]
        N -->|No| R[Use cached model]
    end

    style F fill:#d4edda,stroke:#2e7d32,color:#000
    style L fill:#d4edda,stroke:#2e7d32,color:#000
```

---

## 4. Model Versioning Flow

How models progress through stages in MLflow.

```mermaid
stateDiagram-v2
    [*] --> Training: Start training
    Training --> Registered: Log to MLflow
    Registered --> None: Initial stage

    None --> Production: Promote (manual or auto)
    None --> Staging: Test first (optional)
    Staging --> Production: Promote after testing

    Production --> Archived: New Production model
    Archived --> Production: Rollback (if needed)

    Production --> [*]: Model in use

    note right of Production
        - Downloaded by users
        - Deployed to k3s
        - Baseline for comparisons
    end note

    note right of Archived
        - Previous Production versions
        - Available for rollback
        - Historical reference
    end note
```

---

## 5. What Users Can Do

Matrix of capabilities with/without internet and EC2.

```mermaid
graph TB
    subgraph "✅ Always Available (Offline)"
        A1[Run predictions<br/>with cached model]
        A2[View local code]
        A3[Modify training code]
        A4[Add training data locally]
        A5[Run unit tests]
    end

    subgraph "🌐 Requires Internet (No EC2)"
        B1[Git operations<br/>clone, push, pull]
        B2[View GitHub Actions logs]
        B3[Browse code on GitHub]
        B4[Create/review PRs]
        B5[Trigger workflows manually]
    end

    subgraph "☁️ Requires EC2 Running"
        C1[Download new model<br/>from MLflow]
        C2[View model metrics<br/>show_metrics.py]
        C3[Check model versions<br/>check_model.py]
        C4[Browse MLflow UI]
        C5[Access Grafana dashboard<br/>NodePort :30300]
        C6[Query Prometheus metrics<br/>NodePort :30900]
    end

    subgraph "🔄 Triggers EC2 Auto-start"
        D1[Push training data<br/>hook creates data/* branch]
        D2[training-data-pipeline.yaml<br/>auto-starts EC2 and trains]
        D3[Manual workflow dispatch<br/>train.yml]
    end

    style A1 fill:#d4edda,stroke:#2e7d32,color:#000
    style B1 fill:#cff4fc,stroke:#055160,color:#000
    style C1 fill:#fff3cd,stroke:#664d03,color:#000
    style D1 fill:#FFA500
```

---

## 6. Architecture Overview

High-level system components and their interactions.

```mermaid
C4Context
    Person(user, "Data Scientist", "Uploads training data, runs predictions")

    System_Boundary(github, "GitHub") {
        Container(repo, "Git Repository", "Git / DVC", "Code, data manifests, configs")
        Container(actions, "GitHub Actions", "CI/CD", "8-job training pipeline")
    }

    System_Boundary(aws, "AWS Cloud") {
        Container(ec2, "EC2 t3.large", "Amazon Linux 2023", "Self-hosted runner + k3s node")
        ContainerDb(s3, "S3 Bucket", "Object Storage", "DVC data + MLflow artifacts")
        Container(ecr, "ECR", "Docker Registry", "Model API images")
    }

    System_Boundary(k3s, "k3s Cluster") {
        Container(mlflow, "MLflow", "Python / SQLite", "Experiment tracking, Model registry")
        Container(model_api, "Model API", "FastAPI / PyTorch", "POST /predict")
        Container(monitoring, "Prometheus + Grafana", "Monitoring", "Metrics + Dashboards")
    }

    Rel(user, repo, "git push")
    Rel(repo, actions, "Triggers workflow")
    Rel(actions, ec2, "Starts / stops EC2")
    Rel(actions, s3, "DVC push / pull")
    Rel(actions, ecr, "docker push")
    Rel(mlflow, s3, "Stores artifacts")
    Rel(model_api, mlflow, "Loads Production model")
    Rel(monitoring, model_api, "Scrapes /metrics")
    Rel(user, model_api, "POST /predict")
    Rel(user, mlflow, "Browses experiments")
```

---

## 7. Data Flow

How training data flows through the system.

```mermaid
graph LR
    subgraph "Local Development"
        A[Training Images<br/>.jpg] --> B[Local Repository]
        C[Training Masks<br/>.png] --> B
    end

    subgraph "Version Control"
        B --> D{Data Size}
        D -->|Small POC| E[Git directly]
        D -->|Large prod| F[DVC + S3]
        E --> G[GitHub]
        F --> H[S3 Bucket]
        H --> G
    end

    subgraph "CI/CD Pipeline"
        G --> I[GitHub Actions Runner]
        I --> J{DVC metadata?}
        J -->|Yes| K[dvc pull from S3]
        J -->|No| L[Use data from Git]
        K --> M[Training Data Ready]
        L --> M
    end

    subgraph "Training"
        M --> N[prepareDataset.py]
        N --> O[Train/Val/Test Split]
        O --> P[DataLoader]
        P --> Q[train.py]
    end

    subgraph "Model Artifacts"
        Q --> R[Model Weights<br/>best.pth]
        R --> S[MLflow]
        S --> T[S3 Bucket]
        T --> U[Production Stage]
    end

    subgraph "Download for Inference"
        U --> V[sync_model_aws.py]
        V --> W[Local Cache<br/>production.pth]
        W --> X[predicts.py]
    end

    style U fill:#28a745,stroke:#1e7e34,color:#fff
    style W fill:#28a745,stroke:#1e7e34,color:#fff
```

---

## 8. Monitoring & Observability Stack

Prometheus + Grafana integration.

```mermaid
graph TB
    subgraph "Application Layer"
        A["FastAPI App<br/>WMS Model API"] --> B["metrics endpoint<br/>/metrics"]
        B --> C["prometheus_client<br/>Python library"]
    end

    subgraph "Metrics"
        C --> D[wms_predictions_total<br/>Counter]
        C --> E[wms_predict_latency_seconds<br/>Histogram]
        C --> F[wms_predict_errors_total<br/>Counter]
        C --> G[wms_model_loaded<br/>Gauge]
    end

    subgraph "Collection"
        D --> H[ServiceMonitor CR]
        E --> H
        F --> H
        G --> H
        H --> I[Prometheus Operator]
        I --> J[Prometheus Server]
    end

    subgraph "Storage & Query"
        J --> K[TSDB<br/>Time Series Database]
        K --> L[PromQL<br/>Query Language]
    end

    subgraph "Visualization"
        L --> M[Grafana]
        M --> N[WMS Model Dashboard]
        N --> O[Request Rate Panel]
        N --> P[Latency Percentiles Panel]
        N --> Q[Error Rate Panel]
        N --> R[Resource Usage Panel]
    end

    subgraph "External Access"
        M --> U[Grafana NodePort :30300]
        J --> V[Prometheus NodePort :30900]
    end

    subgraph "Alerting (Optional)"
        L --> S[Alertmanager]
        S --> T[Slack/Email Notifications]
    end

    style N fill:#28a745,stroke:#1e7e34,color:#fff
```

---

## 9. Cost Optimization Strategy

How ephemeral infrastructure saves money.

```mermaid
gantt
    title EC2 Usage Pattern (1 Week Example)
    dateFormat HH:mm
    axisFormat %H:%M

    section Traditional (Always-On)
    EC2 Running (24/7)    :crit, 00:00, 24h

    section Ephemeral (Smart)
    EC2 Stopped          :done, 00:00, 9h
    Training Session 1   :active, 09:00, 15m
    EC2 Stopped          :done, 09:15, 3h45m
    Training Session 2   :active, 13:00, 15m
    EC2 Stopped          :done, 13:15, 2h45m
    Browse MLflow        :active, 16:00, 10m
    EC2 Stopped          :done, 16:10, 7h50m

    section Cost Savings
    Savings              :milestone, 00:00, 0h
```

**Cost Comparison:**

- Traditional: $18/month (24/7 running)
- Ephemeral: $4/month (100h/month usage)
- **Savings: 70%** 🎯

---

## 10. User Interaction Points

Where users interact with the system.

```mermaid
journey
    title User Journey - Training New Model
    section Add Data
        Clone repository: 5: User
        Add images/masks: 5: User
        Commit changes: 5: User
        Push to GitHub: 5: User
    section Automated Training
        Pre-push hook creates data branch (no AWS!): 9: Git Hook
        GitHub Actions downloads S3 data + merges: 8: GitHub Actions
        Data QA runs on merged dataset: 7: GitHub Actions
        EC2 starts: 8: GitHub Actions
        Model trains up to 3 attempts: 8: GitHub Actions
        If improved - PR auto-created and merged: 9: GitHub Actions
        EC2 stops: 8: GitHub Actions
    section Done
        New Production model in MLflow: 9: GitHub Actions
        Download new model if needed: 5: User, sync_model_aws.py
    section Use Model
        Download Production model: 7: User, sync_model_aws.py
        Run local predictions: 9: User, predicts.py
        View results: 9: User
```

---

## 11. Deployment Diagram

Concrete infrastructure — exact names, addresses and ports as deployed in AWS us-east-1.

```mermaid
graph TB
    subgraph dev["💻 Local Machine — Data Scientist"]
        cli["git push / predicts.py"]
    end

    subgraph gh["GitHub — Rafallost/Water-Meters-Segmentation-Autimatization"]
        repo["Repository\ncode + .dvc manifests"]
        hosted["GitHub-hosted runner\nubuntu-latest\n(merge · validate · PR jobs)"]
        repo --> hosted
    end

    subgraph aws["AWS us-east-1 — Account 055677744286"]

        subgraph ec2_box["EC2 t3.large · 100 GB gp3 · us-east-1a\nec2-user @ 100.50.251.97  ←  Elastic IP"]
            runner["GitHub Actions\nself-hosted runner\n(systemd)"]
            mlflow_svc["MLflow Server\n:5000\n(systemd)\nSQLite backend"]

            subgraph k3s["k3s cluster"]
                subgraph ns_wms["namespace: wms"]
                    model_pod["wms-model-api pod\nFastAPI · container :8000\nNodePort :30080"]
                end
                subgraph ns_mon["namespace: monitoring"]
                    prom["Prometheus\nNodePort :30900"]
                    grafana["Grafana\nNodePort :30300"]
                end
            end
        end

        s3_dvc[("S3\nwms-dvc-data-055677744286")]
        s3_mlf[("S3\nwms-mlflow-artifacts-055677744286")]
        ecr["ECR\n055677744286.dkr.ecr\n.us-east-1.amazonaws.com/wms-model"]
    end

    cli -->|"git push"| repo
    hosted -->|"aws ec2 start-instances"| runner
    hosted -->|"dvc push / pull"| s3_dvc
    hosted -->|"docker build + push"| ecr
    runner -->|"train.py + quality-gate.py"| mlflow_svc
    mlflow_svc -->|"boto3 · artifact storage"| s3_mlf
    ecr -->|"imagePull"| model_pod
    model_pod -->|"MlflowClient · load Production model"| mlflow_svc
    prom -->|"scrape :8000/metrics"| model_pod
    grafana -->|"PromQL"| prom

    cli -->|"http://100.50.251.97:5000"| mlflow_svc
    cli -->|"http://100.50.251.97:30080"| model_pod
    cli -->|"http://100.50.251.97:30300"| grafana

    style ec2_box fill:#fff8e1,stroke:#f9a825
    style k3s fill:#e3f2fd,stroke:#1565c0
    style ns_wms fill:#e8f5e9,stroke:#2e7d32
    style ns_mon fill:#fce4ec,stroke:#880e4f
    style aws fill:#fff3e0,stroke:#e65100
    style gh fill:#f3e5f5,stroke:#4a148c
    style dev fill:#e8eaf6,stroke:#283593
```

**Key endpoints:**

| Service    | URL                                  |
| ---------- | ------------------------------------ |
| MLflow UI  | `http://100.50.251.97:5000`          |
| Model API  | `http://100.50.251.97:30080/predict` |
| Grafana    | `http://100.50.251.97:30300`         |
| Prometheus | `http://100.50.251.97:30900`         |

---

## Usage Notes

### Viewing Diagrams

- **GitHub:** Mermaid diagrams render automatically in GitHub README/markdown files
- **VS Code:** Install "Markdown Preview Mermaid Support" extension
- **Local:** Use [Mermaid Live Editor](https://mermaid.live/)

### Updating Diagrams

1. Edit the mermaid code blocks in this file
2. Commit and push to see changes on GitHub
3. Or paste into Mermaid Live Editor for instant preview

### For Thesis

These diagrams are ready to use in your bachelor's thesis:

- Export as PNG/SVG from Mermaid Live Editor
- Or screenshot from GitHub rendering
- All diagrams are properly labeled and professional

---

## References

- [Mermaid Documentation](https://mermaid-js.github.io/mermaid/)
- [Mermaid Live Editor](https://mermaid.live/)
- [C4 Model](https://c4model.com/) - Architecture diagrams
