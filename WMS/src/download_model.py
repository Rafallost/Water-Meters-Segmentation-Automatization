#!/usr/bin/env python3
"""
Download Production model from MLflow to local disk.

Usage:
    python WMS/src/download_model.py --mlflow-uri http://<EC2_IP>:5000
    python WMS/src/download_model.py --force  # Re-download even if cached
"""

import argparse
import os
import sys
import torch
import mlflow
import mlflow.pytorch


def download_production_model(
    mlflow_uri: str = "http://localhost:5000",
    model_name: str = "water-meter-segmentation",
    version: str = "production",
    output_path: str = "WMS/models/production.pth",
    force: bool = False,
):
    """Download Production model from MLflow registry."""

    # Check if already cached
    if os.path.exists(output_path) and not force:
        print(f"[OK] Production model already cached: {output_path}")
        print(f"     To re-download, use --force flag")
        return output_path

    print(f"[*] Downloading Production model from MLflow...")
    print(f"    MLflow URI: {mlflow_uri}")
    print(f"    Model: {model_name}/{version}")

    try:
        # Connect to MLflow
        mlflow.set_tracking_uri(mlflow_uri)

        # Load model from registry
        model_uri = f"models:/{model_name}/{version}"
        print(f"   Loading: {model_uri}")
        model = mlflow.pytorch.load_model(model_uri, map_location="cpu")

        # Create output directory
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Save state dict
        torch.save(model.state_dict(), output_path)

        print(f"[OK] Downloaded Production model to: {output_path}")
        print(f"     You can now use it offline for predictions!")
        return output_path

    except Exception as e:
        print(f"[ERROR] Failed to download model from MLflow: {e}")
        print(f"\nTroubleshooting:")
        print(
            f"  1. Is EC2 running? Start with: gh workflow run ec2-control.yaml -f action=start"
        )
        print(f"  2. Is MLflow accessible? Check: curl {mlflow_uri}/health")
        print(f"  3. Does Production model exist? Check MLflow UI: {mlflow_uri}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download Production model from MLflow"
    )
    parser.add_argument(
        "--mlflow-uri",
        default=os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"),
        help="MLflow tracking URI (default: http://localhost:5000 or MLFLOW_TRACKING_URI env var)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if model is cached locally",
    )
    parser.add_argument(
        "--output",
        default="WMS/models/production.pth",
        help="Output path for downloaded model (default: WMS/models/production.pth)",
    )

    args = parser.parse_args()

    download_production_model(
        mlflow_uri=args.mlflow_uri, output_path=args.output, force=args.force
    )
