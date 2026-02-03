import subprocess
import os
import sys
import torch
import matplotlib.pyplot as plt
import numpy as np

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
    intersection = (pred * target).sum() # 2*|pred ∩ GT| # GT - Ground Truth
    return (2. * intersection + smooth) / (pred.sum() + target.sum() + smooth) # 2*|pred ∩ GT|


# Intersection over Union
def iou_coeff(pred, target, smooth=1e-6):
    pred = pred.flatten()
    target = target.flatten()
    intersection = (pred * target).sum() # |pred ∩ GT|
    union = pred.sum() + target.sum() - intersection # |pred| + |GT| − |pred ∩ GT|
    return (intersection + smooth) / (union + smooth) # smooth to avoid division by 0

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

# Prepare data
prepare_script = os.path.join(os.path.dirname(__file__), 'prepareDataset.py')
subprocess.run([sys.executable, prepare_script], check=True)

# Load data
baseDataDir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'training', 'temp')
# Utility to gather paths
def gather_paths(split):
    img_dir = os.path.join(baseDataDir, split, 'images')
    mask_dir = os.path.join(baseDataDir, split, 'masks')
    images = sorted([os.path.join(img_dir, f) for f in os.listdir(img_dir) if f.endswith('.jpg')])
    masks  = sorted([os.path.join(mask_dir, f) for f in os.listdir(mask_dir) if f.endswith('.jpg')])
    return images, masks

trainImagePaths, trainMaskPaths = gather_paths('train')
testImagePaths, testMaskPaths   = gather_paths('test')
valImagePaths,  valMaskPaths    = gather_paths('val')

# Use augmented transforms for training, simple transforms for val/test
trainTransforms = TrainTransforms(p_hflip=0.5, p_vflip=0.3, rotation_degrees=10, p_rotate=0.5)
trainDataset = WMSDataset(trainImagePaths, trainMaskPaths, paired_transforms=trainTransforms)
valDataset   = WMSDataset(valImagePaths,   valMaskPaths,   imageTransforms=valTransforms)
testDataset  = WMSDataset(testImagePaths,  testMaskPaths,  imageTransforms=valTransforms)

# DataLoaders
trainLoader = DataLoader(trainDataset, batch_size=4, shuffle=True)
valLoader   = DataLoader(valDataset,   batch_size=4, shuffle=False)
testLoader  = DataLoader(testDataset,  batch_size=4, shuffle=False)

# Device
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

model = WaterMetersUNet(inChannels=3, outChannels=1).to(device)

# Loss, optimizer and scheduler
# Revert to pos_weight=1.0 after pos_weight=43 caused training instability
pos_weight = torch.tensor([1.0], device=device)
criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
# Increase LR from 5e-5 to 1e-4 for faster convergence, add weight_decay for regularization
optimizer = optim.Adam(model.parameters(), lr=1e-4, weight_decay=1e-4)
scheduler = ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=3)

# Tracking
trainLosses, valLosses, testLosses = [], [], []
trainAccs, valAccs, testAccs = [], [], []
trainDice, valDice, testDice = [], [], []
trainIoU, valIoU, testIoU = [], [], []
numEpochs = 100
bestVal = float('inf')
patienceCtr = 0

# Session tracking variables
bestSessionVal = float('inf')  # Best validation loss in current session
bestSessionEpoch = 0           # Epoch with best result in session
bestSessionMetrics = {}        # Metrics of best model in session

# Load existing best.pth and validate it to get baseline for comparison
models_dir = os.path.join(os.path.dirname(__file__), '..', 'models')
best_path = os.path.join(models_dir, 'best.pth')
previousBestVal = float('inf')

