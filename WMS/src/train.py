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
numEpochs = 200
bestVal = float('inf')
patienceCtr = 0

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

    # Save best result
    if avgValLoss < bestVal:
        bestVal = avgValLoss
        patienceCtr = 0
        torch.save(model.state_dict(), os.path.join(os.path.dirname(__file__), '..', 'models', f'best.pth'))
    else:
        patienceCtr += 1
        if patienceCtr >= 5:
            print("Early stopping")
            break

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

    # Saving checkpoint
    os.makedirs(os.path.join(os.path.dirname(__file__), '..', 'models'), exist_ok=True)
    torch.save(model.state_dict(), os.path.join(os.path.dirname(__file__), '..', 'models', f'unet_epoch{epoch}.pth'))

# Summary and plots
summary(model, input_size=(3, 512, 512))

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Plot 1: Loss
axes[0, 0].plot(trainLosses, label='Train', color='tab:blue', marker='o', markersize=3)
axes[0, 0].plot(valLosses,   label='Val', color='tab:orange', marker='s', markersize=3)
axes[0, 0].plot(testLosses,  label='Test', color='tab:green', marker='^', markersize=3)
axes[0, 0].set_xlabel('Epoch')
axes[0, 0].set_ylabel('Loss')
axes[0, 0].set_title('Loss vs Epoch')
axes[0, 0].legend(loc='best')
axes[0, 0].grid(True, alpha=0.3)

# Plot 2: Accuracy
axes[0, 1].plot(trainAccs, label='Train', color='tab:blue', marker='o', markersize=3)
axes[0, 1].plot(valAccs,   label='Val', color='tab:orange', marker='s', markersize=3)
axes[0, 1].plot(testAccs,  label='Test', color='tab:green', marker='^', markersize=3)
axes[0, 1].set_xlabel('Epoch')
axes[0, 1].set_ylabel('Accuracy')
axes[0, 1].set_title('Accuracy vs Epoch')
axes[0, 1].legend(loc='best')
axes[0, 1].grid(True, alpha=0.3)

# Plot 3: Dice Coefficient
axes[1, 0].plot(trainDice, label='Train', color='tab:blue', marker='o', markersize=3)
axes[1, 0].plot(valDice,   label='Val', color='tab:orange', marker='s', markersize=3)
axes[1, 0].plot(testDice,  label='Test', color='tab:green', marker='^', markersize=3)
axes[1, 0].set_xlabel('Epoch')
axes[1, 0].set_ylabel('Dice Coefficient')
axes[1, 0].set_title('Dice Coefficient vs Epoch')
axes[1, 0].legend(loc='best')
axes[1, 0].grid(True, alpha=0.3)

# Plot 4: IoU (Intersection over Union)
axes[1, 1].plot(trainIoU, label='Train', color='tab:blue', marker='o', markersize=3)
axes[1, 1].plot(valIoU,   label='Val', color='tab:orange', marker='s', markersize=3)
axes[1, 1].plot(testIoU,  label='Test', color='tab:green', marker='^', markersize=3)
axes[1, 1].set_xlabel('Epoch')
axes[1, 1].set_ylabel('IoU')
axes[1, 1].set_title('IoU vs Epoch')
axes[1, 1].legend(loc='best')
axes[1, 1].grid(True, alpha=0.3)

plt.suptitle('Training Metrics', fontsize=16, fontweight='bold')
plt.tight_layout()
plt.show()

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
    plt.show()