import subprocess
import os
import sys

# Windows: ensure UTF-8 output for unicode characters (no-op on Linux/CI)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import torch
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import argparse
import json
import random
import yaml
import hashlib
from pathlib import Path
import mlflow
import mlflow.pytorch
import time
import requests

from torch import nn, optim
from torch.utils.data import DataLoader
from torchsummary import summary
from scipy.spatial.distance import directed_hausdorff
from model import WaterMetersUNet
from dataset import WMSDataset
from transforms import TrainTransforms, valTransforms
from torch.optim.lr_scheduler import ReduceLROnPlateau


# Dice coefficient
def dice_coeff(pred, target, smooth=1e-6):
    pred = pred.flatten()
    target = target.flatten()
    intersection = (pred * target).sum()  # 2*|pred ∩ GT| # GT - Ground Truth
    return (2.0 * intersection + smooth) / (
        pred.sum() + target.sum() + smooth
    )  # 2*|pred ∩ GT|


# Intersection over Union
def iou_coeff(pred, target, smooth=1e-6):
    pred = pred.flatten()
    target = target.flatten()
    intersection = (pred * target).sum()  # |pred ∩ GT|
    union = pred.sum() + target.sum() - intersection  # |pred| + |GT| − |pred ∩ GT|
    return (intersection + smooth) / (union + smooth)  # smooth to avoid division by 0


# Pixel-wise accuracy
def pixel_accuracy(pred, target):
    return (pred == target).mean()


# Safe Hausdorff distance that handles empty masks
def safe_hausdorff(pred_mask, gt_mask):
    """
    Compute Hausdorff distance with handling for empty masks.
    - If both masks are empty: return 0 (both agree there's nothing)
    - If one mask is empty and the other is not: return the image diagonal as max penalty
    - Otherwise: compute the standard Hausdorff distance
    """
    p_pts = np.argwhere(pred_mask.squeeze() == 1)
    m_pts = np.argwhere(gt_mask.squeeze() == 1)

    pred_empty = len(p_pts) == 0
    gt_empty = len(m_pts) == 0

    if pred_empty and gt_empty:
        # Both masks are empty - perfect agreement
        return 0.0
    elif pred_empty or gt_empty:
        # One mask is empty - return max possible distance (image diagonal)
        h, w = pred_mask.squeeze().shape
        return np.sqrt(h**2 + w**2)
    else:
        # Both masks have points - compute standard Hausdorff
        hd1 = directed_hausdorff(p_pts, m_pts)[0]
        hd2 = directed_hausdorff(m_pts, p_pts)[0]
        return max(hd1, hd2)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_config(config_path):
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_data_version():
    dvc_lock = Path("dvc.lock")
    if dvc_lock.exists():
        return hashlib.md5(dvc_lock.read_bytes()).hexdigest()[:8]
    return "unknown"


def get_model_version():
    git_sha = os.environ.get("GITHUB_SHA", "local")[:7]
    return f"{git_sha}-{get_data_version()}"


# ---------------------------------------------------------------------------
# CLI + seed
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Train WaterMetersUNet")
parser.add_argument("--config", default="WMS/configs/train.yaml")
parser.add_argument("--seed", type=int, default=42)
args = parser.parse_args()

config = load_config(args.config)

torch.manual_seed(args.seed)
np.random.seed(args.seed)
random.seed(args.seed)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(args.seed)

# Prepare data
prepare_script = os.path.join(os.path.dirname(__file__), "prepareDataset.py")
subprocess.run([sys.executable, prepare_script], check=True)

# Load data
baseDataDir = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "training", "temp"
)


# Utility to gather paths
def gather_paths(split):
    img_dir = os.path.join(baseDataDir, split, "images")
    mask_dir = os.path.join(baseDataDir, split, "masks")
    images = sorted(
        [
            os.path.join(img_dir, f)
            for f in os.listdir(img_dir)
            if f.endswith((".jpg", ".png"))
        ]
    )
    masks = sorted(
        [
            os.path.join(mask_dir, f)
            for f in os.listdir(mask_dir)
            if f.endswith((".jpg", ".png"))
        ]
    )
    return images, masks