if os.path.exists(best_path):
    print("Found existing best.pth - validating to establish baseline...")
    model.load_state_dict(torch.load(best_path))
    model.eval()
    runningLoss = 0.0
    with torch.no_grad():
        for images, masks in valLoader:
            images, masks = images.to(device), masks.to(device)
            outputs = model(images)
            runningLoss += criterion(outputs, masks).item()
    previousBestVal = runningLoss / len(valLoader)
    print(f"Previous best.pth validation loss: {previousBestVal:.4f}")
    print("="*80)
    # Reset model for training
    model = WaterMetersUNet(inChannels=3, outChannels=1).to(device)
    optimizer = optim.Adam(model.parameters(), lr=1e-4, weight_decay=1e-4)
    scheduler = ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=3)

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
            batch_dice = sum([dice_coeff(p, m) for p, m in zip(preds_np, masks_np)]) / len(preds_np)
            batch_iou = sum([iou_coeff(p, m) for p, m in zip(preds_np, masks_np)]) / len(preds_np)
        runningAcc  += batch_acc
        runningDice += batch_dice
        runningIoU  += batch_iou
        runningLoss += loss.item()

    avgTrainLoss = runningLoss / len(trainLoader)
    avgTrainAcc  = runningAcc  / len(trainLoader)
    avgTrainDice = runningDice / len(trainLoader)
    avgTrainIoU  = runningIoU  / len(trainLoader)
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
            runningValDice += sum([dice_coeff(p, m) for p, m in zip(preds_np, masks_np)]) / len(preds_np)
            runningValIoU += sum([iou_coeff(p, m) for p, m in zip(preds_np, masks_np)]) / len(preds_np)

    avgValLoss = runningLoss / len(valLoader)
    avgValAcc  = runningValAcc / len(valLoader)
    avgValDice = runningValDice / len(valLoader)
    avgValIoU  = runningValIoU / len(valLoader)
    valLosses.append(avgValLoss)
    valAccs.append(avgValAcc)
    valDice.append(avgValDice)
    valIoU.append(avgValIoU)
    scheduler.step(avgValLoss)

    # Testing
    model.eval()
    runningTestLoss, runningTestAcc, runningTestDice, runningTestIoU = 0.0, 0.0, 0.0, 0.0
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
            runningTestDice += sum([dice_coeff(p, m) for p, m in zip(preds_np, masks_np)]) / len(preds_np)
            runningTestIoU += sum([iou_coeff(p, m) for p, m in zip(preds_np, masks_np)]) / len(preds_np)

    avgTestLoss = runningTestLoss / len(testLoader)
    avgTestAcc  = runningTestAcc  / len(testLoader)
    avgTestDice = runningTestDice / len(testLoader)
    avgTestIoU  = runningTestIoU  / len(testLoader)
    testLosses.append(avgTestLoss)
    testAccs.append(avgTestAcc)
    testDice.append(avgTestDice)
    testIoU.append(avgTestIoU)

    # Logging
    print(f"Epoch {epoch}/{numEpochs}"
          f" - Train Loss: {avgTrainLoss:.4f}, Acc: {avgTrainAcc:.4f}, Dice: {avgTrainDice:.4f}, IoU: {avgTrainIoU:.4f}"
          f" - Val Loss: {avgValLoss:.4f}, Acc: {avgValAcc:.4f}, Dice: {avgValDice:.4f}, IoU: {avgValIoU:.4f}"
          f" - Test Loss: {avgTestLoss:.4f}, Acc: {avgTestAcc:.4f}, Dice: {avgTestDice:.4f}, IoU: {avgTestIoU:.4f}")

    # Save best result for current session (after all metrics are calculated)
    if avgValLoss < bestSessionVal:
        bestSessionVal = avgValLoss
        bestSessionEpoch = epoch
        bestSessionMetrics = {
            'epoch': epoch,
            'val_loss': avgValLoss,
            'val_acc': avgValAcc,
            'val_dice': avgValDice,
            'val_iou': avgValIoU,
            'test_loss': avgTestLoss,
            'test_acc': avgTestAcc,
            'test_dice': avgTestDice,
            'test_iou': avgTestIoU
        }
        patienceCtr = 0
        torch.save(model.state_dict(),
                   os.path.join(os.path.dirname(__file__), '..', 'models', 'best-current-session.pth'))
        print(f"  → Saved best-current-session.pth (epoch {epoch}, val_loss: {avgValLoss:.4f})")
    else:
        patienceCtr += 1
        if patienceCtr >= 5:
            print("Early stopping")
            break

    # Saving checkpoint
    os.makedirs(os.path.join(os.path.dirname(__file__), '..', 'models'), exist_ok=True)
    torch.save(model.state_dict(), os.path.join(os.path.dirname(__file__), '..', 'models', f'unet_epoch{epoch}.pth'))

