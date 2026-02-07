import os
import shutil
import random
from collections import defaultdict
import cv2
import numpy as np
from sklearn.model_selection import train_test_split
import torch
import torchvision
from torch.utils.data import DataLoader
from dataset import WMSDataset
from transforms import valTransforms
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

############### DATA LOAD ###############
random.seed(42)

# Source data directories
datasetPath = os.path.dirname(os.path.abspath(__file__))
sourceImageDir = os.path.join(datasetPath, "..", "data", "training", "images")
sourceMaskDir = os.path.join(datasetPath, "..", "data", "training", "masks")

# Get images and masks names
imageFiles = sorted(
    [f for f in os.listdir(sourceImageDir) if f.endswith((".jpg", ".png"))]
)
maskFiles = sorted(
    [f for f in os.listdir(sourceMaskDir) if f.endswith((".jpg", ".png"))]
)

# Create mapping from stem to full filename for masks (images and masks may have different extensions)
from pathlib import Path

mask_map = {Path(f).stem: f for f in maskFiles}
image_stems = [Path(f).stem for f in imageFiles]

# Verify all images have corresponding masks
assert len(imageFiles) == len(maskFiles), (
    "Amount of images and masks have to be the same"
)
for stem in image_stems:
    assert stem in mask_map, f"No mask found for image with stem: {stem}"

# 80% train, 10% val, 10% test
trainImgs, tempImgs = train_test_split(imageFiles, test_size=0.2, random_state=42)
valImgs, testImgs = train_test_split(tempImgs, test_size=0.5, random_state=42)

splits = {"train": trainImgs, "val": valImgs, "test": testImgs}

# Folders creation
baseDataDir = os.path.join(datasetPath, "..", "data", "training", "temp")
for split, files in splits.items():
    for subfolder in ["images", "masks"]:
        os.makedirs(os.path.join(baseDataDir, split, subfolder), exist_ok=True)
    for img_fname in files:
        # Copy image
        shutil.copy(
            os.path.join(sourceImageDir, img_fname),
            os.path.join(baseDataDir, split, "images", img_fname),
        )
        # Find and copy corresponding mask (may have different extension)
        img_stem = Path(img_fname).stem
        mask_fname = mask_map[img_stem]
        shutil.copy(
            os.path.join(sourceMaskDir, mask_fname),
            os.path.join(baseDataDir, split, "masks", mask_fname),
        )

os.makedirs("../models", exist_ok=True)

results_dir = os.path.join(datasetPath, "..", "Results")
os.makedirs(results_dir, exist_ok=True)

# Load data from folder 'train'
trainImagePaths = [
    os.path.join(baseDataDir, "train", "images", f)
    for f in os.listdir(os.path.join(baseDataDir, "train", "images"))
    if f.endswith((".jpg", ".png"))
]
trainMaskPaths = [
    os.path.join(baseDataDir, "train", "masks", f)
    for f in os.listdir(os.path.join(baseDataDir, "train", "masks"))
    if f.endswith((".jpg", ".png"))
]

testImagePaths = [
    os.path.join(baseDataDir, "test", "images", f)
    for f in os.listdir(os.path.join(baseDataDir, "test", "images"))
    if f.endswith((".jpg", ".png"))
]
testMaskPaths = [
    os.path.join(baseDataDir, "test", "masks", f)
    for f in os.listdir(os.path.join(baseDataDir, "test", "masks"))
    if f.endswith((".jpg", ".png"))
]

valImagePaths = [
    os.path.join(baseDataDir, "val", "images", f)
    for f in os.listdir(os.path.join(baseDataDir, "val", "images"))
    if f.endswith((".jpg", ".png"))
]
valMaskPaths = [
    os.path.join(baseDataDir, "val", "masks", f)
    for f in os.listdir(os.path.join(baseDataDir, "val", "masks"))
    if f.endswith((".jpg", ".png"))
]