trainImagePaths, trainMaskPaths = gather_paths("train")
testImagePaths, testMaskPaths = gather_paths("test")
valImagePaths, valMaskPaths = gather_paths("val")

# Use augmented transforms for training, simple transforms for val/test
trainTransforms = TrainTransforms(
    p_hflip=config["augmentation"]["horizontal_flip"],
    p_vflip=config["augmentation"]["vertical_flip"],
    rotation_degrees=config["augmentation"]["rotation_degrees"],
    p_rotate=config["augmentation"]["rotation_prob"],
    p_color_jitter=config["augmentation"]["color_jitter_prob"],
)
trainDataset = WMSDataset(
    trainImagePaths, trainMaskPaths, paired_transforms=trainTransforms
)
valDataset = WMSDataset(valImagePaths, valMaskPaths, imageTransforms=valTransforms)
testDataset = WMSDataset(testImagePaths, testMaskPaths, imageTransforms=valTransforms)

# DataLoaders
batch_size = config["training"]["batch_size"]
trainLoader = DataLoader(trainDataset, batch_size=batch_size, shuffle=True)
valLoader = DataLoader(valDataset, batch_size=batch_size, shuffle=False)
testLoader = DataLoader(testDataset, batch_size=batch_size, shuffle=False)

# Device
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

model = WaterMetersUNet(inChannels=3, outChannels=1).to(device)

# Loss, optimizer and scheduler
# Revert to pos_weight=1.0 after pos_weight=43 caused training instability
pos_weight = torch.tensor([1.0], device=device)
criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
optimizer = optim.Adam(
    model.parameters(),
    lr=config["training"]["learning_rate"],
    weight_decay=config["training"]["weight_decay"],
)
scheduler = ReduceLROnPlateau(
    optimizer,
    mode="min",
    factor=config["training"]["scheduler"]["factor"],
    patience=config["training"]["scheduler"]["patience"],
    min_lr=config["training"]["scheduler"]["min_lr"],
)

# Tracking
trainLosses, valLosses, testLosses = [], [], []
trainAccs, valAccs, testAccs = [], [], []
trainDice, valDice, testDice = [], [], []
trainIoU, valIoU, testIoU = [], [], []
epoch_logs = []
numEpochs = config["training"]["epochs"]
bestVal = float("inf")
patienceCtr = 0

# Session tracking variables
bestSessionVal = float("inf")  # Best validation loss in current session
bestSessionEpoch = 0  # Epoch with best result in session
bestSessionMetrics = {}  # Metrics of best model in session

# Load existing best.pth and validate it to get baseline for comparison
models_dir = os.path.join(os.path.dirname(__file__), "..", "models")
best_path = os.path.join(models_dir, "best.pth")
previousBestVal = float("inf")

if os.path.exists(best_path):
    print("Found existing best.pth - validating to establish baseline...")
    model.load_state_dict(torch.load(best_path, map_location=device))
    model.eval()
    runningLoss = 0.0
    with torch.no_grad():
        for images, masks in valLoader:
            images, masks = images.to(device), masks.to(device)
            outputs = model(images)
            runningLoss += criterion(outputs, masks).item()
    previousBestVal = runningLoss / len(valLoader)
    print(f"Previous best.pth validation loss: {previousBestVal:.4f}")
    print("=" * 80)
    # Reset model for training
    model = WaterMetersUNet(inChannels=3, outChannels=1).to(device)
    optimizer = optim.Adam(
        model.parameters(),
        lr=config["training"]["learning_rate"],
        weight_decay=config["training"]["weight_decay"],
    )
    scheduler = ReduceLROnPlateau(
        optimizer,
        mode="min",
        factor=config["training"]["scheduler"]["factor"],
        patience=config["training"]["scheduler"]["patience"],
        min_lr=config["training"]["scheduler"]["min_lr"],
    )

# MLflow experiment tracking
tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
if tracking_uri:
    mlflow.set_tracking_uri(tracking_uri)