# Training completed - compare with previous best and update if better
print("\n" + "="*80)
print("Training completed!")
print(f"Best model from this session: epoch {bestSessionEpoch}, val_loss: {bestSessionVal:.4f}")
print("="*80)

best_session_path = os.path.join(models_dir, 'best-current-session.pth')

# Compare with previous best.pth
print(f"\nPrevious best validation loss: {previousBestVal:.4f}")
print(f"Current session best validation loss: {bestSessionVal:.4f}")

results_dir = os.path.join(os.path.dirname(__file__), '..', 'Results')
os.makedirs(results_dir, exist_ok=True)

if bestSessionVal < previousBestVal:
    # Current session improved - update best.pth and Terminal.log
    import shutil
    shutil.copy(best_session_path, best_path)
    print(f"✓ Updated best.pth with model from epoch {bestSessionEpoch}")

    # Save training results to Terminal.log
    log_path = os.path.join(results_dir, 'Terminal.log')

    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_content = f"""
{'='*80}
Training Session - {timestamp}
{'='*80}
Configuration:
  - Epochs: {numEpochs}
  - Early stopping patience: 5
  - Learning rate: 1e-4
  - Batch size: 4

Best Model (epoch {bestSessionEpoch}):
  Validation Metrics:
    - Loss: {bestSessionMetrics['val_loss']:.4f}
    - Accuracy: {bestSessionMetrics['val_acc']:.4f}
    - Dice: {bestSessionMetrics['val_dice']:.4f}
    - IoU: {bestSessionMetrics['val_iou']:.4f}

  Test Metrics:
    - Loss: {bestSessionMetrics['test_loss']:.4f}
    - Accuracy: {bestSessionMetrics['test_acc']:.4f}
    - Dice: {bestSessionMetrics['test_dice']:.4f}
    - IoU: {bestSessionMetrics['test_iou']:.4f}

Models saved:
  - best.pth (global best) - UPDATED
  - best-current-session.pth (this session)
  - unet_epoch1.pth to unet_epoch{epoch}.pth
{'='*80}

"""

    with open(log_path, 'w', encoding='utf-8') as f:
        f.write(log_content)

    print(f"✓ Training results saved to {log_path}")
else:
    # Current session did not improve
    print(f"✗ Current session did not improve best.pth (difference: {bestSessionVal - previousBestVal:+.4f})")
    print(f"  best.pth and Terminal.log were NOT updated")
    print(f"  best-current-session.pth saved for reference")

# Summary and plots
summary(model, input_size=(3, 512, 512))

metrics = [
    ('loss',     'Loss',             trainLosses, valLosses, testLosses),
    ('accuracy', 'Accuracy',         trainAccs,   valAccs,   testAccs),
    ('dice',     'Dice Coefficient', trainDice,   valDice,   testDice),
    ('iou',      'IoU',              trainIoU,    valIoU,    testIoU),
]

for fname, ylabel, train_data, val_data, test_data in metrics:
    plt.figure(figsize=(8, 5))
    plt.plot(train_data, label='Train', color='tab:blue',   marker='o', markersize=3)
    plt.plot(val_data,   label='Val',   color='tab:orange', marker='s', markersize=3)
    plt.plot(test_data,  label='Test',  color='tab:green',  marker='^', markersize=3)
    plt.xlabel('Epoch')
    plt.ylabel(ylabel)
    plt.title(f'{ylabel} vs Epoch')
    plt.legend(loc='best')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, f'plot_{fname}.png'))
    print(f"  → Saved plot_{fname}.png")
    plt.show()

# Load best.pth for final evaluation
print("\n" + "="*80)
print("Loading best.pth for final evaluation...")
model.load_state_dict(torch.load(best_path))
print("="*80)

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
    plt.figure(figsize=(12,4))
    plt.subplot(1,3,1)
    plt.imshow(images[i])
    plt.title('Image')
    plt.axis('off')
    plt.subplot(1,3,2)
    plt.imshow(masks[i], cmap='gray')
    plt.title('GT Mask')
    plt.axis('off')
    plt.subplot(1,3,3)
    plt.imshow(preds[i], cmap='gray')
    plt.title('Predicted Mask')
    plt.axis('off')
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, f'plot_pred_{i}.png'))
    print(f"  → Saved plot_pred_{i}.png")
    plt.show()