# Monitoring & Observability Guide

This guide explains how to deploy and use the monitoring stack (Prometheus + Grafana) for the WMS model API.

## ⚠️ Important: Resource Requirements

**Instance:** t3.large (8 GB RAM, 2 vCPU)

The monitoring stack adds significant resource usage:
- Prometheus: ~400-800 MB RAM
- Grafana: ~128-256 MB RAM
- Alertmanager: ~64-128 MB RAM

---

## 📋 Prerequisites

1. **EC2 instance running** (t3.large)
2. **k3s installed** and accessible
3. **WMS model deployed** (see deployment docs)
4. **kubectl configured** to access k3s cluster

---

## 🚀 Quick Start

### 1. Add Prometheus Helm Repository

```bash
# Add repo
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

### 2. Install kube-prometheus-stack

```bash
# Create monitoring namespace
kubectl create namespace monitoring

# Install Prometheus + Grafana
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --values helm/monitoring/values.yaml \
  --wait

# Wait 3-5 minutes for all pods to start
kubectl get pods -n monitoring -w
```

**Expected pods:**
- prometheus-kube-prometheus-stack-prometheus-0
- prometheus-kube-prometheus-stack-operator-...
- prometheus-grafana-...
- alertmanager-kube-prometheus-stack-alertmanager-0

### 3. Deploy ServiceMonitor

```bash
# Tell Prometheus to scrape WMS model metrics
kubectl apply -f helm/monitoring/servicemonitor.yaml

# Verify ServiceMonitor created
kubectl get servicemonitor wms-model-metrics
```

### 4. Load Grafana Dashboard

```bash
# Create ConfigMap with dashboard JSON
kubectl create configmap wms-dashboard-configmap \
  --from-file=wms-model.json=helm/monitoring/dashboards/wms-model.json \
  -n monitoring

# Restart Grafana to load dashboard
kubectl rollout restart deployment prometheus-grafana -n monitoring
```

---

## 🔍 Accessing the UIs

### Prometheus UI

```bash
# Port forward Prometheus
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090

# Open in browser: http://localhost:9090
```

**What to check:**
1. Status → Targets → Look for `wms-model-metrics` endpoint
2. Should show as **UP** with recent scrape timestamp
3. If DOWN, check ServiceMonitor and model deployment

### Grafana UI

```bash
# Port forward Grafana
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80

# Open in browser: http://localhost:3000
# Username: admin
# Password: admin (or check values.yaml if changed)
```

**Navigate to dashboard:**
1. Click "Dashboards" (left sidebar)
2. Browse → "WMS Model" folder
3. Click "WMS Model Performance"

---

## 📊 Dashboard Panels

The WMS Model Performance dashboard includes:

### Top Row - Key Metrics
1. **Requests per Second** - Current prediction rate
2. **Latency (p50)** - Median response time
3. **Latency (p95)** - 95th percentile response time
4. **Error Rate** - Percentage of failed predictions

### Middle Row - Time Series
5. **Request Rate Over Time** - Traffic patterns
6. **Latency Percentiles** - p50, p95, p99 over time

### Bottom Row - Resources
7. **Pod Memory Usage** - RAM consumption
8. **Pod CPU Usage** - CPU utilization

---

## 🧪 Testing the Monitoring

### 1. Generate Test Traffic

```bash
# Send test prediction requests
for i in {1..100}; do
  curl -X POST http://<MODEL_SERVICE>:8000/predict \
    -F "file=@test-image.jpg" \
    -s -o /dev/null -w "Request $i: %{http_code}\n"
  sleep 0.1
done
```

### 2. Watch Metrics Update

Open Grafana dashboard and observe:
- ✅ Request count increases
- ✅ Latency histogram updates
- ✅ CPU/Memory graphs show activity

### 3. Query Metrics in Prometheus

```promql
# Total predictions
sum(wms_predictions_total)

# Request rate (last 5 min)
sum(rate(wms_predictions_total[5m]))

# p95 latency
histogram_quantile(0.95, sum(rate(wms_predict_latency_seconds_bucket[5m])) by (le))