def check_mlflow_health(uri, max_retries=3, timeout=10):
    """Test MLflow connectivity before starting run to avoid long hangs."""
    if not uri:
        print("⚠️  No MLFLOW_TRACKING_URI set, using local tracking")
        return True

    print(f"🔍 Testing MLflow connectivity: {uri}")

    for attempt in range(1, max_retries + 1):
        try:
            print(f"   Attempt {attempt}/{max_retries}...", end=" ", flush=True)
            response = requests.get(f"{uri}/health", timeout=timeout)
            if response.status_code == 200:
                print("✅ Connected!")
                return True
            else:
                print(f"❌ HTTP {response.status_code}")
        except requests.exceptions.Timeout:
            print(f"⏱️  Timeout after {timeout}s")
        except requests.exceptions.ConnectionError as e:
            print(f"❌ Connection failed: {e}")
        except Exception as e:
            print(f"❌ Error: {e}")

        if attempt < max_retries:
            wait = 2**attempt  # Exponential backoff: 2s, 4s, 8s
            print(f"   Retrying in {wait}s...")
            time.sleep(wait)

    print(f"\n❌ Failed to connect to MLflow after {max_retries} attempts")
    print(f"   URI: {uri}")
    print(f"   This usually means:")
    print(f"   1. EC2 instance is not running")
    print(f"   2. MLflow service is not started on EC2")
    print(f"   3. Security group blocks port 5000")
    print(f"   4. Network connectivity issue")
    sys.exit(1)


# Check MLflow connectivity before starting expensive operations
check_mlflow_health(tracking_uri)

mlflow.set_experiment("water-meter-segmentation")
mlflow.start_run(run_name=get_model_version())
mlflow.log_params(
    {
        "seed": args.seed,
        "epochs": numEpochs,
        "batch_size": config["training"]["batch_size"],
        "learning_rate": config["training"]["learning_rate"],
        "weight_decay": config["training"]["weight_decay"],
        "early_stopping_patience": config["training"]["early_stopping_patience"],
        "scheduler_factor": config["training"]["scheduler"]["factor"],
        "scheduler_patience": config["training"]["scheduler"]["patience"],
        "hflip": config["augmentation"]["horizontal_flip"],
        "vflip": config["augmentation"]["vertical_flip"],
        "rotation_degrees": config["augmentation"]["rotation_degrees"],
        "rotation_prob": config["augmentation"]["rotation_prob"],
        "color_jitter_prob": config["augmentation"]["color_jitter_prob"],
    }
)

