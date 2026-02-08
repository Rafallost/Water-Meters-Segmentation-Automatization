#!/usr/bin/env python3
"""Check MLflow model versions and promote to Production if needed."""

import sys
import mlflow
from mlflow.tracking import MlflowClient

# MLflow URI
MLFLOW_URI = "http://100.49.195.150:5000"
MODEL_NAME = "water-meter-segmentation"

print(f"Connecting to MLflow: {MLFLOW_URI}")
mlflow.set_tracking_uri(MLFLOW_URI)
client = MlflowClient()

print(f"\nSearching for model: {MODEL_NAME}")
versions = client.search_model_versions(f'name="{MODEL_NAME}"')

if not versions:
    print(f"[ERROR] No versions found for model '{MODEL_NAME}'")
    sys.exit(1)

print(f"\nFound {len(versions)} version(s):\n")
for v in versions:
    status = "<<< PRODUCTION" if v.current_stage == "Production" else ""
    print(f"  Version {v.version}:")
    print(f"    Stage: {v.current_stage} {status}")
    print(f"    Run ID: {v.run_id}")
    print()

# Check if any version is in Production
prod_versions = [v for v in versions if v.current_stage == "Production"]

if prod_versions:
    print(f"[OK] {len(prod_versions)} version(s) in Production stage")
    print("\nYou can now download the model:")
    print(f"  python WMS/scripts/sync_model_aws.py")
else:
    print("[WARNING] No versions in Production stage!")
    print("\nTo promote the latest version to Production:")

    # Get latest version
    latest = sorted(versions, key=lambda v: int(v.version), reverse=True)[0]

    print(f"\nLatest version: {latest.version} (stage: {latest.current_stage})")
    response = input("\nPromote this version to Production? (y/n): ").strip().lower()

    if response == 'y':
        print(f"\nPromoting version {latest.version} to Production...")
        client.transition_model_version_stage(
            name=MODEL_NAME,
            version=latest.version,
            stage="Production",
            archive_existing_versions=True
        )
        print(f"[OK] Version {latest.version} is now in Production!")
        print("\nNow you can download the model:")
        print(f"  python WMS/scripts/sync_model_aws.py")
    else:
        print("\nSkipped promotion.")
        print("\nManual promotion command:")
        print(f"  python -c \"from mlflow import MlflowClient; c = MlflowClient(); c.transition_model_version_stage('{MODEL_NAME}', '{latest.version}', 'Production')\"")
