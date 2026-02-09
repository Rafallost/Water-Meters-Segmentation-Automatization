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

    subgraph "Git Hooks"
        B --> C{Pre-push Hook}
        C -->|Detects data changes| D[Create data/TIMESTAMP branch]
        C -->|No data changes| E[Push to main]
    end

    subgraph "GitHub Actions - Data QA"
        D --> F[Trigger PR]
        F --> G[Data Quality Check]
        G -->|Failed| H[❌ Comment on PR]
        G -->|Passed| I[✅ Approve QA]
    end

    subgraph "GitHub Actions - Training"
        I --> J[Start EC2 via Workflow]
        J --> K[Wait for k3s/MLflow]
        K --> L[Train Model x3<br/>Different seeds]
        L --> M[Log to MLflow]
    end

    subgraph "Quality Gate"
        M --> N[Fetch Production Baseline]
        N --> O{Compare Metrics}
        O -->|Dice improved| P[✅ Promote to Production]
        O -->|No improvement| Q[❌ Keep existing]
    end

    subgraph "Deployment"
        P --> R[Auto-approve PR]
        R --> S[Merge to main]
        S --> T[Build Docker Image]
        T --> U[Push to ECR]
        U --> V[Deploy to k3s]
    end

    subgraph "Monitoring"
        V --> W[Prometheus Scrapes /metrics]
        W --> X[Grafana Dashboard]
    end

    subgraph "Cleanup"
        M --> Y[Stop EC2]
        V --> Y
    end

    style P fill:#d4edda,stroke:#2e7d32,color:#000
    style Q fill:#f8d7da,stroke:#842029,color:#000
    style H fill:#f8d7da,stroke:#842029,color:#000
```

---

## 2. Training Pipeline Details

Focus on the 3-attempt training process with quality gates.

```mermaid
graph LR
    subgraph "Start Infrastructure"
        A[EC2 Stopped] --> B[GitHub Actions Trigger]
        B --> C[AWS CLI: start-instances]
        C --> D[Wait for instance-running]
        D --> E[Wait for MLflow /health]
    end

    subgraph "Train - Matrix Strategy"
        E --> F1[Attempt 1<br/>seed=run*100+1]
        E --> F2[Attempt 2<br/>seed=run*100+2]
        E --> F3[Attempt 3<br/>seed=run*100+3]
    end

    subgraph "Log Results"
        F1 --> G1[MLflow Run 1]
        F2 --> G2[MLflow Run 2]
        F3 --> G3[MLflow Run 3]
    end

    subgraph "Aggregate Results"
        G1 --> H[Download Artifacts]
        G2 --> H
        G3 --> H
        H --> I[Parse JSON Results]
        I --> J{Any Improved?}
    end

    subgraph "Promote Best Model"
        J -->|Yes| K[Find Best by Dice]
        K --> L[Register to MLflow]
        L --> M[Transition to Production]
        M --> N[Archive Old Production]
    end

    subgraph "PR Comment"
        J --> O[Generate Results Table]
        O --> P[Post to PR]
        P -->|Improved| Q[Auto-approve PR]
        P -->|Not improved| R[Manual review needed]
    end

    subgraph "Stop Infrastructure"
        J --> S[EC2 Stop]
    end

    style M fill:#d4edda,stroke:#2e7d32,color:#000
    style R fill:#f8d7da,stroke:#842029,color:#000
```

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
        C5[Access Grafana dashboard]
        C6[Query Prometheus metrics]
    end

    subgraph "🔄 Triggers EC2 Auto-start"
        D1[Push training data<br/>creates PR]
        D2[Merge PR with data<br/>starts training]
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
    title System Context Diagram - Water Meters Segmentation Platform

    Person(user, "Data Scientist", "Uploads training data,<br/>runs predictions")

    System_Boundary(github, "GitHub") {
        Container(repo, "Git Repository", "Version Control", "Code, data, configs")
        Container(actions, "GitHub Actions", "CI/CD", "Workflows, runners")
    }

    System_Boundary(aws, "AWS Cloud") {
        Container(ec2, "EC2 Instance", "t3.large", "k3s, MLflow, Docker")
        ContainerDb(s3, "S3 Bucket", "Object Storage", "DVC data, MLflow artifacts")
        Container(ecr, "ECR Registry", "Docker Registry", "Model images")
    }

    System_Boundary(k3s, "k3s Cluster (on EC2)") {
        Container(mlflow, "MLflow Server", "Python", "Experiment tracking,<br/>Model registry")
        Container(model_api, "Model API", "FastAPI", "Prediction endpoint")
        Container(prometheus, "Prometheus", "Monitoring", "Metrics collection")
        Container(grafana, "Grafana", "Visualization", "Dashboards")
    }

    Rel(user, repo, "Pushes data/code", "Git")
    Rel(repo, actions, "Triggers", "Webhook")
    Rel(actions, ec2, "Starts/stops", "AWS CLI")
    Rel(actions, s3, "Reads/writes", "DVC")
    Rel(actions, ecr, "Pushes images", "Docker")

    Rel(ec2, mlflow, "Runs on", "k3s")
    Rel(ec2, model_api, "Deploys to", "k3s")
    Rel(mlflow, s3, "Stores artifacts", "boto3")
    Rel(model_api, mlflow, "Loads model", "MLflow Client")

    Rel(prometheus, model_api, "Scrapes /metrics", "HTTP")
    Rel(grafana, prometheus, "Queries", "PromQL")
    Rel(user, grafana, "Views dashboard", "Browser")
    Rel(user, mlflow, "Browses experiments", "Browser")
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
        Pre-push hook creates branch: 7: Git Hook
        PR created automatically: 8: GitHub Actions
        Data QA runs: 7: GitHub Actions
        EC2 starts: 8: GitHub Actions
        Model trains 3x: 6: GitHub Actions
        Results posted to PR: 8: GitHub Actions
    section Review & Merge
        Check PR comment: 5: User
        Review metrics: 5: User
        Merge if improved: 5: User
    section Use Model
        Download Production model: 7: User, sync_model_aws.py
        Run local predictions: 9: User, predicts.py
        View results: 9: User
```

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