# Training loop
for epoch in range(1, numEpochs + 1):
    model.train()
    runningLoss, runningAcc, runningDice, runningIoU = 0.0, 0.0, 0.0, 0.0

    for images, masks in trainLoader:
        images, masks = images.to(device), masks.to(device)
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, masks)
        loss.backward()
        optimizer.step()

        with torch.no_grad():
            probs = torch.sigmoid(outputs)
            preds = (probs > 0.5).float()
            preds_np = preds.cpu().numpy()
            masks_np = masks.cpu().numpy()
            batch_acc = pixel_accuracy(preds_np, masks_np)
            batch_dice = sum(
                [dice_coeff(p, m) for p, m in zip(preds_np, masks_np)]
            ) / len(preds_np)
            batch_iou = sum(
                [iou_coeff(p, m) for p, m in zip(preds_np, masks_np)]
            ) / len(preds_np)
        runningAcc += batch_acc
        runningDice += batch_dice
        runningIoU += batch_iou
        runningLoss += loss.item()

    avgTrainLoss = runningLoss / len(trainLoader)
    avgTrainAcc = runningAcc / len(trainLoader)
    avgTrainDice = runningDice / len(trainLoader)
    avgTrainIoU = runningIoU / len(trainLoader)
    trainLosses.append(avgTrainLoss)
    trainAccs.append(avgTrainAcc)
    trainDice.append(avgTrainDice)
    trainIoU.append(avgTrainIoU)

    # Validation
    model.eval()
    runningLoss, runningValAcc, runningValDice, runningValIoU = 0.0, 0.0, 0.0, 0.0
    with torch.no_grad():
        for images, masks in valLoader:
            images, masks = images.to(device), masks.to(device)
            outputs = model(images)
            runningLoss += criterion(outputs, masks).item()
            probs = torch.sigmoid(outputs)
            preds = (probs > 0.5).float()
            preds_np = preds.cpu().numpy()
            masks_np = masks.cpu().numpy()
            runningValAcc += pixel_accuracy(preds_np, masks_np)
            runningValDice += sum(
                [dice_coeff(p, m) for p, m in zip(preds_np, masks_np)]
            ) / len(preds_np)
            runningValIoU += sum(
                [iou_coeff(p, m) for p, m in zip(preds_np, masks_np)]
            ) / len(preds_np)

    avgValLoss = runningLoss / len(valLoader)
    avgValAcc = runningValAcc / len(valLoader)
    avgValDice = runningValDice / len(valLoader)
    avgValIoU = runningValIoU / len(valLoader)
    valLosses.append(avgValLoss)
    valAccs.append(avgValAcc)
    valDice.append(avgValDice)
    valIoU.append(avgValIoU)
    scheduler.step(avgValLoss)

    # Testing
    model.eval()
    runningTestLoss, runningTestAcc, runningTestDice, runningTestIoU = (
        0.0,
        0.0,
        0.0,
        0.0,
    )
    with torch.no_grad():
        for images, masks in testLoader:
            images, masks = images.to(device), masks.to(device)
            outputs = model(images)
            runningTestLoss += criterion(outputs, masks).item()
            probs = torch.sigmoid(outputs)
            preds = (probs > 0.5).float()
            preds_np = preds.cpu().numpy()
            masks_np = masks.cpu().numpy()
            runningTestAcc += pixel_accuracy(preds_np, masks_np)
            runningTestDice += sum(
                [dice_coeff(p, m) for p, m in zip(preds_np, masks_np)]
            ) / len(preds_np)
            runningTestIoU += sum(
                [iou_coeff(p, m) for p, m in zip(preds_np, masks_np)]
            ) / len(preds_np)

    avgTestLoss = runningTestLoss / len(testLoader)
    avgTestAcc = runningTestAcc / len(testLoader)
    avgTestDice = runningTestDice / len(testLoader)
    avgTestIoU = runningTestIoU / len(testLoader)
    testLosses.append(avgTestLoss)
    testAccs.append(avgTestAcc)
    testDice.append(avgTestDice)
    testIoU.append(avgTestIoU)

    # Logging
    epoch_line = (
        f"Epoch {epoch}/{numEpochs}"
        f" - Train Loss: {avgTrainLoss:.4f}, Acc: {avgTrainAcc:.4f}, Dice: {avgTrainDice:.4f}, IoU: {avgTrainIoU:.4f}"
        f" - Val Loss: {avgValLoss:.4f}, Acc: {avgValAcc:.4f}, Dice: {avgValDice:.4f}, IoU: {avgValIoU:.4f}"
        f" - Test Loss: {avgTestLoss:.4f}, Acc: {avgTestAcc:.4f}, Dice: {avgTestDice:.4f}, IoU: {avgTestIoU:.4f}"
    )
    print(epoch_line)
    epoch_logs.append(epoch_line)

    # Log to MLflow every 5 epochs or on last epoch to reduce server load
    if epoch % 5 == 0 or epoch == numEpochs:
        mlflow.log_metrics(
            {
                "train_loss": avgTrainLoss,
                "train_dice": avgTrainDice,
                "train_iou": avgTrainIoU,
                "val_loss": avgValLoss,
                "val_dice": avgValDice,
                "val_iou": avgValIoU,
                "test_loss": avgTestLoss,
                "test_dice": avgTestDice,
                "test_iou": avgTestIoU,
            },
            step=epoch,
        )

    # Save best result for current session (after all metrics are calculated)
    if avgValLoss < bestSessionVal:
        bestSessionVal = avgValLoss
        bestSessionEpoch = epoch
        bestSessionMetrics = {
            "epoch": epoch,
            "val_loss": avgValLoss,
            "val_acc": avgValAcc,
            "val_dice": avgValDice,
            "val_iou": avgValIoU,
            "test_loss": avgTestLoss,
            "test_acc": avgTestAcc,
            "test_dice": avgTestDice,
            "test_iou": avgTestIoU,
        }
        patienceCtr = 0
        torch.save(
            model.state_dict(),
            os.path.join(
                os.path.dirname(__file__), "..", "models", "best-current-session.pth"
            ),
        )
        print(
            f"  → Saved best-current-session.pth (epoch {epoch}, val_loss: {avgValLoss:.4f})"
        )
    else:
        patienceCtr += 1
        if patienceCtr >= config["training"]["early_stopping_patience"]:
            print("Early stopping")
            break

    # Saving checkpoint
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "models"), exist_ok=True)
    torch.save(
        model.state_dict(),
        os.path.join(
            os.path.dirname(__file__), "..", "models", f"unet_epoch{epoch}.pth"
        ),
    )