trainDataset = WMSDataset(trainImagePaths, trainMaskPaths, valTransforms)
testDataset = WMSDataset(testImagePaths, testMaskPaths, valTransforms)
valDataset = WMSDataset(valImagePaths, valMaskPaths, valTransforms)

print(f"trainDataset length(train part): {len(trainDataset)}")
print(f"testDataset length(train part): {len(testDataset)}")
print(f"valDataset length(train part): {len(valDataset)}")

dataLoader = DataLoader(trainDataset, batch_size=5, shuffle=True)
images, masks = next(iter(dataLoader))


############### DATA VERIFICATION ###############
def count_pixel_balance(mask_paths, dataset_name):
    counts = defaultdict(int)
    for mask_path in mask_paths:
        mask_img = cv2.imread(mask_path, 0)  # Load mask as grayscale
        if mask_img is None:
            print(f"Warning: Could not load {mask_path}")
            continue
        # Apply same thresholding as in WMSDataset to avoid JPEG compression artifacts
        mask_img = (mask_img >= 127).astype(np.uint8)
        unique, cnts = np.unique(mask_img, return_counts=True)
        for cls, count in zip(unique, cnts):
            counts[cls] += count
    print(f"\nPixel distribution for the set {dataset_name}:")
    for cls, count in sorted(counts.items()):
        print(f"Class {cls}: {count} pixels")

    # Bar chart for visualization
    classes = sorted(counts.keys())
    values = [counts[c] for c in classes]
    plt.figure(figsize=(8, 6))
    plt.bar([str(c) for c in classes], values)
    plt.xlabel("Class")
    plt.ylabel("number of pixels")
    plt.title(f"Pixel distribution for the set: {dataset_name}")
    plt.tight_layout()
    plt.savefig(
        os.path.join(results_dir, f"plot_pixel_balance_{dataset_name.lower()}.png")
    )
    print(f"  → Saved plot_pixel_balance_{dataset_name.lower()}.png")
    plt.show()


############### DEVICE CONFIGURATION ###############
# determine the device to be used for training and evaluation
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
# determine if we will be pinning memory during data loading
PIN_MEMORY = True if DEVICE == "cuda" else False

############### VISUALIZATION (only when run directly) ###############
if __name__ == "__main__":
    # Count balances
    count_pixel_balance(trainMaskPaths, "Train")
    count_pixel_balance(valMaskPaths, "Validation")
    count_pixel_balance(testMaskPaths, "Test")

    # Dataset split pie chart
    sizes = [len(trainImgs), len(valImgs), len(testImgs)]
    labels = ["Train", "Validation", "Test"]

    plt.figure(figsize=(6, 6))
    plt.pie(
        sizes,
        labels=labels,
        autopct="%1.1f%%",
        startangle=140,
        pctdistance=0.85,
        labeldistance=1.1,
    )
    plt.title("Dataset Split", pad=20)
    plt.axis("equal")  # Equal aspect ratio ensures pie is drawn as a circle.
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "plot_dataset_split.png"))
    print(f"  → Saved plot_dataset_split.png")
    plt.show()

    # Sample images grid
    fig, axs = plt.subplots(5, 2, figsize=(10, 20))
    for i in range(5):
        image = images[i].permute(1, 2, 0).numpy()
        mask = masks[i].squeeze().numpy()
        axs[i, 0].imshow(image)
        axs[i, 0].set_title("Image")
        axs[i, 1].imshow(mask, cmap="gray")
        axs[i, 1].set_title("Mask")
        axs[i, 0].axis("off")
        axs[i, 1].axis("off")
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "plot_samples.png"))
    print(f"  → Saved plot_samples.png")
    plt.show()

    # PyTorch info
    print(f"\nPyTorch version: {torch.__version__}")
    print(f"Torchvision version: {torchvision.__version__}")
    print(f"GPU available: {torch.cuda.is_available()}")
    print(f"cuda version: {torch.version.cuda}")