# Error rate
sum(rate(wms_predict_errors_total[5m])) / sum(rate(wms_predictions_total[5m]))
```

---

## 📈 Available Metrics

The FastAPI app exposes these Prometheus metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `wms_predictions_total` | Counter | Total predictions made |
| `wms_predict_latency_seconds` | Histogram | Prediction latency distribution |
| `wms_predict_errors_total` | Counter | Total prediction errors |
| `wms_model_loaded` | Gauge | Model load status (1=loaded, 0=not) |

**Custom labels** (if added):
- `model_version` - MLflow model version
- `endpoint` - API endpoint name

---

## 🔧 Troubleshooting

### Prometheus Not Scraping Model

**Symptom:** Prometheus Targets page shows `wms-model-metrics` as DOWN

**Solutions:**
```bash
# 1. Check ServiceMonitor
kubectl get servicemonitor wms-model-metrics -o yaml

# 2. Check Service labels match
kubectl get svc wms-model -o yaml | grep -A5 labels

# 3. Check model pod is running
kubectl get pods -l app=wms-model

# 4. Test metrics endpoint manually
kubectl port-forward svc/wms-model 8000:8000
curl http://localhost:8000/metrics
```

### Dashboard Not Showing Data

**Symptom:** Grafana dashboard panels show "No data"

**Solutions:**
```bash
# 1. Check Prometheus has data
# Prometheus UI → Graph → Query: wms_predictions_total
# Should show some data points

# 2. Check dashboard data source
# Grafana → Dashboard → Settings → Variables
# Ensure "Prometheus" is selected

# 3. Check time range
# Dashboard top-right → Last 1 hour or longer
```

### High Memory Usage / OOM Kills

**Symptom:** Pods get killed, node shows DiskPressure or MemoryPressure

**Solutions:**
```bash
# 1. Check resource usage
kubectl top nodes
kubectl top pods -n monitoring

# 2. Reduce Prometheus retention
# Edit values.yaml: retention: 3d (instead of 7d)

# 3. Reduce scrape interval
# Edit servicemonitor.yaml: interval: 30s (instead of 15s)
```

### Grafana Login Issues

**Symptom:** Can't login to Grafana

**Solutions:**
```bash
# 1. Get admin password
kubectl get secret -n monitoring prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode

# 2. Reset password
kubectl exec -n monitoring prometheus-grafana-... -- \
  grafana-cli admin reset-admin-password newpassword

# 3. Check if pod is running
kubectl get pods -n monitoring | grep grafana
```

---

## 🗑️ Cleanup

**Important:** Uninstall monitoring stack before stopping EC2 to avoid issues on restart.

```bash
# Uninstall Prometheus/Grafana
helm uninstall kube-prometheus-stack -n monitoring

# Delete namespace
kubectl delete namespace monitoring

# Delete ServiceMonitor
kubectl delete servicemonitor wms-model-metrics

# Delete ConfigMap
kubectl delete configmap wms-dashboard-configmap -n monitoring
```

---

## 💰 Cost Management

### During Active Testing

Keep monitoring stack running while testing:
- Cost: ~$0.08/hour (t3.large)
- Good for: Load testing, debugging, optimization

### When Not Testing

Tear down monitoring stack:
```bash
helm uninstall kube-prometheus-stack -n monitoring
# Saves ~200-400 MB RAM
```

### Long-term Strategy

**Option 1: Deploy on-demand**
- Install monitoring when needed
- Takes ~5 minutes to deploy
- Total ~10-15 runs during thesis = ~$6

**Option 2: Always-on (if budget allows)**
- Keep monitoring running 24/7
- Full observability
- ~$60/month (t3.large 24/7)

---

## 📚 Further Reading

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [kube-prometheus-stack Chart](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
- [Prometheus Best Practices](https://prometheus.io/docs/practices/naming/)

---

## 📸 Screenshots for Thesis

### Key Screenshots to Capture:

1. **Grafana Dashboard** - Full view with all panels showing live data
2. **Prometheus Targets** - ServiceMonitor showing UP status
3. **Load Test Results** - High RPS with latency percentiles
4. **Resource Usage** - CPU/Memory graphs during load
5. **Error Handling** - Error rate when model fails

These demonstrate:
- ✅ Complete observability stack
- ✅ Production-grade monitoring
- ✅ Real-time metrics
- ✅ Industry best practices for MLOps