# Training completed - compare with previous best and update if better
print("\n" + "=" * 80)
print("Training completed!")
print(
    f"Best model from this session: epoch {bestSessionEpoch}, val_loss: {bestSessionVal:.4f}"
)
print("=" * 80)

best_session_path = os.path.join(models_dir, "best-current-session.pth")

# Compare with previous best.pth
print(f"\nPrevious best validation loss: {previousBestVal:.4f}")
print(f"Current session best validation loss: {bestSessionVal:.4f}")

results_dir = os.path.join(os.path.dirname(__file__), "..", "Results")
os.makedirs(results_dir, exist_ok=True)

if bestSessionVal < previousBestVal:
    import shutil

    shutil.copy(best_session_path, best_path)
    print(f"✓ Updated best.pth with model from epoch {bestSessionEpoch}")
    improved = True
else:
    print(
        f"✗ Current session did not improve best.pth (difference: {bestSessionVal - previousBestVal:+.4f})"
    )
    print(f"  best-current-session.pth saved for reference")
    improved = False

# Always write Terminal.log (every session, regardless of improvement)
from datetime import datetime

log_path = os.path.join(results_dir, "Terminal.log")
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

log_lines = [
    "",
    "=" * 80,
    f"Training Session - {timestamp}",
    "=" * 80,
    f"Status: {'IMPROVED — best.pth updated' if improved else 'NOT IMPROVED'}",
    f"Previous best val_loss: {previousBestVal:.4f}",
    f"Session best  val_loss: {bestSessionVal:.4f}",
    "",
    "Configuration:",
    f"  - Epochs: {numEpochs}",
    f"  - Early stopping patience: {config['training']['early_stopping_patience']}",
    f"  - Learning rate: {config['training']['learning_rate']}",
    f"  - Batch size: {config['training']['batch_size']}",
    f"  - Seed: {args.seed}",
    "",
    "--- Per-epoch metrics ---",
    *epoch_logs,
    "",
    f"Best Model (epoch {bestSessionEpoch}):",
    "  Validation Metrics:",
    f"    - Loss: {bestSessionMetrics['val_loss']:.4f}",
    f"    - Accuracy: {bestSessionMetrics['val_acc']:.4f}",
    f"    - Dice: {bestSessionMetrics['val_dice']:.4f}",
    f"    - IoU: {bestSessionMetrics['val_iou']:.4f}",
    "",
    "  Test Metrics:",
    f"    - Loss: {bestSessionMetrics['test_loss']:.4f}",
    f"    - Accuracy: {bestSessionMetrics['test_acc']:.4f}",
    f"    - Dice: {bestSessionMetrics['test_dice']:.4f}",
    f"    - IoU: {bestSessionMetrics['test_iou']:.4f}",
    "",
    "Models saved:",
    f"  - best-current-session.pth (this session)",
    f"  - unet_epoch1.pth to unet_epoch{epoch}.pth",
    "=" * 80,
    "",
]

with open(log_path, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines))

print(f"  → Terminal.log written")

# Try to upload log to MLflow (gracefully handle S3 permission errors)
try:
    mlflow.log_artifact(log_path, artifact_path="logs")
    print(f"  → Terminal.log uploaded to MLflow")
except Exception as e:
    print(f"  ⚠️  Warning: Could not upload Terminal.log to MLflow: {e}")
    print(
        f"  → Training succeeded, but artifact upload failed (AWS Academy restriction)"
    )
    # Continue - training completed successfully, log is saved locally

# Summary and plots
summary(model, input_size=(3, 512, 512))

metrics = [
    ("loss", "Loss", trainLosses, valLosses, testLosses),
    ("accuracy", "Accuracy", trainAccs, valAccs, testAccs),
    ("dice", "Dice Coefficient", trainDice, valDice, testDice),
    ("iou", "IoU", trainIoU, valIoU, testIoU),
]

for fname, ylabel, train_data, val_data, test_data in metrics:
    plt.figure(figsize=(8, 5))
    plt.plot(train_data, label="Train", color="tab:blue", marker="o", markersize=3)
    plt.plot(val_data, label="Val", color="tab:orange", marker="s", markersize=3)
    plt.plot(test_data, label="Test", color="tab:green", marker="^", markersize=3)
    plt.xlabel("Epoch")
    plt.ylabel(ylabel)
    plt.title(f"{ylabel} vs Epoch")
    plt.legend(loc="best")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, f"plot_{fname}.png"))
    print(f"  → Saved plot_{fname}.png")
    plt.show()

# Load best.pth for final evaluation
print("\n" + "=" * 80)
print("Loading best.pth for final evaluation...")
model.load_state_dict(torch.load(best_path, map_location=device))
print("=" * 80)

# Final metrics on test set
print("--- Final evaluation on test set ---")
dice_scores, iou_scores, hausdorff_dists = [], [], []
model.eval()
with torch.no_grad():
    for images, masks in testLoader:
        images, masks = images.to(device), masks.to(device)
        outputs = model(images)
        probs = torch.sigmoid(outputs)
        preds = (probs > 0.5).float().cpu().numpy()
        masks_np = masks.cpu().numpy()
        for p, m in zip(preds, masks_np):
            dice_scores.append(dice_coeff(p, m))
            iou_scores.append(iou_coeff(p, m))
            hausdorff_dists.append(safe_hausdorff(p, m))

print(f"Test Dice:      {np.mean(dice_scores):.4f}")
print(f"Test IoU:       {np.mean(iou_scores):.4f}")
print(f"Test Hausdorff: {np.mean(hausdorff_dists):.4f}")


model.eval()
images, masks = next(iter(testLoader))
images = images.to(device)
with torch.no_grad():
    outputs = model(images)
    probs = torch.sigmoid(outputs)
    preds = (probs > 0.5).float().cpu()

images = images.cpu().permute(0, 2, 3, 1).numpy()
masks = masks.cpu().squeeze(1).numpy()
preds = preds.squeeze(1).numpy()

for i in range(images.shape[0]):
    plt.figure(figsize=(12, 4))
    plt.subplot(1, 3, 1)
    plt.imshow(images[i])
    plt.title("Image")
    plt.axis("off")
    plt.subplot(1, 3, 2)
    plt.imshow(masks[i], cmap="gray")
    plt.title("GT Mask")
    plt.axis("off")
    plt.subplot(1, 3, 3)
    plt.imshow(preds[i], cmap="gray")
    plt.title("Predicted Mask")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, f"plot_pred_{i}.png"))
    print(f"  → Saved plot_pred_{i}.png")
    plt.show()

# Write metrics.json (DVC metrics output; train-with-retry.py reads this)
metrics_out = {
    "val_dice": float(bestSessionMetrics.get("val_dice", 0.0)),
    "val_iou": float(bestSessionMetrics.get("val_iou", 0.0)),
    "test_dice": float(np.mean(dice_scores)),
    "test_iou": float(np.mean(iou_scores)),
    "test_hausdorff": float(np.mean(hausdorff_dists)),
}
with open(os.path.join(models_dir, "metrics.json"), "w") as f:
    json.dump(metrics_out, f, indent=2)
print("  → Saved metrics.json")

# Log plots and model to MLflow
for png in sorted(Path(results_dir).glob("*.png")):
    mlflow.log_artifact(str(png), artifact_path="plots")
mlflow.pytorch.log_model(
    model, name="model", registered_model_name="water-meter-segmentation"
)
mlflow.end_run()
print("  → MLflow run finished")
